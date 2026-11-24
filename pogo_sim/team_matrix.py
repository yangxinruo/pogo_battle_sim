"""队伍对队伍（3v3-f2）：我方一队或几队，对很多队对手各打一场 3v3，输出 Markdown 报告。

对手队伍是配置里手写的，加上从环境前 N 随机抽的（docs/mechanics.md 13.2 D5，用户 2026-11-21 选定）。
用 tools/run_team_matrix.py 运行。例子：experiments/gl_team_matrix_example.toml。

文件格式（和 3v3 配置 team_battle.py 相同的部分不再细说）：
    description、custom_files、league、season、[rules]、[policy]   # 同 team_battle.py；[policy] 所有队伍共用

    [[team]]                     # 我方队伍，至少一队。写法同 team_battle.py 的 [[team]]：
    name = "Team A"              #   name、可选 shields、可选 [team.policy]、[[team.member]] 正好 3 只
    [[team.member]]
    ...

    [[opponent_team]]            # 可选：手写的对手队伍，写法同 [[team]]（[opponent_team.policy]、[[opponent_team.member]]）
    ...

    [opponent_sample]            # 可选：从环境前 N 随机抽对手队伍
    rankings = "mega"            # 从哪套 PvPoke 排名抽（rankings.RANKING_CUPS）
    top = 30                     # 非 Mega 从这一类的前 top 只里抽
    mega_top = 10                # 可选，默认 0。大于 0：每队正好 1 只 Mega，从 Mega 前 mega_top 只里抽；0：不带 Mega
    count = 50                   # 抽几队
    seed = 1                     # 随机种子：同一个种子每次抽出同样的队伍
    ivs = "rank1"                # 可选：IV 规则（rankings.IV_RULES），默认 IV 排名第 1
    shields = 2                  # 可选，默认 2
    [opponent_sample.policy]     # 可选：只改抽样队伍的策略参数，逐项覆盖 [policy]

手写的对手和抽样至少写一种。所有队伍的名字都不能重复；抽样的队伍叫"抽样 1"……"抽样 N"。

抽样的规则（每一队）：
- 有 Mega 时先从 Mega 候选里均匀抽 1 只；再把非 Mega 候选洗牌，按顺序取，跳过和已选的同一种的（按图鉴编号，
  暗影、Mega、地区形态都算同一种），取满一队；最后把这一队的出场顺序洗牌。
- 均匀抽，不按名次加权。成员相同（不论顺序）的队伍只留一个，重抽。
- 随机数只用 random.Random(seed).random()：Python 只保证它在不同版本下对同一个种子给出同样的序列。

对战：我方每一队对每一队对手打一场，我方是第 0 方。每队只建一次配置；对位评估器按评估配置在全部对战之间共用
（缓存键不含是哪一场，结果和一场一场单独打相同，测试里核对）。对战是确定的：同一个配置每次结果相同。
"""

import csv
import io
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pogo_sim.battle import BattleResult
from pogo_sim.config import (
    ConfigError,
    Entry,
    Participant,
    check_unknown_keys,
    format_params,
    format_participant,
    format_table,
    load_toml,
    marked,
    merge_tables,
    parse_params,
)
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.rankings import (
    IV_RULES,
    RANKING_CUPS,
    Pool,
    PoolMember,
    PoolSpec,
    format_pool_members,
    format_skipped,
    prepare_pool,
    ranked_entry,
)
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.season import SeasonRules, league_name
from pogo_sim.simple_policy import SimplePolicyConfig
from pogo_sim.team_battle import (
    TeamBattle,
    TeamBattleConfig,
    TeamSetup,
    assemble_team_battle,
    check_prepared_team,
    parse_common_settings,
    parse_team,
    policy_text,
    prepare_team,
    run_team_battle,
)
from pogo_sim.team_policy import TeamPolicyConfig

