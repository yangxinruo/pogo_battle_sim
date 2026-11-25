"""网页界面的接口（第 4 步，4a）：收 dict、回 dict，结果都能直接转成 JSON。

网页只负责填表和显示，这里只做转换：把网页发来的配置交给引擎，再把结果整理成网页好显示的结构。
规则、检查和计算都在引擎里（team_battle.py、config.py 等），这里不重复。
tools/run_web.py 把这些函数转发成 HTTP 接口。

- options()：联盟、赛季规则、覆盖文件、策略的可选值，以及例子配置
- species_catalog(custom_files)：全部宝可梦（名字、属性、招式池）和招式
- build_member(raw)：一只宝可梦按赛季规则建配置（CP、等级、IV、说明）
- team_battle(raw)：打一场 3v3，返回结果、每只的情况、换人和开盾、逐回合时间线、Markdown 报告

网页发来的配置和 3v3 配置文件（team_battle.py 开头）写法一样、键也一样，只有一处不同：
覆盖文件只能从 data/custom/ 里选，写文件名（例如 "mega_froslass.toml"），不能写任意路径。
写错时抛出 ConfigError，信息和配置文件写错时一样，开头是"网页"。
"""

from dataclasses import asdict
from typing import Any, get_args, get_type_hints

from pogo_sim.battle import BattleResult
from pogo_sim.combatant import make_combatant
from pogo_sim.config import (
    REPO_ROOT,
    ConfigError,
    Participant,
    check_unknown_keys,
    error_message,
    load_toml,
    parse_entry,
    prepare_entry,
)
from pogo_sim.gamemaster import GameMaster, Move, load_gamemaster
from pogo_sim.rankings import load_rankings
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.season import LEAGUE_NAMES, SEASON_PRESETS, league_name
from pogo_sim.team_battle import (
    SWITCH_KINDS,
    TeamBattle,
    charged_records,
    format_outcome,
    format_team_battle_report,
    member_summaries,
    opening_matchups,
    parse_common_settings,
    parse_team_battle_config,
    policy_text,
    prepare_team_battle,
    run_team_battle,
    switch_records,
    timeline_names,
)
from pogo_sim.team_policy import TeamPolicyConfig
from pogo_sim.timeline import (
    CancelledEvent,
    DecisionEvent,
    Event,
    FaintEvent,
    MoveEvent,
    Names,
    SwitchEvent,
    describe_event,
    event_actor,
)

WHERE = "网页"  # 报错信息的开头（配置文件是文件名）
CUSTOM_DIR = REPO_ROOT / "data" / "custom"
EXAMPLE_CONFIG = REPO_ROOT / "experiments" / "gl_3v3_example.toml"

# TeamPolicyConfig.switching 的取值在网页上怎么说
SWITCHING_NAMES = {"threshold": "按阈值主动换人（默认）", "never": "不主动换人"}

_EVENT_TYPES = {
    DecisionEvent: "decision",
    MoveEvent: "move",
    CancelledEvent: "cancelled",
    FaintEvent: "faint",
    SwitchEvent: "switch",
}


# ---- 覆盖文件 ----


def available_custom_files() -> dict[str, str]:
    """data/custom/ 下的覆盖文件：文件名 → 说明（文件里 [meta] 的 description，没写时为空）。"""
    files = {}
    for path in sorted(CUSTOM_DIR.glob("*.toml")):
        try:
            meta = load_toml(path).get("meta", {})
        except ConfigError:
            meta = {}  # 写坏了的文件照样列出来，选了以后加载时会报错
        files[path.name] = str(meta.get("description", "")) if isinstance(meta, dict) else ""
    return files


def custom_paths(names: Any) -> list[str]:
    """网页选的覆盖文件名 → 配置里的路径（相对仓库根目录）。只认 data/custom/ 下有的文件。"""
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ConfigError(f"{WHERE}：custom_files 要写覆盖文件名的列表，得到 {names!r}")
    available = available_custom_files()
    for name in names:
        if name not in available:
            choices = "、".join(available) or "没有"
            raise ConfigError(f"{WHERE}：data/custom/ 里没有覆盖文件 {name!r}（可用：{choices}）")
    return [f"data/custom/{name}" for name in names]


