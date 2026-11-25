"""网页界面的接口（第 4 步，4a）：收 dict、回 dict，结果都能直接转成 JSON。

网页只负责填表和显示，这里只做转换：把网页发来的配置交给引擎，再把结果整理成网页好显示的结构。
规则、检查和计算都在引擎里（team_battle.py、config.py 等），这里不重复。
tools/run_web.py 把这些函数转发成 HTTP 接口。

- options()：联盟、赛季规则、覆盖文件、策略的可选值，以及例子配置
- species_catalog(custom_files, league)：全部宝可梦（名字、属性、招式池、搜索用的文字、PvPoke 排名）和招式
- build_member(raw)：一只宝可梦按赛季规则建配置（CP、等级、IV、说明）
- team_battle(raw)：打一场 3v3，返回结果、每只的情况、换人和开盾、逐回合时间线、Markdown 报告
- manual_battle(raw)：手动对战，玩家操作一队；重打到下一个要玩家决定的地方，返回局面和能选什么（4c）
- stat_table_payload(league, season, custom_files)：能力值排序，每只的 CP、等级、IV、实际能力值、坦度（4d）

网页发来的配置和 3v3 配置文件（team_battle.py 开头）写法一样、键也一样，只有一处不同：
覆盖文件只能从 data/custom/ 里选，写文件名（例如 "mega_froslass.toml"），不能写任意路径。
写错时抛出 ConfigError，信息和配置文件写错时一样，开头是"网页"。
"""