_TOP_LEVEL_KEYS = {
    "description", "custom_files", "league", "season", "rules", "policy",
    "team", "opponent_team", "opponent_sample",
}
_SAMPLE_KEYS = frozenset({"rankings", "top", "mega_top", "count", "seed", "ivs", "shields", "policy"})

GROUP_OURS = "我方"
GROUP_HANDWRITTEN = "手写"
GROUP_SAMPLED = "抽样"

# 抽样时，平均每队最多试这么多次（成员相同的队伍要重抽）
_ATTEMPTS_PER_TEAM = 50


# ---- 配置 ----


@dataclass(frozen=True)
class SampleSpec:
    """[opponent_sample]：从环境前 N 随机抽对手队伍。"""

    rankings: str  # RANKING_CUPS 的键
    top: int  # 非 Mega 候选：这一类的前 top 只
    mega_top: int  # Mega 候选：前 mega_top 只；0 表示不带 Mega
    count: int
    seed: int
    ivs: str  # IV_RULES 的键
    shields: int
    policy: TeamPolicyConfig

    def team_name(self, i: int) -> str:
        """第 i 队（从 0 数）的名字。"""
        return f"{GROUP_SAMPLED} {i + 1}"

    def pool_specs(self) -> tuple[PoolSpec, ...]:
        """候选：非 Mega 前 top，以及（mega_top > 0 时）Mega 前 mega_top。"""
        specs = [PoolSpec(f"非 Mega 前 {self.top}", self.rankings, "non_mega", self.top, self.ivs)]
        if self.mega_top:
            specs.append(PoolSpec(f"Mega 前 {self.mega_top}", self.rankings, "mega", self.mega_top, self.ivs))
        return tuple(specs)

    def describe(self, league: int, size: int) -> str:
        """size 是每队几只。"""
        if self.mega_top:
            makeup = (
                f"每队 1 只 Mega（Mega 前 {self.mega_top} 只里抽）和 {size - 1} 只非 Mega"
                f"（非 Mega 前 {self.top} 只里抽）"
            )
        else:
            makeup = f"每队 {size} 只非 Mega（非 Mega 前 {self.top} 只里抽），不带 Mega"
        return (
            f"从 PvPoke 的 {self.rankings} 排名（{RANKING_CUPS[self.rankings]}，{league_name(league)}）随机抽 "
            f"{self.count} 队，随机种子 {self.seed}：{makeup}；同一种不重复，出场顺序随机，"
            f"均匀抽、不按名次加权；{IV_RULES[self.ivs]}"
        )


@dataclass(frozen=True)
class TeamMatrixConfig:
    description: str
    custom_files: tuple[Path, ...]
    league: int
    season: SeasonRules
    rules: BattleRules
    teams: tuple[TeamSetup, ...]  # 我方
    opponent_teams: tuple[TeamSetup, ...]  # 手写的对手
    sample: SampleSpec | None


def load_team_matrix_config(path: Path | str) -> TeamMatrixConfig:
    """读取并检查队伍对队伍的配置文件（格式见模块说明）。写错时抛出 ConfigError。"""
    path = Path(path)
    raw = load_toml(path)
    where = path.name

    check_unknown_keys(raw, _TOP_LEVEL_KEYS, where)
    for key in ("league", "season", "team"):
        if key not in raw:
            raise ConfigError(f"{where}：缺少 {key}")
    if "opponent_team" not in raw and "opponent_sample" not in raw:
        raise ConfigError(f"{where}：缺少对手（[[opponent_team]] 或 [opponent_sample]）")
    settings = parse_common_settings(raw, where)
    rules = settings.rules

    teams = _parse_teams(raw["team"], settings.shared_policy, rules, f"{where}：我方", "team")
    opponent_teams = (
        _parse_teams(raw["opponent_team"], settings.shared_policy, rules, f"{where}：对手", "opponent_team")
        if "opponent_team" in raw
        else ()
    )
    sample = (
        _parse_sample(raw["opponent_sample"], settings.shared_policy, rules, f"{where}：opponent_sample")
        if "opponent_sample" in raw
        else None
    )

    names = [t.name for t in (*teams, *opponent_teams)]
    if sample is not None:
        names += [sample.team_name(i) for i in range(sample.count)]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(
            f"{where}：队伍名字不能重复：{', '.join(duplicates)}"
            f"（抽样的队伍叫\"{GROUP_SAMPLED} 1\"……，手写的队伍别用这种名字）"
        )

    return TeamMatrixConfig(
        description=settings.description,
        custom_files=settings.custom_files,
        league=settings.league,
        season=settings.season,
        rules=rules,
        teams=teams,
        opponent_teams=opponent_teams,
        sample=sample,
    )


