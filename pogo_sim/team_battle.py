"""3v3 对战配置与报告（3v3-e）：两队写在一个 TOML 文件里，打一场，输出 Markdown 报告。

用 tools/run_team_battle.py 运行。例子：experiments/gl_3v3_example.toml。
队伍对队伍（team_matrix.py）也用这里的配置解析（parse_common_settings、parse_team）和建队伍（prepare_team、assemble_team_battle）。
网页界面（web_api.py）发来的配置是 dict，用 parse_team_battle_config 检查，和配置文件走同一套检查。

文件格式：
    description = "说明"                    # 可选
    custom_files = ["data/custom/x.toml"]  # 可选：覆盖文件，路径相对仓库根目录（同 matchups.py）
    league = 1500                          # CP 上限：500 / 1500 / 2500 / 10000（大师联盟）
    season = "pvpoke"                      # 赛季规则预设，见 season.SEASON_PRESETS

    [rules]                                # 可选：机制规则（BattleRules 的字段），默认与 PvPoke 一致。例如
    timeout_result = "more_remaining"      #   时间到、双方都还有宝可梦时怎么判（docs/mechanics.md 9.3）

    [policy]                               # 可选：双方的 3v3 策略参数（TeamPolicyConfig），不写就是默认
    switching = "threshold"
    [policy.moves]                         # 出招、开盾的简单规则参数（SimplePolicyConfig）
    bait_shields = true
    [policy.evaluation]                    # 对位评估时双方用的简单规则参数（SimplePolicyConfig）

    [[team]]                               # 正好两队，第一队是第 0 方
    name = "Team A"                        # 报告里的名字，两队不能同名
    shields = 2                            # 可选，默认 2
    [team.policy]                          # 可选：只改这一队的策略参数，逐项覆盖上面的 [policy]
    switching = "never"
    [[team.member]]                        # 正好 3 只（BattleRules.max_team_size），按出场顺序，第一只是首发
    species = "azumarill"                  # 写法同 matchups.py 的 [[subject]]：可选 label、ivs、level、
    fast = "BUBBLE"                        #   best_buddy、mega_level、outside_movepool
    charged = ["ICE_BEAM", "PLAY_ROUGH"]

队伍检查（建配置时）：只数；同一种宝可梦不能带两只（按图鉴编号，暗影、Mega、地区形态都算同一种）；
Mega 不超过赛季规则的上限（season.check_team）。

双方都用 3v3 策略 TeamPolicy（规则见 docs/mechanics.md 13.7）。对战是确定的：同一个配置每次结果相同。

报告的内容：设置、两队的配置和策略参数、结果、每只的情况、开局对位评分、换人和开盾的原因、带原因的完整时间线。
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.battle_summary import Segment, SegmentSide, battle_segments
from pogo_sim.combatant import make_combatant
from pogo_sim.config import (
    ConfigError,
    Entry,
    Participant,
    check_unknown_keys,
    error_message,
    format_params,
    format_participant,
    format_table,
    load_toml,
    merge_tables,
    parse_entry,
    parse_params,
    prepare_entry,
    resolve_path,
)
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.season import SEASON_PRESETS, SeasonRules, check_team, league_name
from pogo_sim.simple_policy import SimplePolicyConfig
from pogo_sim.team import Team
from pogo_sim.team_policy import TeamPolicy, TeamPolicyConfig
from pogo_sim.timeline import DecisionEvent, FaintEvent, MoveEvent, SwitchEvent, format_timeline

_TOP_LEVEL_KEYS = {"description", "custom_files", "league", "season", "rules", "policy", "team"}
_TEAM_KEYS = {"name", "shields", "policy", "member"}

SWITCH_KINDS = {"switch": "主动换人", "zero_turn": "0 回合换人", "replacement": "倒下后换人"}


# ---- 配置 ----


@dataclass(frozen=True)
class TeamSetup:
    """配置文件里的一队（还没按赛季规则建配置）。"""

    name: str
    shields: int
    policy: TeamPolicyConfig
    members: tuple[Entry, ...]


@dataclass(frozen=True)
class TeamBattleConfig:
    description: str
    custom_files: tuple[Path, ...]
    league: int
    season: SeasonRules
    rules: BattleRules
    teams: tuple[TeamSetup, TeamSetup]


@dataclass(frozen=True)
class CommonSettings:
    """3v3 配置和队伍对队伍配置（team_matrix.py）共用的部分。"""

    description: str
    custom_files: tuple[Path, ...]
    league: int
    season: SeasonRules
    rules: BattleRules
    shared_policy: dict[str, Any]  # 配置里的 [policy] 原样（已检查过）；各队再用自己的 policy 逐项覆盖


def load_team_battle_config(path: Path | str) -> TeamBattleConfig:
    """读取并检查 3v3 配置文件（格式见模块说明）。写错时抛出 ConfigError。"""
    path = Path(path)
    return parse_team_battle_config(load_toml(path), path.name)


def parse_team_battle_config(raw: dict[str, Any], where: str) -> TeamBattleConfig:
    """检查已经读进来的 3v3 配置（和 TOML 文件同样的键，例如网页发来的 JSON）。

    where 是报错信息开头的来源（文件名，或者"网页"）。写错时抛出 ConfigError。
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}：配置要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, _TOP_LEVEL_KEYS, where)
    for key in ("league", "season", "team"):
        if key not in raw:
            raise ConfigError(f"{where}：缺少 {key}")
    settings = parse_common_settings(raw, where)

    teams = raw["team"]
    if not isinstance(teams, list) or len(teams) != 2:
        count = len(teams) if isinstance(teams, list) else "不是 [[team]] 表"
        raise ConfigError(f"{where}：要正好写两队（[[team]]），得到 {count}")
    parsed = tuple(
        parse_team(team, settings.shared_policy, settings.rules, f"{where}：第 {i + 1} 队")
        for i, team in enumerate(teams)
    )
    if parsed[0].name == parsed[1].name:
        raise ConfigError(f"{where}：两队不能同名（{parsed[0].name}）")

    return TeamBattleConfig(
        description=settings.description,
        custom_files=settings.custom_files,
        league=settings.league,
        season=settings.season,
        rules=settings.rules,
        teams=(parsed[0], parsed[1]),
    )