import json
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import Any, get_args, get_type_hints

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.battle_summary import lane_items
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
from pogo_sim.combatant import Combatant
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import GameMaster, Move, Species, load_gamemaster
from pogo_sim.manual import (
    QUESTION_NAMES,
    ManualDecision,
    ManualError,
    ManualGame,
    format_manual_report,
    parse_decisions,
    play_manual,
)
from pogo_sim.rules import BattleRules
from pogo_sim.rankings import RankedPokemon, load_rankings
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.season import LEAGUE_NAMES, SEASON_PRESETS, league_name
from pogo_sim.stat_table import CACHE_DIR as STAT_CACHE_DIR
from pogo_sim.stat_table import stat_table
from pogo_sim.team_battle import (
    SWITCH_KINDS,
    TeamBattle,
    charged_records,
    charged_use_text,
    format_outcome,
    format_team_battle_report,
    max_hps,
    member_summaries,
    opening_matchups,
    parse_common_settings,
    parse_team_battle_config,
    policy_text,
    prepare_team_battle,
    run_team_battle,
    segment_end_text,
    segments,
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


def league_rankings(league: int) -> dict[str, dict[str, RankedPokemon]]:
    """PvPoke 这个联盟的排名：{"all": {宝可梦 ID: 名次}, "mega": {...}}。这个联盟没有的排名文件不在里面。

    "all" 是普通排名（没有 Mega）；"mega" 是 Mega 版排名（Mega 和非 Mega 一起排）。
    """
    rankings = {}
    for cup in ("all", "mega"):
        try:
            rankings[cup] = {entry.species_id: entry for entry in load_rankings(cup, league)}
        except ValueError:
            continue
    return rankings


def recommended_moveset(rankings: dict[str, dict[str, RankedPokemon]], species_id: str) -> list[str] | None:
    """PvPoke 推荐的配招 [快招, 大招, ...]：先看普通排名，没有的（Mega）再看 Mega 版排名；都没有时为 None。

    网页上选了宝可梦以后先填这一套，只是方便，可以改。
    """
    for cup in ("all", "mega"):
        entry = rankings.get(cup, {}).get(species_id)
        if entry is not None:
            return [entry.moveset.fast, *entry.moveset.charged]
    return None


# 网页搜宝可梦时，名字和 ID 以外也能搜到的词：gamemaster tags 里挑的几个（Mega 另外加），以及少数别名。
SEARCH_TAGS = ("legendary", "mythical", "ultrabeast")
SEARCH_ALIASES: dict[str, str] = {
    "zygarde_complete": "100%",  # 正作叫 100% Forme，PvPoke 的名字是 Complete Forme
}


def normalize_search(text: str) -> str:
    """搜索用的写法：小写、去掉重音（Flabébé → flabebe）、标点换成空格（Mr. Mime → mr mime）。

    网页（app.js 的 normalizeSearch）用同样的办法处理输入的文字。
    """
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def search_text(species: Species) -> str:
    """网页搜这只宝可梦时在哪些文字里找：名字、名字去掉空格、ID、部分 tags、Mega（含原始回归）、别名。

    网页把输入拆成几个词，每个词都在这里出现（不分先后）就算搜到，
    所以 "mega venu"、"venusaur mega"、"zygarde 100" 都能搜到。
    """
    name = normalize_search(species.name)
    words = [name, name.replace(" ", ""), normalize_search(species.species_id)]
    words += [tag for tag in SEARCH_TAGS if tag in species.tags]
    if species.is_mega:
        words.append("mega")
    if species.species_id in SEARCH_ALIASES:
        words.append(normalize_search(SEARCH_ALIASES[species.species_id]))
    return " ".join(words)


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

    宝可梦按 gamemaster 的顺序（图鉴编号，同一只的各形态挨着）；custom 是覆盖文件新加的（gamemaster 里没有）。
    fast / charged 是招式池；extra_charged 是第三个大招能选的（只有部分 Mega 有）。
    search 是网页搜宝可梦时找的文字（search_text）。
    给了 league 时：recommended 是 PvPoke 在这个联盟推荐的配招，rank 是普通排名的名次，
    mega_rank 是 Mega 在 Mega 版排名里的名次；排名里没有的为 None。
    """
    names = list(custom_files)
    gm = load_gamemaster(custom_files=custom_paths(names))
    league_cp = _parse_league(league)
    rankings = league_rankings(league_cp) if league_cp is not None else {}
    describe = _species_describer(gm, names, rankings)
    species = [
        {
            **describe(s),
            "fast": list(s.fast_move_ids),
            "charged": list(s.charged_move_ids),
            "extra_charged": list(s.extra_charged_move_ids) if s.is_mega else [],
            "recommended": recommended_moveset(rankings, s.species_id),
        }
        for s in gm.species.values()
    ]
    moves = {move_id: _move_info(move) for move_id, move in gm.moves.items()}
    return {"species": species, "moves": moves}


def _species_describer(
    gm: GameMaster, custom_names: list[str], rankings: dict[str, dict[str, RankedPokemon]]
) -> Callable[[Species], dict[str, Any]]:
    """宝可梦列表和能力值表共用的说明：名字、图鉴编号、属性、tags、是否实装、是否覆盖文件新加的、排名、搜索文字。"""
    base_ids = set(load_gamemaster().species) if custom_names else set(gm.species)
    normal_rank = {species_id: entry.rank for species_id, entry in rankings.get("all", {}).items()}
    mega_rank = {species_id: entry.rank for species_id, entry in rankings.get("mega", {}).items()}

    def describe(s: Species) -> dict[str, Any]:
        return {
            "id": s.species_id,
            "name": s.name,
            "dex": s.dex,
            "types": list(s.types),
            "tags": list(s.tags),
            "released": s.released,
            "custom": s.species_id not in base_ids,
            "mega": s.is_mega,
            "shadow": s.is_shadow,
            "rank": normal_rank.get(s.species_id),
            "mega_rank": mega_rank.get(s.species_id) if s.is_mega else None,
            "search": search_text(s),
        }

    return describe


# ---- 能力值排序（4d） ----

# 同时来两个请求时一个一个算：第二个等第一个算完，直接读缓存。
_STAT_TABLE_LOCK = threading.Lock()


def stat_table_payload(
    league: Any,
    season: Any,
    custom_files: Any = (),
    *,
    cache_dir: Path = STAT_CACHE_DIR,
    species_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """能力值排序（4d，docs/mechanics.md 14.6）：每只宝可梦在这个联盟的 CP、等级、IV、实际能力值、坦度。

    每只的等级和 IV 按赛季规则选（stat_table.py）；攻击、防御含暗影倍率。
    筛选、排序、自定义公式（攻^a × 防^b × HP^c）在网页上做，只是显示，不改数据。
    rows：每只一行，宝可梦的说明和 species_catalog 一样，另有 cp、level、ivs、atk、def、hp、
    bulk（坦度 = 防 × HP）、stat_product（攻 × 防 × HP）、base（种族值 攻/防/HP）。
    skipped：在这个联盟没有合法配置的，和原因。shadow_multipliers：攻击、防御乘的暗影倍率（网页上说明用）。
    computed、seconds：这次新算了几只、花了几秒（一个联盟第一次打开时要算，之后读本地缓存）。
    cache_dir、species_ids 只给测试用。
    """
    league_cp = _parse_league(league)
    if league_cp not in LEAGUE_NAMES:
        choices = " / ".join(str(cp) for cp in LEAGUE_NAMES)
        raise ConfigError(f"{WHERE}：league 要是 {choices}，得到 {league!r}")
    if season not in SEASON_PRESETS:
        raise ConfigError(f"{WHERE}：season 要是 {' / '.join(SEASON_PRESETS)}，得到 {season!r}")
    names = list(custom_files)
    paths = [REPO_ROOT / path for path in custom_paths(names)]

    start = time.perf_counter()
    with _STAT_TABLE_LOCK:
        table = stat_table(league_cp, season, paths, rules=PVPOKE_COMPAT, cache_dir=cache_dir, species_ids=species_ids)
    seconds = time.perf_counter() - start

    gm = load_gamemaster(custom_files=paths)
    describe = _species_describer(gm, names, league_rankings(league_cp))
    rows = []
    for row in table.rows:
        species = gm.species[row.species_id]
        base = species.base_stats
        rows.append({
            **describe(species),
            "cp": row.cp,
            "level": row.level,
            "ivs": [row.ivs.atk, row.ivs.def_, row.ivs.hp],
            "atk": row.atk,
            "def": row.def_,
            "hp": row.hp,
            "bulk": row.bulk,
            "stat_product": row.stat_product,
            "base": [base.atk, base.def_, base.hp],
        })
    skipped = [
        {"id": item.species_id, "name": gm.species[item.species_id].name, "reason": item.reason}
        for item in table.skipped
    ]
    return {
        "league": league_cp,
        "season": season,
        "rows": rows,
        "skipped": skipped,
        "shadow_multipliers": {"atk": PVPOKE_COMPAT.shadow_attack, "def": PVPOKE_COMPAT.shadow_defense},
        "computed": table.computed,
        "seconds": round(seconds, 2),
    }


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


def battle_payload(battle: TeamBattle, result: BattleResult, report_markdown: str | None = None) -> dict[str, Any]:
    """一场打完以后网页要显示的东西。数字和文字都来自引擎和报告用的同一批函数。

    - teams：两队每只的配置（_member_info）；names 是时间线里用的名字（镜像时带队名）
    - outcome：一行中文结果（同报告）；result：结果的数字
    - members：每只的情况（team_battle.MemberSummary）
    - opening：开局对位评分（只有一个时是从第 0 方看）
    - switches、charged：换人和大招，带策略给的原因
    - segments：对位分段（segments_payload）；chart：过程图的数据（chart_payload）
    - timeline：逐回合的事件和回合末的状态（timeline_payload）
    - report_markdown：和命令行一样的完整报告（手动对战时传入手动对战的报告）
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
        "segments": segments_payload(battle, result),
        "chart": chart_payload(battle, result),
        "timeline": timeline_payload(result, names),
        "report_markdown": report_markdown if report_markdown is not None else format_team_battle_report(battle, result),
    }