def _parse_teams(
    raw: Any, shared_policy: dict[str, Any], rules: BattleRules, where: str, table: str
) -> tuple[TeamSetup, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{where}：要写成 [[{table}]] 表，至少一队")
    return tuple(
        parse_team(team, shared_policy, rules, f"{where}第 {i + 1} 队", table) for i, team in enumerate(raw)
    )


def _parse_sample(raw: Any, shared_policy: dict[str, Any], rules: BattleRules, where: str) -> SampleSpec:
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}：要写成 [opponent_sample] 表，得到 {raw!r}")
    check_unknown_keys(raw, _SAMPLE_KEYS, where)
    for key in ("rankings", "top", "count", "seed"):
        if key not in raw:
            raise ConfigError(f"{where}：缺少 {key}")

    def integer(key: str, default: int, minimum: int | None, expected: str) -> int:
        value = raw.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or (minimum is not None and value < minimum):
            raise ConfigError(f"{where}：{key} 要写{expected}，得到 {value!r}")
        return value

    def choice(key: str, default: str, options: dict[str, str]) -> str:
        value = raw.get(key, default)
        if not isinstance(value, str) or value not in options:
            raise ConfigError(f"{where}：{key} 要写 {' / '.join(repr(o) for o in options)}，得到 {value!r}")
        return value

    shields = raw.get("shields", rules.max_shields)
    if not isinstance(shields, int) or isinstance(shields, bool) or not 0 <= shields <= rules.max_shields:
        raise ConfigError(f"{where}：shields 要写 0 到 {rules.max_shields} 的整数，得到 {shields!r}")
    sample_policy = raw.get("policy", {})
    if not isinstance(sample_policy, dict):
        raise ConfigError(f"{where}：policy 要写成表（[opponent_sample.policy]）")

    return SampleSpec(
        rankings=choice("rankings", "", RANKING_CUPS),
        top=integer("top", 0, 1, "正整数"),
        mega_top=integer("mega_top", 0, 0, "不小于 0 的整数"),
        count=integer("count", 0, 1, "正整数"),
        seed=integer("seed", 0, None, "整数"),
        ivs=choice("ivs", "rank1", IV_RULES),
        shields=shields,
        policy=parse_params(TeamPolicyConfig, merge_tables(shared_policy, sample_policy), where, "策略参数"),
    )


# ---- 建配置、抽样 ----


@dataclass(frozen=True)
class MatrixTeam:
    """建好配置的一队。"""

    setup: TeamSetup
    members: tuple[Participant, ...]  # 按出场顺序
    group: str  # GROUP_OURS / GROUP_HANDWRITTEN / GROUP_SAMPLED
    ranks: tuple[int, ...] = ()  # 抽样的队伍：每只在排名文件里的名次

    @property
    def name(self) -> str:
        return self.setup.name

    def member_names(self) -> list[str]:
        """每只的名字，抽样的后面带排名里的名次，例如 "Altaria #3"。"""
        names = [marked(p) for p in self.members]
        if self.ranks:
            names = [f"{name} #{rank}" for name, rank in zip(names, self.ranks)]
        return names


@dataclass(frozen=True)
class Sample:
    """抽好的对手队伍和候选。"""

    spec: SampleSpec
    pools: tuple[Pool, ...]  # 候选：非 Mega，以及 Mega（有的话）
    teams: tuple[MatrixTeam, ...]