def parse_common_settings(raw: dict[str, Any], where: str) -> CommonSettings:
    """description、custom_files、league、season、[rules]、[policy]。写错时抛出 ConfigError。"""
    for key in ("league", "season"):
        if key not in raw:
            raise ConfigError(f"{where}：缺少 {key}")

    league = raw["league"]
    if not isinstance(league, int) or isinstance(league, bool) or league <= 0:
        raise ConfigError(f"{where}：league 要写正整数（CP 上限），得到 {league!r}")
    season_key = raw["season"]
    if season_key not in SEASON_PRESETS:
        raise ConfigError(f"{where}：不认识的赛季规则 {season_key!r}（可用：{', '.join(SEASON_PRESETS)}）")
    custom_files = raw.get("custom_files", [])
    if not isinstance(custom_files, list) or not all(isinstance(p, str) for p in custom_files):
        raise ConfigError(f"{where}：custom_files 要写字符串列表")

    rules = parse_params(BattleRules, raw.get("rules", {}), where, "规则参数")
    shared_policy = raw.get("policy", {})
    parse_params(TeamPolicyConfig, shared_policy, where, "策略参数")  # 先单独检查一遍，报错时好找

    return CommonSettings(
        description=str(raw.get("description", "")),
        custom_files=tuple(resolve_path(p) for p in custom_files),
        league=league,
        season=SEASON_PRESETS[season_key],
        rules=rules,
        shared_policy=shared_policy,
    )