def _with_custom_paths(raw: Any) -> dict[str, Any]:
    """把网页配置里的覆盖文件名换成路径，其余原样（交给引擎检查）。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：配置要写成表（键值对），得到 {type(raw).__name__}")
    converted = dict(raw)
    converted["custom_files"] = custom_paths(raw.get("custom_files", []))
    return converted


# ---- 选项和数据 ----


def options() -> dict[str, Any]:
    """网页上的下拉选项，以及第一次打开时用的例子配置（experiments/gl_3v3_example.toml）。"""
    switching = get_args(get_type_hints(TeamPolicyConfig)["switching"])
    return {
        "leagues": [{"cp": cp, "name": name} for cp, name in LEAGUE_NAMES.items()],
        "seasons": [{"key": key, "name": season.name} for key, season in SEASON_PRESETS.items()],
        "custom_files": [{"name": n, "description": d} for n, d in available_custom_files().items()],
        "max_shields": PVPOKE_COMPAT.max_shields,
        "team_size": PVPOKE_COMPAT.max_team_size,
        "switching": [{"key": key, "name": SWITCHING_NAMES.get(key, key)} for key in switching],
        "example": example_config(),
    }


def example_config() -> dict[str, Any]:
    """例子配置，写成网页的格式（没有说明文字；覆盖文件写文件名）。"""
    raw = load_toml(EXAMPLE_CONFIG)
    raw.pop("description", None)
    raw["custom_files"] = [path.rsplit("/", 1)[-1] for path in raw.get("custom_files", [])]
    return raw


def _move_info(move: Move) -> dict[str, Any]:
    return {
        "name": move.name,
        "type": move.type,
        "fast": move.is_fast,
        "power": move.power,
        # 快招是每次得到的能量，大招是要花的能量
        "energy": move.energy_gain if move.is_fast else move.energy_cost,
        "turns": move.turns,
    }


def recommended_movesets(league: int) -> dict[str, list[str]]:
    """PvPoke 排名里这个联盟的推荐配招：宝可梦 ID → [快招, 大招, ...]。

    先看普通排名（"all"），没有的（Mega）再看 Mega 版排名。这个联盟没有排名文件时为空。
    网页上选了宝可梦以后先填这一套，只是方便，可以改。
    """
    movesets: dict[str, list[str]] = {}
    for cup in ("mega", "all"):  # 后面的覆盖前面的：两套都有时用普通排名的
        try:
            ranked = load_rankings(cup, league)
        except ValueError:
            continue
        for entry in ranked:
            movesets[entry.species_id] = [entry.moveset.fast, *entry.moveset.charged]
    return movesets


def _parse_league(raw: Any) -> int | None:
    """查询字符串里的 league（字符串），没写时为 None。"""
    if raw is None:
        return None
    try:
        league = int(raw)
    except (TypeError, ValueError):
        league = 0
    if league <= 0:
        raise ConfigError(f"{WHERE}：league 要写正整数（CP 上限），得到 {raw!r}")
    return league


def species_catalog(custom_files: Any = (), league: Any = None) -> dict[str, Any]:
    """全部宝可梦和招式（加载选中的覆盖文件后）。

    宝可梦按 gamemaster 的顺序；custom 是覆盖文件新加的（gamemaster 里没有）。
    fast / charged 是招式池；extra_charged 是第三个大招能选的（只有部分 Mega 有）。
    给了 league 时，recommended 是 PvPoke 在这个联盟推荐的配招（排名里没有的为 None）。
    """
    names = list(custom_files)
    gm = load_gamemaster(custom_files=custom_paths(names))
    base_ids = set(load_gamemaster().species) if names else set(gm.species)
    league_cp = _parse_league(league)
    recommended = recommended_movesets(league_cp) if league_cp is not None else {}
    species = [
        {
            "id": s.species_id,
            "name": s.name,
            "dex": s.dex,
            "types": list(s.types),
            "tags": list(s.tags),
            "released": s.released,
            "custom": s.species_id not in base_ids,
            "mega": s.is_mega,
            "fast": list(s.fast_move_ids),
            "charged": list(s.charged_move_ids),
            "extra_charged": list(s.extra_charged_move_ids) if s.is_mega else [],
            "recommended": recommended.get(s.species_id),
        }
        for s in gm.species.values()
    ]
    moves = {move_id: _move_info(move) for move_id, move in gm.moves.items()}
    return {"species": species, "moves": moves}


# ---- 一只宝可梦 ----


def _member_info(gm: GameMaster, participant: Participant) -> dict[str, Any]:
    """建好配置的一只：CP、等级、IV、实际能力值、配招、建配置的说明。"""
    build = participant.build
    combatant = make_combatant(gm, build, 0)
    return {
        "label": participant.label,
        "species": build.species_id,
        "species_name": combatant.species.name,
        "types": list(combatant.species.types),
        "cp": combatant.cp,
        "level": build.level,
        "ivs": [build.ivs.atk, build.ivs.def_, build.ivs.hp],
        "mega_level": combatant.mega_level,
        "hp": combatant.stats.hp,
        "atk": combatant.stats.atk,
        "def": combatant.stats.def_,
        "fast": build.fast_move_id,
        "charged": list(build.charged_move_ids),
        "outside_movepool": list(participant.outside_movepool),
        "notes": list(build.notes),
    }


def build_member(raw: Any) -> dict[str, Any]:
    """一只宝可梦按赛季规则建配置（网页上选好以后显示 CP、等级、IV）。

    raw：{"league", "season", "custom_files"（可选）, "member"}；member 的写法同配置文件里的一只。
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, {"league", "season", "custom_files", "member"}, WHERE)
    if "member" not in raw:
        raise ConfigError(f"{WHERE}：缺少 member")
    settings = parse_common_settings(
        {key: raw[key] for key in ("league", "season") if key in raw}
        | {"custom_files": custom_paths(raw.get("custom_files", []))},
        WHERE,
    )
    gm = load_gamemaster(custom_files=settings.custom_files)
    entry = parse_entry(raw["member"], f"{WHERE}：这一只")
    try:
        participant = prepare_entry(gm, entry, settings.league, settings.season)
    except (KeyError, ValueError) as e:
        raise ConfigError(f"{WHERE}：{error_message(e)}") from e
    return _member_info(gm, participant)