@dataclass(frozen=True)
class TeamMatrix:
    config: TeamMatrixConfig
    gm: GameMaster
    teams: tuple[MatrixTeam, ...]  # 我方
    opponents: tuple[MatrixTeam, ...]  # 手写的在前，抽样的在后
    sample: Sample | None


def prepare_team_matrix(config: TeamMatrixConfig) -> TeamMatrix:
    """加载覆盖文件，每队按赛季规则建配置（每队只建一次），抽样。写错时抛出 ConfigError。"""
    gm = load_gamemaster(custom_files=config.custom_files)

    def prepare(setups: Sequence[TeamSetup], group: str) -> tuple[MatrixTeam, ...]:
        return tuple(
            MatrixTeam(setup, prepare_team(gm, setup, config.league, config.season), group) for setup in setups
        )

    teams = prepare(config.teams, GROUP_OURS)
    handwritten = prepare(config.opponent_teams, GROUP_HANDWRITTEN)
    sample = None
    if config.sample is not None:
        sample = draw_sample(gm, config.sample, config.league, config.season, config.rules.max_team_size)
    opponents = handwritten + (sample.teams if sample else ())
    return TeamMatrix(config, gm, teams, opponents, sample)


def draw_sample(gm: GameMaster, spec: SampleSpec, league: int, season: SeasonRules, size: int) -> Sample:
    """按模块说明里的规则抽 spec.count 队。候选不够时抛出 ConfigError。"""
    where = "opponent_sample"
    if spec.mega_top and season.max_megas_per_team is not None and season.max_megas_per_team < 1:
        raise ConfigError(f"{where}：赛季规则 {season.name} 不许带 Mega，mega_top 要写 0")
    try:
        pools = tuple(prepare_pool(gm, pool_spec, league, season) for pool_spec in spec.pool_specs())
    except ValueError as e:
        raise ConfigError(f"{where}：{e}") from e
    non_megas = pools[0].members
    megas = pools[1].members if spec.mega_top else ()
    if spec.mega_top and not megas:
        raise ConfigError(f"{where}：{spec.rankings} 排名里没有能用的 Mega（mega_top 写 0 就不带 Mega）")

    rng = random.Random(spec.seed)
    drawn: list[tuple[PoolMember, ...]] = []
    seen: set[frozenset[str]] = set()
    attempts = 0
    while len(drawn) < spec.count:
        attempts += 1
        if attempts > spec.count * _ATTEMPTS_PER_TEAM:
            raise ConfigError(
                f"{where}：试了 {attempts - 1} 次，只抽出 {len(drawn)} 个不同的队伍，不够 {spec.count} 个。"
                "把 top / mega_top 调大，或者把 count 调小"
            )
        team = _draw_team(gm, rng, non_megas, megas, size, where)
        key = frozenset(m.participant.build.species_id for m in team)
        if key in seen:
            continue
        seen.add(key)
        drawn.append(team)

    entries: dict[int, Entry] = {}  # 每只候选只写一次配置（ranked_entry 有时要算 IV）
    teams = []
    for i, team in enumerate(drawn):
        name = spec.team_name(i)
        for member in team:
            if member.ranked.rank not in entries:
                entries[member.ranked.rank] = ranked_entry(gm, member.ranked, league, spec.ivs)
        setup = TeamSetup(name, spec.shields, spec.policy, tuple(entries[m.ranked.rank] for m in team))
        participants = tuple(m.participant for m in team)
        check_prepared_team(gm, name, participants, season)  # 抽样本身已经保证，这里再核对一遍
        teams.append(MatrixTeam(setup, participants, GROUP_SAMPLED, tuple(m.ranked.rank for m in team)))
    return Sample(spec, pools, tuple(teams))


