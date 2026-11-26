"""对战配置：一组测试对象对一组对手，每一对打 0–2 盾对 0–2 盾的九宫格。

配置写在 TOML 文件里（例子：experiments/mega_zygarde_ml.toml）。换配招、对手、联盟、赛季规则、
策略参数都只改配置文件，不改代码。用 tools/run_matchups.py 运行。

文件格式：
    description = "说明"                               # 可选
    custom_files = ["data/custom/mega_zygarde.toml"]   # 可选：覆盖文件，路径相对仓库根目录。
                                                       # 赛季的招式平衡调整也写成覆盖文件（patch_moves）放这里
    league = 10000                                     # CP 上限：500 / 1500 / 2500 / 10000（大师联盟）
    season = "pvpoke"                                  # 赛季规则预设，见 season.SEASON_PRESETS

    [policy]                                           # 可选：简单规则策略的参数（SimplePolicyConfig），双方相同
    bait_shields = false

    [[subject]]                                        # 测试对象（九宫格的行），可以有多个
    label = "Dragon Tail"                              # 可选：报告里的名字，默认是宝可梦名；同一组里不能重名
    species = "zygarde_mega"
    fast = "DRAGON_TAIL"
    charged = ["CRUNCH", "BULLDOZE", "NIHIL_LIGHT"]
    # 以下可选：
    # ivs = [15, 15, 15]          攻 / 防 / HP；不写时用 IV 排名第 1
    # level = 50                  不写时用上限内 CP 合法的最高等级
    # best_buddy = true
    # mega_level = 4
    # outside_movepool = true     允许招式池外的招式（见 moveset.py），报告里会标出来

    [[opponent]]                                       # 对手，写法同上
    ...

    [[opponent_pool]]                                  # 可选：PvPoke 排名里的环境前 N 当对手（rankings.py）
    name = "非 Mega 前 50"                             # 可选：报告里的名字
    rankings = "mega"                                  # PvPoke 的排名："all"（不含 Mega）/ "mega"（Mega 版）
    kind = "non_mega"                                  # "mega" / "non_mega"：Mega 和非 Mega 分开取
    top = 50                                           # 这一类的前几只
    ivs = "rank1"                                      # 可选："rank1"（默认）/ "pvpoke_default"

[[opponent]] 和 [[opponent_pool]] 至少写一种。环境前 N 的对手用宝可梦名当名字，不能和手写的对手重名。

九宫格里的评分都是从测试对象一方看的 PvPoke 对战评分（battle.battle_rating），大于 500 算赢。
手写的对手每一对列一个九宫格；环境前 N 每个测试对象列一张表，一行是一个对手的九宫格。

一只宝可梦的写法、参数表的检查、报告里的一行说明和 3v3 配置（team_battle.py）共用，在 config.py。
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.combatant import make_combatant
from pogo_sim.config import (  # 共用部分；REPO_ROOT、Entry、Participant 也从这里导入
    REPO_ROOT,
    ConfigError,
    Entry,
    Participant,
    check_unknown_keys,
    error_message,
    format_participant,
    format_table,
    load_toml,
    marked,
    parse_entry,
    parse_params,
    prepare_entry,
    resolve_path,
)
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.rankings import (
    Pool,
    PoolBuilder,
    PoolSpec,
    format_pool_members,
    format_skipped,
    parse_pool_spec,
    prepare_pool,
)
from pogo_sim.season import SEASON_PRESETS, SeasonRules, league_name
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team

SHIELD_COUNTS: tuple[int, ...] = (0, 1, 2)
WIN_RATING = 500  # 评分大于 500 算赢（一方倒下时，赢家的评分一定大于 500，见 battle.battle_rating）

_TOP_LEVEL_KEYS = {
    "description", "custom_files", "league", "season", "policy", "subject", "opponent", "opponent_pool",
}
_GROUP_NAMES = {"subject": "测试对象", "opponent": "对手"}


# 配置写错时的异常（和 3v3 配置共用，见 config.ConfigError）
MatchupConfigError = ConfigError


# ---- 配置 ----


@dataclass(frozen=True)
class MatchupConfig:
    description: str
    custom_files: tuple[Path, ...]
    league: int
    season: SeasonRules
    policy: SimplePolicyConfig
    subjects: tuple[Entry, ...]
    opponents: tuple[Entry, ...]  # 手写的对手，可以没有
    opponent_pools: tuple[PoolSpec, ...] = ()  # 环境前 N，可以没有


def load_matchup_config(path: Path | str) -> MatchupConfig:
    """读取并检查对战配置文件（格式见模块说明）。写错时抛出 MatchupConfigError。"""
    path = Path(path)
    return parse_matchup_config(load_toml(path), path.name)


def parse_matchup_config(raw: dict[str, Any], where: str) -> MatchupConfig:
    """检查已经读进来的配置（和配置文件同样的键）。where 是报错信息的开头（文件名，网页是"网页"）。

    网页发来的配置也走这里（web_api.py），所以检查和命令行完全相同。
    """
    if not isinstance(raw, dict):
        raise MatchupConfigError(f"{where}：配置要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, _TOP_LEVEL_KEYS, where)
    for key in ("league", "season", "subject"):
        if key not in raw:
            raise MatchupConfigError(f"{where}：缺少 {key}")
    if "opponent" not in raw and "opponent_pool" not in raw:
        raise MatchupConfigError(f"{where}：缺少对手（[[opponent]] 或 [[opponent_pool]]）")

    league = raw["league"]
    if not isinstance(league, int) or isinstance(league, bool) or league <= 0:
        raise MatchupConfigError(f"{where}：league 要写正整数（CP 上限），得到 {league!r}")
    season_key = raw["season"]
    if season_key not in SEASON_PRESETS:
        raise MatchupConfigError(
            f"{where}：不认识的赛季规则 {season_key!r}（可用：{', '.join(SEASON_PRESETS)}）"
        )

    custom_files = raw.get("custom_files", [])
    if not isinstance(custom_files, list) or not all(isinstance(p, str) for p in custom_files):
        raise MatchupConfigError(f"{where}：custom_files 要写字符串列表")

    return MatchupConfig(
        description=str(raw.get("description", "")),
        custom_files=tuple(resolve_path(p) for p in custom_files),
        league=league,
        season=SEASON_PRESETS[season_key],
        policy=parse_params(SimplePolicyConfig, raw.get("policy", {}), where, "策略参数"),
        subjects=_parse_group(raw["subject"], f"{where}：subject"),
        opponents=_parse_group(raw["opponent"], f"{where}：opponent") if "opponent" in raw else (),
        opponent_pools=_parse_pools(raw["opponent_pool"], f"{where}：opponent_pool") if "opponent_pool" in raw else (),
    )


def _parse_group(raw: Any, where: str) -> tuple[Entry, ...]:
    if not isinstance(raw, list) or not raw:
        raise MatchupConfigError(f"{where}：至少要写一个（[[...]] 表）")
    return tuple(parse_entry(item, f"{where} 第 {i + 1} 项") for i, item in enumerate(raw))


def _parse_pools(raw: Any, where: str) -> tuple[PoolSpec, ...]:
    if not isinstance(raw, list) or not raw:
        raise MatchupConfigError(f"{where}：要写成 [[opponent_pool]] 表，至少一个")
    pools = tuple(parse_pool_spec(item, f"{where} 第 {i + 1} 项") for i, item in enumerate(raw))
    names = [pool.name for pool in pools]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise MatchupConfigError(f"{where}：name 重复：{', '.join(duplicates)}")
    return pools


# ---- 按赛季规则建配置 ----


@dataclass(frozen=True)
class Matchups:
    """准备好的一组对战：配置、加载了覆盖文件的 gamemaster、双方的配置。"""

    config: MatchupConfig
    gm: GameMaster
    subjects: tuple[Participant, ...]
    opponents: tuple[Participant, ...]  # 手写的对手
    pools: tuple[Pool, ...] = ()  # 环境前 N


def prepare_matchups(config: MatchupConfig, build_pool: PoolBuilder = prepare_pool) -> Matchups:
    """加载覆盖文件，给每只宝可梦按赛季规则建配置，并检查招式。环境前 N 里建不了配置的跳过（报告里写明）。

    build_pool 是建一组环境前 N 的函数，默认 rankings.prepare_pool。网页换成带缓存的同一个函数
    （web_api.py：建环境前 N 比打九宫格慢得多，改测试对象时不用重建）。
    """
    gm = load_gamemaster(custom_files=config.custom_files)
    subjects = _prepare_group(gm, config, config.subjects, "subject")
    opponents = _prepare_group(gm, config, config.opponents, "opponent")
    pools = []
    for spec in config.opponent_pools:
        try:
            pool = build_pool(gm, spec, config.league, config.season)
        except ValueError as e:
            raise MatchupConfigError(f"环境前 N（{spec.name}）：{error_message(e)}") from e
        clashes = sorted({p.label for p in opponents} & {p.label for p in pool.participants})
        if clashes:
            raise MatchupConfigError(
                f"手写的对手和环境前 N（{spec.name}）里有重名的 {', '.join(clashes)}：给手写的那只写别的 label"
            )
        pools.append(pool)
    return Matchups(
        config=config,
        gm=gm,
        subjects=subjects,
        opponents=opponents,
        pools=tuple(pools),
    )


def _prepare_group(
    gm: GameMaster, config: MatchupConfig, entries: Sequence[Entry], group: str
) -> tuple[Participant, ...]:
    participants = []
    for i, entry in enumerate(entries):
        where = f"{_GROUP_NAMES[group]}第 {i + 1} 项（{entry.label or entry.species_id}）"
        try:
            participants.append(prepare_entry(gm, entry, config.league, config.season))
        except (KeyError, ValueError) as e:
            raise MatchupConfigError(f"{where}：{error_message(e)}") from e

    labels = [p.label for p in participants]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise MatchupConfigError(
            f"{_GROUP_NAMES[group]}里有重名的 {', '.join(duplicates)}：同一种宝可梦写了几套配招时，给每套写 label"
        )
    return tuple(participants)


# ---- 对战和九宫格 ----


@dataclass(frozen=True)
class ShieldGrid:
    """一对宝可梦在 0–2 盾对 0–2 盾下的评分，从测试对象一方看。"""

    subject: str
    opponent: str
    # ratings[测试对象的盾数][对手的盾数]
    ratings: tuple[tuple[int, ...], ...]

    def all_ratings(self) -> list[int]:
        return [r for row in self.ratings for r in row]

    @property
    def wins(self) -> int:
        return sum(1 for r in self.all_ratings() if r > WIN_RATING)

    @property
    def average(self) -> float:
        ratings = self.all_ratings()
        return sum(ratings) / len(ratings)


def make_sides(
    matchups: Matchups,
    subject: Participant,
    opponent: Participant,
    subject_shields: int,
    opponent_shields: int,
) -> tuple[Team, Team]:
    """建立一场 1v1 的双方（每队一只）：测试对象是第 0 方，对手是第 1 方。"""
    gm = matchups.gm
    return (
        Team((make_combatant(gm, subject.build, 0),), shields=subject_shields),
        Team((make_combatant(gm, opponent.build, 1),), shields=opponent_shields),
    )


def fight(matchups: Matchups, sides: tuple[Team, Team]) -> BattleResult:
    """双方都用配置里的简单规则策略打一场。"""
    policy = matchups.config.policy
    return Battle(sides, (SimplePolicy(policy), SimplePolicy(policy))).run()


def battle_names(subject: Participant, opponent: Participant) -> tuple[str, str]:
    """一场里双方的名字。同名时（镜像对局）后面加上"（测试对象）""（对手）"，免得时间线里分不清。"""
    if subject.label != opponent.label:
        return subject.label, opponent.label
    return f"{subject.label}（测试对象）", f"{opponent.label}（对手）"


def format_outcome(names: tuple[str, str], result: BattleResult) -> str:
    """一场 1v1 的一行中文结果（网页上看一场时用），例如"Azumarill 赢。评分 623 对 377；剩余 HP 45 对 0；……"。"""
    outcome = "平局" if result.winner is None else f"{names[result.winner]} 赢"
    if result.timed_out:
        outcome += "（时间到）"
    last = result.snapshots[-1].sides if result.snapshots else None
    hp = f"剩余 HP {last[0].hp} 对 {last[1].hp}；" if last is not None else ""
    return (
        f"{outcome}。评分 {result.ratings[0]} 对 {result.ratings[1]}；{hp}"
        f"{result.turns} 回合，对战时间 {result.elapsed_ms / 1000:g} 秒。"
    )


def shield_grid(matchups: Matchups, subject: Participant, opponent: Participant) -> ShieldGrid:
    ratings = tuple(
        tuple(
            fight(matchups, make_sides(matchups, subject, opponent, mine, theirs)).ratings[0]
            for theirs in SHIELD_COUNTS
        )
        for mine in SHIELD_COUNTS
    )
    return ShieldGrid(subject.label, opponent.label, ratings)


def run_all(matchups: Matchups) -> list[ShieldGrid]:
    """手写对手的全部九宫格：先按测试对象，再按对手的顺序。"""
    return [
        shield_grid(matchups, subject, opponent)
        for subject in matchups.subjects
        for opponent in matchups.opponents
    ]


@dataclass(frozen=True)
class PoolGrids:
    """一组环境前 N 的全部九宫格。"""

    pool: Pool
    # by_subject[第几个测试对象][第几个对手]，对手按名次
    by_subject: tuple[tuple[ShieldGrid, ...], ...]


def run_pools(matchups: Matchups) -> list[PoolGrids]:
    """每组环境前 N：每个测试对象对其中每一只打九宫格。"""
    return [
        PoolGrids(
            pool,
            tuple(
                tuple(shield_grid(matchups, subject, opponent) for opponent in pool.participants)
                for subject in matchups.subjects
            ),
        )
        for pool in matchups.pools
    ]


def find_participant(group: Sequence[Participant], label: str) -> Participant:
    for participant in group:
        if participant.label == label:
            return participant
    raise KeyError(f"找不到 {label!r}（可用：{', '.join(p.label for p in group)}）")


def find_opponent(matchups: Matchups, label: str) -> Participant:
    """按名字找对手：手写的和环境前 N 里的都找。几组环境前 N 里都有、配置又不同时报错。"""
    group = [*matchups.opponents, *(p for pool in matchups.pools for p in pool.participants)]
    found = find_participant(group, label)
    if any(p.label == label and p.build != found.build for p in group):
        raise KeyError(f"{label!r} 在几组环境前 N 里都有，配置不同（排名或 IV 规则不同），分不清是哪一只")
    return found


# ---- 报告（Markdown） ----


def format_summary(matchups: Matchups, grids: Sequence[ShieldGrid]) -> str:
    """总表：行是测试对象，列是对手，每格是九宫格里赢了几场和平均评分。"""
    by_pair = {(g.subject, g.opponent): g for g in grids}
    header = ["测试对象 \\ 对手", *(marked(o) for o in matchups.opponents)]
    rows = []
    for subject in matchups.subjects:
        cells = []
        for opponent in matchups.opponents:
            grid = by_pair[(subject.label, opponent.label)]
            cells.append(f"{grid.wins}/9 胜，平均 {grid.average:.0f}")
        rows.append([marked(subject), *cells])
    return format_table(header, rows)


def format_grid(grid: ShieldGrid) -> str:
    """一个九宫格：行是测试对象的盾数，列是对手的盾数。"""
    header = [f"{grid.subject} 对 {grid.opponent}", *(f"对手 {s} 盾" for s in SHIELD_COUNTS)]
    rows = [
        [f"自己 {mine} 盾", *(str(r) for r in grid.ratings[mine])]
        for mine in SHIELD_COUNTS
    ]
    return format_table(header, rows)


def _shield_header(mine: int, theirs: int) -> str:
    return f"{mine} 对 {theirs}"


def _rating_cell(rating: int) -> str:
    """赢的加粗。"""
    return f"**{rating}**" if rating > WIN_RATING else str(rating)


@dataclass(frozen=True)
class PoolSummary:
    """一个测试对象对一组环境前 N 的总计（报告的总表和网页共用）。"""

    opponents: int  # 对手只数
    same_shield_wins: tuple[int, ...]  # 双方同样 0 / 1 / 2 盾时赢了几只
    wins: int  # 九种盾数一共赢了几格（满分 9 × 对手只数）
    average: float  # 全部评分的平均


def pool_summary(grids: Sequence[ShieldGrid]) -> PoolSummary:
    n = len(grids)
    return PoolSummary(
        opponents=n,
        same_shield_wins=tuple(sum(1 for g in grids if g.ratings[s][s] > WIN_RATING) for s in SHIELD_COUNTS),
        wins=sum(g.wins for g in grids),
        average=sum(g.average for g in grids) / n if n else 0.0,
    )


def format_pool_summary(matchups: Matchups, pool_grids: PoolGrids) -> str:
    """环境前 N 的总表：行是测试对象；双方同样盾数时赢了几只，九种盾数一共赢了几格，平均评分。"""
    header = ["测试对象", *(f"{s} 对 {s} 盾" for s in SHIELD_COUNTS), "九种盾数", "平均评分"]
    rows = []
    for subject, grids in zip(matchups.subjects, pool_grids.by_subject):
        summary = pool_summary(grids)
        n = summary.opponents
        same = [f"赢 {wins} / {n}" for wins in summary.same_shield_wins]
        rows.append([marked(subject), *same, f"赢 {summary.wins} / {9 * n}", f"{summary.average:.0f}"])
    return format_table(header, rows)


def format_pool_table(pool_grids: PoolGrids, subject_index: int) -> str:
    """一个测试对象对环境前 N：一行是一个对手的九宫格（列是"自己的盾数 对 对手的盾数"），赢的加粗。"""
    header = [
        "名次",
        "对手",
        *(_shield_header(mine, theirs) for mine in SHIELD_COUNTS for theirs in SHIELD_COUNTS),
        "赢",
        "平均",
    ]
    rows = []
    for member, grid in zip(pool_grids.pool.members, pool_grids.by_subject[subject_index]):
        rows.append([
            str(member.ranked.rank),
            marked(member.participant),
            *(_rating_cell(r) for r in grid.all_ratings()),
            f"{grid.wins}/9",
            f"{grid.average:.0f}",
        ])
    return format_table(header, rows)


def _format_pool_section(matchups: Matchups, pool_grids: PoolGrids) -> list[str]:
    pool = pool_grids.pool
    lines = [f"## 环境前 N：{pool.spec.name}", ""]
    lines.append(
        f"{pool.spec.describe(pool.league)}。名次是 PvPoke 排名文件里的名次"
        f"（{pool.spec.rankings} 排名里的所有宝可梦一起排），推荐配招也来自 PvPoke。"
    )
    if pool.skipped:
        lines += ["", f"前 {pool.spec.top} 只里建不了配置、跳过的："]
        lines += format_skipped(pool.skipped)
    lines += ["", "### 对手", "", format_pool_members(matchups.gm, pool), ""]
    lines += ["### 总表", ""]
    lines.append(
        f"双方同样盾数时赢了几只（评分大于 {WIN_RATING}）；九种盾数（0–2 盾对 0–2 盾）一共赢了几格；全部评分的平均。"
    )
    lines += ["", format_pool_summary(matchups, pool_grids), ""]
    for i, subject in enumerate(matchups.subjects):
        lines += [f"### {marked(subject)}", ""]
        lines.append(
            f"一行是对一个对手的九宫格，列名是\"自己的盾数 对 对手的盾数\"；加粗的是赢的（评分大于 {WIN_RATING}）。"
        )
        lines += ["", format_pool_table(pool_grids, i), ""]
    return lines


def format_report(
    matchups: Matchups,
    grids: Sequence[ShieldGrid],
    source: str = "",
    pool_grids: Sequence[PoolGrids] = (),
) -> str:
    """完整报告：设置、双方配置、手写对手的总表和九宫格、每组环境前 N 的表。"""
    config = matchups.config
    lines = []
    if config.description:
        lines += [config.description, ""]
    if source:
        lines.append(f"- 配置文件：`{source}`")
    lines.append(f"- 联盟：{league_name(config.league)}；赛季规则：{config.season.name}")
    lines.append(f"- 策略：双方都是简单规则策略，参数 {config.policy}")
    lines.append(
        "- 评分：PvPoke 的对战评分，从测试对象一方看。"
        "500 × 对手损失的 HP 比例 + 500 × 自己剩余的 HP 比例，向下取整；大于 500 算赢"
    )
    for log in matchups.gm.custom_log:
        lines.append(f"- 覆盖文件：{log}")
    lines += ["", "测试对象：", ""]
    lines += [f"- {format_participant(matchups.gm, p)}" for p in matchups.subjects]
    if matchups.opponents:
        lines += ["", "对手：", ""]
        lines += [f"- {format_participant(matchups.gm, p)}" for p in matchups.opponents]
    if matchups.pools:
        lines += ["", "环境前 N（每组的对手列在各自的一节里）：", ""]
        lines += [f"- {pool.spec.name}：{pool.spec.describe(pool.league)}" for pool in matchups.pools]
    if any(p.outside_movepool for p in (*matchups.subjects, *matchups.opponents)):
        lines += ["", "\\* 带了招式池外的招式（假设）。"]
    if matchups.opponents:
        lines += ["", "## 总表", "", "每格是 0–2 盾对 0–2 盾九场里赢了几场，以及九场的平均评分。", ""]
        lines.append(format_summary(matchups, grids))
        lines += ["", "## 九宫格", ""]
        for grid in grids:
            lines += [format_grid(grid), ""]
    if pool_grids:
        lines.append("")
    for pg in pool_grids:
        lines += _format_pool_section(matchups, pg)
    return "\n".join(lines).rstrip() + "\n"


def format_csv(matchups: Matchups, grids: Sequence[ShieldGrid], pool_grids: Sequence[PoolGrids] = ()) -> str:
    """全部评分，一场一行（CSV，方便另外分析）。group 是"手写"或环境前 N 的名字；rank 只有环境前 N 有。"""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["group", "rank", "subject", "opponent", "subject_shields", "opponent_shields", "rating"])

    def write(group: str, rank: str, grid: ShieldGrid) -> None:
        for mine in SHIELD_COUNTS:
            for theirs in SHIELD_COUNTS:
                writer.writerow([group, rank, grid.subject, grid.opponent, mine, theirs, grid.ratings[mine][theirs]])

    for grid in grids:
        write("手写", "", grid)
    for pg in pool_grids:
        for subject_grids in pg.by_subject:
            for member, grid in zip(pg.pool.members, subject_grids):
                write(pg.pool.spec.name, str(member.ranked.rank), grid)
    return out.getvalue()