def segments_payload(battle: TeamBattle, result: BattleResult) -> list[dict[str, Any]]:
    """对位分段（battle_summary.Segment），加上报告里用的文字：每方的大招（charged_text）和怎么结束（end_text）。"""
    all_segments = segments(battle, result)
    return [
        asdict(segment) | {
            "charged_text": [charged_use_text(side) for side in segment.sides],
            "end_text": segment_end_text(battle, result, segment, last=i == len(all_segments) - 1),
        }
        for i, segment in enumerate(all_segments)
    ]


def chart_payload(battle: TeamBattle, result: BattleResult) -> dict[str, Any]:
    """过程图的数据。逐回合的数组都从第 0 回合（开打之前）开始，下标就是回合数：

    - elapsed_ms[t]：第 t 回合结束时的对战时间
    - sides[方]：active[t] 是第 t 回合在场的第几只（第 0 回合是首发）；hp[第几只][t]、energy[第几只][t]
      是第 t 回合结束时的 HP 和能量；max_hp；lane 是招式带（battle_summary.LaneItem）
    - move_names：图上用到的招式的名字
    """
    lanes = lane_items(result, battle.gm)
    hps = max_hps(battle)
    snapshots = result.snapshots
    if [s.turn for s in snapshots] != list(range(1, result.turns + 1)):
        raise ValueError("快照要每回合一个")  # 引擎每回合都记，不应该发生
    sides = []
    for side, team in enumerate(battle.teams):
        size = len(team.members)
        sides.append({
            "active": [0] + [s.sides[side].active for s in snapshots],
            "max_hp": list(hps[side]),
            "hp": [[hps[side][slot]] + [s.sides[side].member_hp[slot] for s in snapshots] for slot in range(size)],
            "energy": [[0] + [s.sides[side].member_energy[slot] for s in snapshots] for slot in range(size)],
            "lane": [asdict(item) for item in lanes[side]],
        })
    used = {item.move_id for lane in lanes for item in lane if item.move_id in battle.gm.moves}
    return {
        "turns": result.turns,
        "elapsed_ms": [0] + [s.elapsed_ms for s in snapshots],
        "sides": sides,
        "move_names": {move_id: battle.gm.get_move(move_id).name for move_id in sorted(used)},
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
            "elapsed_ms": snapshots[turn].elapsed_ms if turn in snapshots else None,
        }
        for turn in sorted(events.keys() | snapshots.keys())
    ]