def _draw_team(
    gm: GameMaster,
    rng: random.Random,
    non_megas: Sequence[PoolMember],
    megas: Sequence[PoolMember],
    size: int,
    where: str,
) -> tuple[PoolMember, ...]:
    def dex(member: PoolMember) -> int:
        return gm.get_species(member.participant.build.species_id).dex

    chosen: list[PoolMember] = []
    if megas:
        chosen.append(megas[_random_index(rng, len(megas))])
    used = {dex(m) for m in chosen}
    candidates = list(non_megas)
    _shuffle(rng, candidates)
    for member in candidates:
        if len(chosen) == size:
            break
        if dex(member) not in used:
            chosen.append(member)
            used.add(dex(member))
    if len(chosen) < size:
        raise ConfigError(f"{where}：候选里不同种的宝可梦不够组成一队（{size} 只），把 top 调大")
    _shuffle(rng, chosen)
    return tuple(chosen)


def _random_index(rng: random.Random, n: int) -> int:
    """0 到 n − 1 的随机整数。只用 rng.random()（理由见模块说明）。"""
    return int(rng.random() * n)


def _shuffle(rng: random.Random, items: list) -> None:
    """Fisher–Yates 洗牌，只用 rng.random()。"""
    for i in range(len(items) - 1, 0, -1):
        j = _random_index(rng, i + 1)
        items[i], items[j] = items[j], items[i]


# ---- 对战 ----


def pairing(matrix: TeamMatrix, team: MatrixTeam, opponent: MatrixTeam) -> TeamBattle:
    """我方一队对一队对手（我方是第 0 方），和 3v3 配置文件里写这两队打一场相同。"""
    config = matrix.config
    battle_config = TeamBattleConfig(
        description=config.description,
        custom_files=config.custom_files,
        league=config.league,
        season=config.season,
        rules=config.rules,
        teams=(team.setup, opponent.setup),
    )
    return assemble_team_battle(battle_config, matrix.gm, (team.members, opponent.members))


def run_team_matrix(matrix: TeamMatrix) -> tuple[tuple[BattleResult, ...], ...]:
    """全部对战。results[我方第几队][对手第几队]。对位评估器在全部对战之间共用（结果不变，只是快）。"""
    evaluators: dict[SimplePolicyConfig, MatchupEvaluator] = {}
    return tuple(
        tuple(run_team_battle(pairing(matrix, team, opponent), evaluators) for opponent in matrix.opponents)
        for team in matrix.teams
    )


def find_team(teams: Sequence[MatrixTeam], name: str, what: str) -> MatrixTeam:
    for team in teams:
        if team.name == name:
            return team
    raise ConfigError(f"{what}里没有叫 {name!r} 的队伍（有：{', '.join(t.name for t in teams)}）")


# ---- 统计 ----


def outcome(result: BattleResult) -> str:
    """从我方（第 0 方）看：赢 / 平 / 输。"""
    if result.winner is None:
        return "平"
    return "赢" if result.winner == 0 else "输"


@dataclass(frozen=True)
class Tally:
    """一队对一组对手的统计。"""

    battles: int
    wins: int
    draws: int
    losses: int
    mean_rating: float  # 我方评分的平均
    mean_remaining: tuple[float, float]  # 平均剩余只数：我方、对方


def tally(results: Sequence[BattleResult]) -> Tally:
    n = len(results)
    outcomes = [outcome(r) for r in results]

    def mean(values: list[int]) -> float:
        return sum(values) / n if n else 0.0

    return Tally(
        battles=n,
        wins=outcomes.count("赢"),
        draws=outcomes.count("平"),
        losses=outcomes.count("输"),
        mean_rating=mean([r.ratings[0] for r in results]),
        mean_remaining=(mean([r.remaining[0] for r in results]), mean([r.remaining[1] for r in results])),
    )


def _groups(matrix: TeamMatrix) -> list[tuple[str, list[int]]]:
    """对手分组：(组名, 对手的下标)。两组都有时再加"全部"。"""
    groups = []
    for group in (GROUP_HANDWRITTEN, GROUP_SAMPLED):
        indices = [j for j, o in enumerate(matrix.opponents) if o.group == group]
        if indices:
            groups.append((group, indices))
    if len(groups) > 1:
        groups.append(("全部", list(range(len(matrix.opponents)))))
    return groups