def parse_team(
    raw: Any, shared_policy: dict[str, Any], rules: BattleRules, where: str, table: str = "team"
) -> TeamSetup:
    """配置里的一队。table 是报错信息里的表名（[[team]]、[[opponent_team]] 等）。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}：要写成 [[{table}]] 表")
    if "name" not in raw:
        raise ConfigError(f"{where}：缺少 name")
    name = raw["name"]
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{where}：name 要写非空的字符串，得到 {name!r}")
    where = f"{where}（{name}）"
    check_unknown_keys(raw, _TEAM_KEYS, where)
    if "member" not in raw:
        raise ConfigError(f"{where}：缺少 member（[[{table}.member]]）")

    shields = raw.get("shields", rules.max_shields)
    if not isinstance(shields, int) or isinstance(shields, bool) or not 0 <= shields <= rules.max_shields:
        raise ConfigError(f"{where}：shields 要写 0 到 {rules.max_shields} 的整数，得到 {shields!r}")

    team_policy = raw.get("policy", {})
    if not isinstance(team_policy, dict):
        raise ConfigError(f"{where}：policy 要写成表（[{table}.policy]）")
    policy = parse_params(TeamPolicyConfig, merge_tables(shared_policy, team_policy), where, "策略参数")

    members = raw["member"]
    size = rules.max_team_size
    if not isinstance(members, list) or len(members) != size:
        count = len(members) if isinstance(members, list) else f"不是 [[{table}.member]] 表"
        raise ConfigError(f"{where}：每队要正好 {size} 只（[[{table}.member]]），得到 {count}")
    entries = tuple(parse_entry(member, f"{where}第 {i + 1} 只") for i, member in enumerate(members))
    return TeamSetup(name, shields, policy, entries)


# ---- 按赛季规则建配置、检查队伍 ----


@dataclass(frozen=True)
class PreparedTeam:
    setup: TeamSetup
    members: tuple[Participant, ...]
    # 时间线和报告里的名字：label（默认是宝可梦名）；两队有同名的，后面加上队名
    names: tuple[str, ...]


@dataclass(frozen=True)
class TeamBattle:
    """准备好的一场 3v3：配置、加载了覆盖文件的 gamemaster、两队。"""

    config: TeamBattleConfig
    gm: GameMaster
    teams: tuple[PreparedTeam, PreparedTeam]


def prepare_team_battle(config: TeamBattleConfig) -> TeamBattle:
    """加载覆盖文件，给每只宝可梦按赛季规则建配置，检查招式和队伍。写错时抛出 ConfigError。"""
    gm = load_gamemaster(custom_files=config.custom_files)
    prepared = [prepare_team(gm, setup, config.league, config.season) for setup in config.teams]
    return assemble_team_battle(config, gm, (prepared[0], prepared[1]))


def assemble_team_battle(
    config: TeamBattleConfig,
    gm: GameMaster,
    members: tuple[tuple[Participant, ...], tuple[Participant, ...]],
) -> TeamBattle:
    """用建好的两队配置（prepare_team 的结果）拼成一场。批量对战时每队只建一次配置（team_matrix.py）。"""
    # 两队都有的名字（例如镜像对局），后面加队名，免得时间线里分不清
    shared = {p.label for p in members[0]} & {p.label for p in members[1]}
    teams = tuple(
        PreparedTeam(
            setup,
            team,
            tuple(f"{p.label} ({setup.name})" if p.label in shared else p.label for p in team),
        )
        for setup, team in zip(config.teams, members)
    )
    return TeamBattle(config, gm, (teams[0], teams[1]))


def prepare_team(gm: GameMaster, setup: TeamSetup, league: int, season: SeasonRules) -> tuple[Participant, ...]:
    """一队按赛季规则建配置，检查招式和队伍规则。写错时抛出 ConfigError。"""
    members = []
    for i, entry in enumerate(setup.members):
        where = f"{setup.name} 第 {i + 1} 只（{entry.label or entry.species_id}）"
        try:
            members.append(prepare_entry(gm, entry, league, season))
        except (KeyError, ValueError) as e:
            raise ConfigError(f"{where}：{error_message(e)}") from e
    check_prepared_team(gm, setup.name, members, season)
    return tuple(members)


def check_prepared_team(gm: GameMaster, name: str, members: Sequence[Participant], season: SeasonRules) -> None:
    """队伍规则（season.check_team：同一种不能带两只、Mega 数）和名字不重复。不符合时抛出 ConfigError。"""
    try:
        check_team(gm, [p.build for p in members], season)
    except ValueError as e:
        raise ConfigError(f"{name}：{e}") from e
    labels = [p.label for p in members]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ConfigError(f"{name} 里有重名的 {', '.join(duplicates)}：给它们写不同的 label")


# ---- 对战 ----


def make_teams(battle: TeamBattle) -> tuple[Team, Team]:
    """建立双方的队伍（新的宝可梦，满 HP、0 能量）。"""
    teams = tuple(
        Team(
            tuple(make_combatant(battle.gm, p.build, side) for p in team.members),
            shields=team.setup.shields,
        )
        for side, team in enumerate(battle.teams)
    )
    return teams[0], teams[1]


def make_policies(
    battle: TeamBattle, evaluators: dict[SimplePolicyConfig, MatchupEvaluator] | None = None
) -> tuple[TeamPolicy, TeamPolicy]:
    """双方的 TeamPolicy。对位评估的配置相同时共用一个评估器（共用缓存，结果不变，只是快）。

    evaluators：按对位评估配置存的评估器，传进来就在多场对战之间共用（team_matrix.py）。
    评估器的缓存键是双方的状态、盾数和规则，不含是哪一场，所以共用不改变结果。
    """
    if evaluators is None:
        evaluators = {}
    policies = []
    for team in battle.teams:
        config = team.setup.policy
        if config.evaluation not in evaluators:
            evaluators[config.evaluation] = MatchupEvaluator(config.evaluation)
        policies.append(TeamPolicy(config, evaluators[config.evaluation]))
    return policies[0], policies[1]


def run_team_battle(
    battle: TeamBattle, evaluators: dict[SimplePolicyConfig, MatchupEvaluator] | None = None
) -> BattleResult:
    return Battle(make_teams(battle), make_policies(battle, evaluators), battle.config.rules).run()


def timeline_names(battle: TeamBattle) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return battle.teams[0].names, battle.teams[1].names


# ---- 开局对位评分 ----


@dataclass(frozen=True)
class OpeningMatchups:
    """开局时一队每一只对另一队每一只的对位评分（满 HP、0 能量，盾数是两队开局的盾数）。"""

    side: int  # 从哪一方看
    ratings: tuple[tuple[int, ...], ...]  # ratings[我方第几只][对方第几只]，四舍五入


def opening_matchups(battle: TeamBattle) -> list[OpeningMatchups]:
    """TeamPolicy 选人、换人时用的就是这种评分。两队对位评估的配置相同时只算第 0 方的（第 1 方约等于 1000 减它）。"""
    sides = [0] if battle.teams[0].setup.policy.evaluation == battle.teams[1].setup.policy.evaluation else [0, 1]
    results = []
    for side in sides:
        mine, theirs = battle.teams[side], battle.teams[1 - side]
        evaluator = MatchupEvaluator(mine.setup.policy.evaluation)
        ratings = tuple(
            tuple(
                evaluator.evaluate(
                    make_combatant(battle.gm, me.build, 0),
                    make_combatant(battle.gm, opponent.build, 1),
                    mine.setup.shields,
                    theirs.setup.shields,
                    battle.config.rules,
                ).rounded
                for opponent in theirs.members
            )
            for me in mine.members
        )
        results.append(OpeningMatchups(side, ratings))
    return results


# ---- 每只的情况 ----


@dataclass(frozen=True)
class MemberSummary:
    """一只宝可梦在这一场里的情况（从事件里统计）。"""

    side: int
    slot: int
    hp: int  # 结束时的 HP
    max_hp: int
    energy: int  # 结束时的能量
    damage_dealt: int  # 造成的伤害（被盾挡下的算 1）
    damage_taken: int
    fast_moves: int  # 用了几次快招
    charged_moves: tuple[str, ...]  # 放的大招，按顺序
    charged_shielded: int  # 挨的大招里，开盾挡下的次数
    charged_unshielded: int  # 挨的大招里，队伍还有盾但没开的次数
    fainted_turn: int | None


def member_summaries(battle: TeamBattle, result: BattleResult) -> list[MemberSummary]:
    """按第 0 方、第 1 方，再按队伍顺序。"""
    dealt: Counter[tuple[int, int]] = Counter()
    taken: Counter[tuple[int, int]] = Counter()
    fast: Counter[tuple[int, int]] = Counter()
    charged: dict[tuple[int, int], list[str]] = {}
    shielded: Counter[tuple[int, int]] = Counter()
    unshielded: Counter[tuple[int, int]] = Counter()
    fainted: dict[tuple[int, int], int] = {}
    for event in result.events:
        if isinstance(event, MoveEvent):
            attacker = (event.actor, event.actor_slot)
            defender = (1 - event.actor, event.target_slot)
            dealt[attacker] += event.damage
            taken[defender] += event.damage
            if event.is_charged:
                charged.setdefault(attacker, []).append(event.move_id)
                if event.shielded:
                    shielded[defender] += 1
                elif event.shield_reason is not None:  # 有盾才会问开不开
                    unshielded[defender] += 1
            else:
                fast[attacker] += 1
        elif isinstance(event, FaintEvent):
            fainted[(event.actor, event.slot)] = event.turn

    last = result.snapshots[-1].sides
    summaries = []
    for side, team in enumerate(battle.teams):
        for slot, participant in enumerate(team.members):
            key = (side, slot)
            max_hp = make_combatant(battle.gm, participant.build, side).stats.hp
            summaries.append(
                MemberSummary(
                    side=side,
                    slot=slot,
                    hp=last[side].member_hp[slot],
                    max_hp=max_hp,
                    energy=last[side].member_energy[slot],
                    damage_dealt=dealt[key],
                    damage_taken=taken[key],
                    fast_moves=fast[key],
                    charged_moves=tuple(charged.get(key, [])),
                    charged_shielded=shielded[key],
                    charged_unshielded=unshielded[key],
                    fainted_turn=fainted.get(key),
                )
            )
    return summaries


def max_hps(battle: TeamBattle) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """两队每只的最大 HP（按队伍顺序）。"""
    hps = tuple(
        tuple(make_combatant(battle.gm, p.build, side).stats.hp for p in team.members)
        for side, team in enumerate(battle.teams)
    )
    return hps[0], hps[1]


# ---- 对位分段（battle_summary.py） ----


def segments(battle: TeamBattle, result: BattleResult) -> list[Segment]:
    return battle_segments(result, max_hps(battle))


def segment_end_text(battle: TeamBattle, result: BattleResult, segment: Segment, last: bool) -> str:
    """这一段是怎么结束的，例如"Azumarill 倒下"、"Team B 0 回合换人"。报告和网页共用。"""
    parts = [f"{battle.teams[side].names[segment.sides[side].slot]} 倒下" for side in segment.fainted]
    parts += [f"{battle.teams[side].setup.name} {SWITCH_KINDS[kind]}" for side, kind in segment.switched]
    if not parts and last:
        parts.append("时间到" if result.timed_out else "对战结束")
    return "；".join(parts)


def charged_use_text(segment_side: SegmentSide) -> str:
    """一段里放的大招，例如"ICE_BEAM 挡下、PLAY_ROUGH 51"（被挡下写"挡下"，否则是伤害）。

    没放满的（只有手动对战里会有）后面写威力，例如"PLAY_ROUGH 30（威力 60%）"。
    """
    return "、".join(
        f"{use.move_id} {'挡下' if use.shielded else use.damage}"
        + (f"（威力 {use.charge:.0%}）" if use.charge < 1 else "")
        for use in segment_side.charged
    )


# ---- 报告（Markdown） ----


def format_outcome(battle: TeamBattle, result: BattleResult) -> str:
    """一行中文结果。"""
    names = [team.setup.name for team in battle.teams]
    if result.winner is None:
        outcome = "平局"
    else:
        outcome = f"{names[result.winner]} 赢"
    if result.timed_out:
        outcome += f"（时间到，判定方式 timeout_result = \"{battle.config.rules.timeout_result}\"）"
    return (
        f"{outcome}。评分 {result.ratings[0]} 对 {result.ratings[1]}；"
        f"剩余 {result.remaining[0]} 只对 {result.remaining[1]} 只；"
        f"剩余盾 {result.shields_left[0]} 对 {result.shields_left[1]}；"
        f"{result.turns} 回合，对战时间 {result.elapsed_ms / 1000:g} 秒（大招每次按 "
        f"{battle.config.rules.charged_move_ms / 1000:g} 秒算）。"
    )


def policy_text(policy: TeamPolicyConfig) -> str:
    """例如"TeamPolicy，默认参数"。"""
    changed = format_params(policy, TeamPolicyConfig())
    return f"TeamPolicy，{'和默认不同的参数：' + changed if changed else '默认参数'}"


def _format_team_section(battle: TeamBattle, side: int, policy_note: str = "") -> list[str]:
    """policy_note：策略那一行前面另加的说明（例如这一方的打法是搜索出来的）。"""
    team = battle.teams[side]
    setup = team.setup
    lines = [f"**{setup.name}**（第 {side} 方，{setup.shields} 盾）", ""]
    for slot, participant in enumerate(team.members):
        role = "首发" if slot == 0 else "后备"
        lines.append(f"- {role} {format_participant(battle.gm, participant)}")
    lines.append(f"- 策略：{policy_note}{policy_text(setup.policy)}")
    return lines


def _format_members(battle: TeamBattle, summaries: Sequence[MemberSummary]) -> str:
    header = ["队伍", "宝可梦", "剩余 HP", "剩余能量", "造成伤害", "受到伤害", "快招", "大招", "挨大招：开盾 / 没开", "倒下"]
    rows = []
    for s in summaries:
        team = battle.teams[s.side]
        counts = Counter(s.charged_moves)
        charged = ", ".join(f"{move} ×{n}" for move, n in counts.items()) or "—"
        rows.append([
            team.setup.name,
            team.names[s.slot],
            f"{s.hp} / {s.max_hp}",
            str(s.energy),
            str(s.damage_dealt),
            str(s.damage_taken),
            str(s.fast_moves),
            charged,
            f"{s.charged_shielded} / {s.charged_unshielded}",
            f"第 {s.fainted_turn} 回合" if s.fainted_turn is not None else "—",
        ])
    return format_table(header, rows)


def _format_opening(battle: TeamBattle, opening: OpeningMatchups) -> str:
    mine, theirs = battle.teams[opening.side], battle.teams[1 - opening.side]
    header = [f"{mine.setup.name} \\ {theirs.setup.name}", *theirs.names]
    rows = [
        [name, *(str(r) for r in row)]
        for name, row in zip(mine.names, opening.ratings)
    ]
    return format_table(header, rows)


def _decision_for(result: BattleResult, switch: SwitchEvent) -> DecisionEvent | None:
    """换人对应的决定（同一回合、同一方、换上同一只）。"""
    found = None
    for event in result.events:
        if (
            isinstance(event, DecisionEvent)
            and event.turn == switch.turn
            and event.actor == switch.actor
            and event.switch_to == switch.to_slot
        ):
            found = event
    return found


@dataclass(frozen=True)
class SwitchRecord:
    """一次换人和策略给的原因（报告的"换人"一节、网页都用）。"""

    turn: int
    side: int
    from_slot: int
    to_slot: int
    kind: str  # "switch" / "zero_turn" / "replacement"，同 SwitchEvent.kind
    reason: str  # 找不到对应的决定时为空字符串


def switch_records(result: BattleResult) -> list[SwitchRecord]:
    records = []
    for event in result.events:
        if isinstance(event, SwitchEvent):
            decision = _decision_for(result, event)
            records.append(SwitchRecord(
                event.turn, event.actor, event.from_slot, event.to_slot, event.kind,
                decision.reason if decision else "",
            ))
    return records


@dataclass(frozen=True)
class ChargedRecord:
    """一个大招的结果和开不开盾的原因（报告的"大招和开盾"一节、网页都用）。"""

    turn: int
    side: int  # 出招的一方
    attacker_slot: int
    move_id: str
    target_slot: int  # 挨打的是对方的第几只
    damage: int  # 被挡下时为 1
    shielded: bool
    hp_after: int  # 挨打那只剩下的 HP
    shield_reason: str | None  # 守方没有盾时为 None


def charged_records(result: BattleResult) -> list[ChargedRecord]:
    return [
        ChargedRecord(
            event.turn, event.actor, event.actor_slot, event.move_id, event.target_slot,
            event.damage, event.shielded, event.defender_hp_after, event.shield_reason,
        )
        for event in result.events
        if isinstance(event, MoveEvent) and event.is_charged
    ]


def _escape(text: str) -> str:
    """表格格子里的 | 要转义。"""
    return text.replace("|", "\\|")


def _format_switches(battle: TeamBattle, result: BattleResult) -> str:
    rows = []
    for record in switch_records(result):
        team = battle.teams[record.side]
        rows.append([
            str(record.turn),
            team.setup.name,
            f"{team.names[record.from_slot]} → {team.names[record.to_slot]}",
            SWITCH_KINDS[record.kind],
            _escape(record.reason),
        ])
    if not rows:
        return "没有换人。"
    return format_table(["回合", "队伍", "换人", "类型", "原因"], rows)


def _format_charged(battle: TeamBattle, result: BattleResult) -> str:
    rows = []
    for record in charged_records(result):
        attacker = battle.teams[record.side]
        defender = battle.teams[1 - record.side]
        if record.shielded:
            outcome = "开盾挡下"
        else:
            outcome = f"{record.damage} 伤害，剩 HP {record.hp_after}"
        rows.append([
            str(record.turn),
            attacker.names[record.attacker_slot],
            record.move_id,
            defender.names[record.target_slot],
            outcome,
            _escape(record.shield_reason) if record.shield_reason is not None else "没有盾",
        ])
    if not rows:
        return "没有放大招。"
    return format_table(["回合", "出招", "大招", "挨打", "结果", "开不开盾的原因"], rows)


def _segment_cell(name: str, side: SegmentSide) -> str:
    parts = [
        f"{name}：HP {side.hp_start} → {side.hp_end}，能量 {side.energy_start} → {side.energy_end}",
        f"快招 {side.fast_moves} 次",
    ]
    if side.charged:
        parts.append(f"大招 {charged_use_text(side)}")
    if side.shields_used:
        parts.append(f"开盾 {side.shields_used} 次")
    return "；".join(parts)


def _format_segments(battle: TeamBattle, result: BattleResult) -> str:
    all_segments = segments(battle, result)
    rows = []
    for i, segment in enumerate(all_segments):
        turns = f"{segment.start_turn}–{segment.end_turn}" if segment.end_turn != segment.start_turn else str(segment.start_turn)
        rows.append([
            turns,
            *(_segment_cell(battle.teams[side].names[segment.sides[side].slot], segment.sides[side]) for side in (0, 1)),
            segment_end_text(battle, result, segment, last=i == len(all_segments) - 1),
        ])
    header = ["回合", battle.teams[0].setup.name, battle.teams[1].setup.name, "怎么结束"]
    return format_table(header, rows)


def format_team_battle_report(
    battle: TeamBattle,
    result: BattleResult,
    source: str = "",
    include_timeline: bool = True,
) -> str:
    """完整报告（Markdown）。"""
    lines = format_settings(
        battle,
        source,
        "双方都是 3v3 策略 TeamPolicy（规则和默认参数见 docs/mechanics.md 13.7）。"
        "出招照简单规则策略；倒下后换上对位评分最高的；当前对位不好就主动换人；不在必输的对位上开盾",
    )
    lines += format_teams(battle)
    lines += ["", "## 结果", "", format_outcome(battle, result), ""]
    lines += format_battle_details(battle, result, include_timeline)
    return "\n".join(lines).rstrip() + "\n"


def format_settings(battle: TeamBattle, source: str, policy_line: str) -> list[str]:
    """报告开头的设置：说明、配置文件、联盟和赛季规则、机制规则、覆盖文件、策略、评分口径。"""
    config = battle.config
    lines: list[str] = []
    if config.description:
        lines += [config.description, ""]
    if source:
        lines.append(f"- 配置文件：`{source}`")
    lines.append(f"- 联盟：{league_name(config.league)}；赛季规则：{config.season.name}")
    changed_rules = format_params(config.rules, PVPOKE_COMPAT)
    lines.append(f"- 机制规则：{'和 PvPoke 默认不同的：' + changed_rules if changed_rules else '与 PvPoke 一致（默认）'}")
    for log in battle.gm.custom_log:
        lines.append(f"- 覆盖文件：{log}")
    lines.append(f"- 策略：{policy_line}")
    lines.append(
        "- 评分：本项目的口径（docs/mechanics.md 13.2 D1），"
        "500 + 500 ×（己方剩余 HP 比例之和 − 对方剩余 HP 比例之和）÷ 每队只数，向下取整。双方加起来 1000"
    )
    return lines


def format_teams(battle: TeamBattle, policy_notes: dict[int, str] | None = None) -> list[str]:
    """"## 队伍"一节：两队的配置和策略，队伍检查。policy_notes：某一方策略那一行前面另加的说明。"""
    notes = policy_notes or {}
    lines = ["", "## 队伍", ""]
    for side in (0, 1):
        lines += _format_team_section(battle, side, notes.get(side, ""))
        lines.append("")
    config = battle.config
    size = config.rules.max_team_size
    mega_limit = config.season.max_megas_per_team
    mega_text = f"Mega 不超过 {mega_limit} 只" if mega_limit is not None else "Mega 不限"
    lines.append(f"队伍检查通过：每队 {size} 只；没有同一种宝可梦（按图鉴编号）；{mega_text}。")
    return lines


def format_battle_details(battle: TeamBattle, result: BattleResult, include_timeline: bool) -> list[str]:
    """一场的细节：每只的情况、开局对位评分、换人、大招和开盾、时间线。"""
    lines = ["## 每只的情况", ""]
    lines.append(
        "挨大招：被大招打中时开盾挡下的次数 / 队伍还有盾但没开的次数。被盾挡下的大招算 1 点伤害。"
    )
    lines += ["", _format_members(battle, member_summaries(battle, result)), ""]

    lines += ["## 开局对位评分", ""]
    lines.append(
        "TeamPolicy 选人、换人看的就是这种评分：行上那只对列上那只打 1v1，双方满 HP、0 能量，"
        "盾数从 0 到两队开局的盾数，按 [4, 4, 1] 加权平均（docs/mechanics.md 13.7）。500 是平手。"
    )
    openings = opening_matchups(battle)
    if len(openings) == 1:
        lines.append(f"从 {battle.teams[0].setup.name} 一方看；{battle.teams[1].setup.name} 一方约等于 1000 减它。")
    for opening in openings:
        lines += ["", _format_opening(battle, opening)]
    lines.append("")

    lines += ["## 对位分段", ""]
    lines.append(
        "在场的两只不变的一段时间算一段，任一方换人就开始新的一段（docs/mechanics.md 14.4）。"
        "HP 和能量是这一段开始之前 → 最后一回合结束时；大招后面是伤害，\"挡下\"是被对方开盾挡下；"
        "开盾是挡下对方大招的次数。"
    )
    lines += ["", _format_segments(battle, result), ""]

    lines += ["## 换人", "", _format_switches(battle, result), ""]
    lines += ["## 大招和开盾", "", _format_charged(battle, result), ""]

    if include_timeline:
        lines += ["## 时间线", ""]
        lines.append("每回合的决定（decides …，括号里是原因）和结算。T 后面是回合数。")
        lines += ["", "```text", format_timeline(result.events, timeline_names(battle), show_decisions=True), "```"]
    return lines