# ---- 手动对战（4c） ----


@lru_cache(maxsize=8)
def _prepare_from_key(key: str) -> TeamBattle:
    return prepare_team_battle(parse_team_battle_config(json.loads(key)["config"], WHERE))


def prepared_battle(raw: Any) -> TeamBattle:
    """检查配置并按赛季规则建好两队。手动对战每做一个决定都要重打，同一个配置只建一次（建配置比打一场慢得多）。

    缓存的键是配置本身和选中的覆盖文件的修改时间，所以改了覆盖文件会重新建。
    """
    converted = _with_custom_paths(raw)
    mtimes = [(REPO_ROOT / path).stat().st_mtime_ns for path in converted["custom_files"]]
    try:
        key = json.dumps({"config": converted, "mtimes": mtimes}, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{WHERE}：配置里有不能转成 JSON 的值（{e}）") from e
    return _prepare_from_key(key)


def manual_battle(raw: Any) -> dict[str, Any]:
    """手动对战：玩家操作第 side 方，按 decisions 从第 1 回合重打到下一个要玩家决定的地方（pogo_sim/manual.py）。

    raw：{"config": 和 team_battle 一样的配置, "side": 0 或 1, "decisions": [玩家到现在的决定]}。
    返回：
    - 停下来时 {"status": "decide", ...}，内容见 manual_question_payload；
    - 打完时 {"status": "finished", "result": battle_payload}（含对方每个决定的原因、过程图、报告）。
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, {"config", "side", "decisions"}, WHERE)
    for key in ("config", "side"):
        if key not in raw:
            raise ConfigError(f"{WHERE}：缺少 {key}")
    side = raw["side"]
    if side not in (0, 1) or isinstance(side, bool):
        raise ConfigError(f"{WHERE}：side（玩家操作哪一方）要是 0 或 1，得到 {side!r}")
    battle = prepared_battle(raw["config"])
    try:
        decisions = parse_decisions(raw.get("decisions", []))
        game = play_manual(battle, side, decisions)
    except ManualError as e:
        raise ConfigError(f"{WHERE}：{e}") from e

    if game.result is not None:
        payload = battle_payload(battle, game.result, format_manual_report(battle, game.result, side))
        payload["teams"][side]["policy"] = "玩家手动操作"
        return {"status": "finished", "side": side, "decisions": len(decisions), "result": payload}
    return {"status": "decide", "side": side, **manual_question_payload(battle, game, side)}


def _option_label(option: ManualDecision, names: Sequence[str], me: Combatant) -> str:
    """一个选项在网页按钮上的文字。"""
    if option.kind == "shield":
        return "开盾" if option.shield else "不开盾"
    if option.to is not None:
        return f"换上 {names[option.to]}"
    if option.kind == "zero_turn_switch":
        return "不换"
    if option.action == "fast":
        return f"快招 {me.fast_move.name}"
    if option.action == "charged":
        move = next(m for m in me.charged_moves if m.move_id == option.move_id)
        return f"大招 {move.name}（{move.energy_cost} 能量）"
    return "什么都不做"


def fast_moves_needed(energy: int, cost: int, gain: int) -> int | None:
    """还差几次快招才够放这个大招（够了是 0；快招不给能量时为 None）。"""
    if energy >= cost:
        return 0
    if gain <= 0:
        return None
    return ceil((cost - energy) / gain)


def _side_state(
    battle: Battle, side: int, team_name: str, names: Sequence[str], hidden_energy: int | None = None
) -> dict[str, Any]:
    """一方现在的状态：盾、换人冷却、在场的是谁，每只的 HP、能量、能力等级、招式（每个大招够不够、还差几次快招）。

    hidden_energy：开盾的问题里，对方在场那只显示这一回合开始时的能量（见 manual_question_payload）。
    """
    team = battle.teams[side]
    members = []
    for slot, member in enumerate(team.members):
        energy = hidden_energy if hidden_energy is not None and slot == team.active else member.energy
        gain = member.fast_move.energy_gain
        members.append({
            "slot": slot,
            "name": names[slot],
            "types": list(member.species.types),
            "hp": member.hp,
            "max_hp": member.stats.hp,
            "energy": energy,
            "fainted": member.is_fainted,
            "atk_stage": member.atk_stage,
            "def_stage": member.def_stage,
            "fast": {**_move_info(member.fast_move), "id": member.fast_move.move_id},
            "charged": [
                {
                    **_move_info(move),
                    "id": move.move_id,
                    "ready": energy >= move.energy_cost,
                    "fast_needed": fast_moves_needed(energy, move.energy_cost, gain),
                }
                for move in member.charged_moves
            ],
        })
    return {
        "name": team_name,
        "active": team.active,
        "shields": team.shields,
        "switch_timer_ms": team.switch_timer_ms,
        "members": members,
    }


def damage_preview(me: Combatant, opponent: Combatant, rules: BattleRules) -> dict[str, Any]:
    """出招时的伤害参考（双方在场的两只，按现在的能力等级；不开盾时）。

    - my_charged[招式]：威力从 min_charge 到 100%（percents，每 1%）各打多少（damage），
      打死至少要几 %（ko_min，打不死为 None），不打死最多几 %（survive_max，怎么都打死为 None）
    - my_fast、their_fast：双方快招一次打多少；their_charged：对方每个大招满蓄力打多少
    网页的拖动条只是查这张表，伤害都是引擎同一个函数算的（damage.calculate_damage）。
    """
    percents = list(range(ceil(rules.min_charge * 100), 101))
    mine = {}
    for move in me.charged_moves:
        damages = [calculate_damage(move, me.damage_side(), opponent.damage_side(), rules, p / 100) for p in percents]
        ko = [p for p, d in zip(percents, damages) if d >= opponent.hp]
        alive = [p for p, d in zip(percents, damages) if d < opponent.hp]
        mine[move.move_id] = {
            "damage": damages,
            "ko_min": ko[0] if ko else None,
            "survive_max": alive[-1] if alive else None,
        }
    return {
        "percents": percents,
        "target_hp": opponent.hp,
        "my_charged": mine,
        "my_fast": calculate_damage(me.fast_move, me.damage_side(), opponent.damage_side(), rules),
        "their_fast": calculate_damage(opponent.fast_move, opponent.damage_side(), me.damage_side(), rules),
        "their_charged": {
            move.move_id: calculate_damage(move, opponent.damage_side(), me.damage_side(), rules)
            for move in opponent.charged_moves
        },
    }


def manual_question_payload(team_battle: TeamBattle, game: ManualGame, side: int) -> dict[str, Any]:
    """对战停下来问玩家时，网页要显示的东西：

    - question：第几个决定、第几回合、问的是什么（kind、kind_text）、能选什么（options，每个带按钮文字 label）
    - sides：双方现在的状态（_side_state）；turn、elapsed_ms
    - damage：出招的问题里，伤害参考（damage_preview）
    - events：到现在为止结算过的事件（不含双方的决定和原因，开盾的原因也去掉：对方的打算不能提前看到，
      打完以后在时间线和报告里看）

    开盾的问题里，对方的大招还没结算，不告诉玩家是哪一招；对方在场那只的能量显示这一回合开始时的值
    （它的能量已经扣掉了大招的能量，看了就知道是哪一招）。
    """
    battle = game.battle
    question = game.question
    assert question is not None and game.view is not None
    names = timeline_names(team_battle)
    hidden_energy = None
    if question.kind == "shield":
        opponent = battle.teams[1 - side]
        hidden_energy = battle.snapshots[-1].sides[1 - side].member_energy[opponent.active] if battle.snapshots else 0
    sides = [
        _side_state(battle, s, team_battle.teams[s].setup.name, names[s], hidden_energy if s == 1 - side else None)
        for s in (0, 1)
    ]
    me = battle.teams[side].active_member
    opponent_active = battle.teams[1 - side].active_member
    return {
        "question": {
            "index": question.index,
            "turn": question.turn,
            "kind": question.kind,
            "kind_text": QUESTION_NAMES[question.kind],
            "options": [asdict(o) | {"label": _option_label(o, names[side], me)} for o in question.options],
        },
        "turn": question.turn,
        "elapsed_ms": battle.elapsed_ms,
        "min_charge": battle.rules.min_charge,
        "sides": sides,
        "damage": damage_preview(me, opponent_active, battle.rules) if question.kind == "action" else None,
        "events": [
            event_payload(replace(e, shield_reason=None) if isinstance(e, MoveEvent) else e, names)
            for e in battle.events
            if not isinstance(e, DecisionEvent)
        ],
    }