# ---- 报告（Markdown） ----


def format_summary(matrix: TeamMatrix, results: Sequence[Sequence[BattleResult]]) -> str:
    """总表：一行是我方一队对一组对手。"""
    header = ["我方队伍", "对手", "场数", "赢", "平", "输", "平均评分", "平均剩余只数（我方 / 对方）"]
    rows = []
    for team, row in zip(matrix.teams, results):
        for group, indices in _groups(matrix):
            t = tally([row[j] for j in indices])
            rows.append([
                team.name,
                group,
                str(t.battles),
                str(t.wins),
                str(t.draws),
                str(t.losses),
                f"{t.mean_rating:.0f}",
                f"{t.mean_remaining[0]:.2f} / {t.mean_remaining[1]:.2f}",
            ])
    return format_table(header, rows)


def _outcome_cell(result: BattleResult) -> str:
    text = outcome(result)
    if result.timed_out:
        text += "（时间到）"
    return f"**{text}**" if result.winner == 0 else text


def format_team_results(matrix: TeamMatrix, results: Sequence[BattleResult]) -> str:
    """我方一队对每一队对手：一行一场。"""
    header = ["对手队伍", "对手（按出场顺序）", "结果", "评分", "剩余只数", "剩余盾", "回合"]
    rows = []
    for opponent, result in zip(matrix.opponents, results):
        rows.append([
            opponent.name,
            "、".join(opponent.member_names()),
            _outcome_cell(result),
            f"{result.ratings[0]} 对 {result.ratings[1]}",
            f"{result.remaining[0]} 对 {result.remaining[1]}",
            f"{result.shields_left[0]} 对 {result.shields_left[1]}",
            str(result.turns),
        ])
    return format_table(header, rows)


def _format_team_lines(gm: GameMaster, team: MatrixTeam) -> list[str]:
    setup = team.setup
    lines = [f"**{setup.name}**（{setup.shields} 盾）", ""]
    for slot, participant in enumerate(team.members):
        role = "首发" if slot == 0 else "后备"
        lines.append(f"- {role} {format_participant(gm, participant)}")
    lines.append(f"- 策略：{policy_text(setup.policy)}")
    return lines


def _format_sample_section(matrix: TeamMatrix, sample: Sample) -> list[str]:
    spec = sample.spec
    lines = [f"### 随机抽的（{len(sample.teams)} 队）", ""]
    lines.append(f"{spec.describe(matrix.config.league, matrix.config.rules.max_team_size)}。")
    lines.append(f"每队 {spec.shields} 盾；策略：{policy_text(spec.policy)}。")
    for pool in sample.pools:
        if pool.skipped:
            lines += ["", f"{pool.spec.name}里建不了配置、不参加抽样的："]
            lines += format_skipped(pool.skipped)
    lines += ["", "#后面是 PvPoke 排名文件里的名次（这套排名里的所有宝可梦一起排）。", ""]
    size = matrix.config.rules.max_team_size
    header = ["队伍", "首发", *(["后备"] * (size - 1))]
    lines.append(format_table(header, [[t.name, *t.member_names()] for t in sample.teams]))
    for pool in sample.pools:
        lines += ["", f"#### 候选：{pool.spec.name}", ""]
        lines.append("推荐配招来自 PvPoke；CP、等级、IV 按上面的 IV 规则和赛季规则。")
        lines += ["", format_pool_members(matrix.gm, pool)]
    return lines