# ---- 一场 3v3 ----


def team_battle(raw: Any) -> dict[str, Any]:
    """打一场 3v3（双方都用 TeamPolicy），返回网页显示用的全部数据（见 battle_payload）。"""
    config = parse_team_battle_config(_with_custom_paths(raw), WHERE)
    battle = prepare_team_battle(config)
    return battle_payload(battle, run_team_battle(battle))


def battle_payload(battle: TeamBattle, result: BattleResult) -> dict[str, Any]:
    """一场打完以后网页要显示的东西。数字和文字都来自引擎和报告用的同一批函数。

    - teams：两队每只的配置（_member_info）；names 是时间线里用的名字（镜像时带队名）
    - outcome：一行中文结果（同报告）；result：结果的数字
    - members：每只的情况（team_battle.MemberSummary）
    - opening：开局对位评分（只有一个时是从第 0 方看）
    - switches、charged：换人和大招，带策略给的原因
    - timeline：逐回合的事件和回合末的状态（timeline_payload）
    - report_markdown：和命令行一样的完整报告
    """
    config = battle.config
    names = timeline_names(battle)
    return {
        "settings": {
            "league": config.league,
            "league_name": league_name(config.league),
            "season": config.season.name,
            "custom_log": list(battle.gm.custom_log),
        },
        "teams": [
            {
                "name": team.setup.name,
                "shields": team.setup.shields,
                "policy": policy_text(team.setup.policy),
                "names": list(team.names),
                "members": [_member_info(battle.gm, p) for p in team.members],
            }
            for team in battle.teams
        ],
        "outcome": format_outcome(battle, result),
        "result": {
            "winner": result.winner,
            "ratings": list(result.ratings),
            "turns": result.turns,
            "elapsed_ms": result.elapsed_ms,
            "timed_out": result.timed_out,
            "remaining": list(result.remaining),
            "shields_left": list(result.shields_left),
        },
        "members": [asdict(s) for s in member_summaries(battle, result)],
        "opening": [{"side": o.side, "ratings": o.ratings} for o in opening_matchups(battle)],
        "switches": [asdict(r) | {"kind_text": SWITCH_KINDS[r.kind]} for r in switch_records(result)],
        "charged": [asdict(r) for r in charged_records(result)],
        "timeline": timeline_payload(result, names),
        "report_markdown": format_team_battle_report(battle, result),
    }


def event_payload(event: Event, names: Names) -> dict[str, Any]:
    """一个事件：种类、哪一方的第几只、文字（同文字时间线，不带回合数和名字）、原始字段。"""
    side, slot = event_actor(event)
    return {
        "type": _EVENT_TYPES[type(event)],
        "side": side,
        "slot": slot,
        "text": describe_event(event, names),
        "data": asdict(event),
    }


def timeline_payload(result: BattleResult, names: Names) -> list[dict[str, Any]]:
    """逐回合：这一回合的事件（按发生的顺序）和回合末双方的状态（TurnSnapshot，没有时为 None）。

    每个有事件或者有快照的回合一项，按回合排序。
    """
    snapshots = {snapshot.turn: snapshot for snapshot in result.snapshots}
    events: dict[int, list[dict[str, Any]]] = {}
    for event in result.events:
        events.setdefault(event.turn, []).append(event_payload(event, names))
    return [
        {
            "turn": turn,
            "events": events.get(turn, []),
            "sides": [asdict(side) for side in snapshots[turn].sides] if turn in snapshots else None,
        }
        for turn in sorted(events.keys() | snapshots.keys())
    ]