def format_report(
    matrix: TeamMatrix, results: Sequence[Sequence[BattleResult]], source: str = ""
) -> str:
    """完整报告：设置、我方队伍、总表、我方每一队的结果、对手队伍。"""
    config = matrix.config
    lines: list[str] = []
    if config.description:
        lines += [config.description, ""]
    if source:
        lines.append(f"- 配置文件：`{source}`")
    lines.append(f"- 联盟：{league_name(config.league)}；赛季规则：{config.season.name}")
    changed_rules = format_params(config.rules, PVPOKE_COMPAT)
    lines.append(f"- 机制规则：{'和 PvPoke 默认不同的：' + changed_rules if changed_rules else '与 PvPoke 一致（默认）'}")
    for log in matrix.gm.custom_log:
        lines.append(f"- 覆盖文件：{log}")
    handwritten = sum(1 for o in matrix.opponents if o.group == GROUP_HANDWRITTEN)
    sampled = len(matrix.opponents) - handwritten
    lines.append(
        f"- 对战：我方 {len(matrix.teams)} 队，每一队对 {len(matrix.opponents)} 队对手"
        f"（手写 {handwritten} 队、随机抽 {sampled} 队）各打一场 3v3，我方是第 0 方。"
        "对战是确定的，同一个配置每次结果相同"
    )
    lines.append(
        "- 策略：每一队都是 3v3 策略 TeamPolicy（规则和默认参数见 docs/mechanics.md 13.7），"
        "和默认不同的参数写在各队下面"
    )
    lines.append(
        "- 评分：本项目的口径（docs/mechanics.md 13.2 D1），从我方看。"
        "500 + 500 ×（己方剩余 HP 比例之和 − 对方剩余 HP 比例之和）÷ 每队只数，向下取整；双方加起来 1000"
    )
    lines.append("- 想看某一场的完整过程（换人和开盾的原因、时间线）：`tools/run_team_matrix.py` 加 `--battle 我方队伍 对手队伍`")

    lines += ["", "## 我方队伍", ""]
    for team in matrix.teams:
        lines += _format_team_lines(matrix.gm, team)
        lines.append("")

    lines += ["## 总表", ""]
    lines.append("赢、平、输从我方看；平均评分是我方评分的平均。")
    lines += ["", format_summary(matrix, results), ""]

    for team, row in zip(matrix.teams, results):
        lines += [f"## {team.name} 的每一场", ""]
        lines.append("评分、剩余只数、剩余盾都是\"我方 对 对手\"；我方赢的加粗。")
        lines += ["", format_team_results(matrix, row), ""]

    lines += ["## 对手队伍", ""]
    hand = [o for o in matrix.opponents if o.group == GROUP_HANDWRITTEN]
    if hand:
        lines += [f"### 手写的（{len(hand)} 队）", ""]
        for team in hand:
            lines += _format_team_lines(matrix.gm, team)
            lines.append("")
    if matrix.sample is not None:
        lines += _format_sample_section(matrix, matrix.sample)
    if any(p.outside_movepool for t in (*matrix.teams, *matrix.opponents) for p in t.members):
        lines += ["", "\\* 带了招式池外的招式（假设）。"]
    return "\n".join(lines).rstrip() + "\n"


def format_csv(matrix: TeamMatrix, results: Sequence[Sequence[BattleResult]]) -> str:
    """全部对战，一场一行（CSV，方便另外分析）。result 从我方看：win / draw / loss。"""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([
        "team", "opponent_group", "opponent", "opponent_members", "result", "timed_out",
        "team_rating", "opponent_rating", "team_remaining", "opponent_remaining",
        "team_shields_left", "opponent_shields_left", "turns",
    ])
    codes = {"赢": "win", "平": "draw", "输": "loss"}
    for team, row in zip(matrix.teams, results):
        for opponent, result in zip(matrix.opponents, row):
            writer.writerow([
                team.name,
                opponent.group,
                opponent.name,
                " / ".join(opponent.member_names()),
                codes[outcome(result)],
                int(result.timed_out),
                result.ratings[0],
                result.ratings[1],
                result.remaining[0],
                result.remaining[1],
                result.shields_left[0],
                result.shields_left[1],
                result.turns,
            ])
    return out.getvalue()
