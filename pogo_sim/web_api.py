"""网页界面的接口（第 4 步，4a）：收 dict、回 dict，结果都能直接转成 JSON。

网页只负责填表和显示，这里只做转换：把网页发来的配置交给引擎，再把结果整理成网页好显示的结构。
规则、检查和计算都在引擎里（team_battle.py、config.py 等），这里不重复。
tools/run_web.py 把这些函数转发成 HTTP 接口。

- options()：联盟、赛季规则、覆盖文件、策略的可选值，以及例子配置
- species_catalog(custom_files, league)：全部宝可梦（名字、属性、招式池、搜索用的文字、PvPoke 排名）和招式
- build_member(raw)：一只宝可梦按赛季规则建配置（CP、等级、IV、说明）
- team_battle(raw)：打一场 3v3，返回结果、每只的情况、换人和开盾、逐回合时间线、Markdown 报告
- manual_battle(raw)：手动对战，玩家操作一队；重打到下一个要玩家决定的地方，返回局面和能选什么（4c）
- best_response(raw)：对另一队的固定策略，搜索一队的打法；改了哪些决定、每个决定点各选项的结果（4e）
- library_payload()、save_library_team(raw)：队伍库（teams/，一队一个文件）：列出、存进去；不能删除（4f）
- export_team_battle(raw)、import_team_battle(raw)：把页面上的配置导出成 3v3 配置文件（TOML），或者从这样的文件导入（4f）
- matchup_options()、matchups(raw)、matchup_battle(raw)：1v1 九宫格和环境前 N（同命令行 tools.run_matchups），
  以及其中一场的过程图和时间线；export_matchups(raw)、import_matchups(raw)：导出 / 导入九宫格的配置文件（4g）
- matrix_options()、team_matrix_stream(raw)、matrix_battle(raw)、matrix_pairing_config(raw)：队伍对队伍（同命令行
  tools.run_team_matrix），边打边给出进度；其中一场的完整结果；把那一场送到"打一场"页的配置；
  export_matrix(raw)、import_matrix(raw)：导出 / 导入队伍对队伍的配置文件（4h）
- stat_table_payload(league, season, custom_files)：能力值排序，每只的 CP、等级、IV、实际能力值、坦度（4d）

网页发来的配置和配置文件（3v3 见 team_battle.py 开头，九宫格见 matchups.py 开头，队伍对队伍见 team_matrix.py 开头）
写法一样、键也一样，只有一处不同：
覆盖文件只能从 data/custom/ 里选，写文件名（例如 "mega_froslass.toml"），不能写任意路径。
写错时抛出 ConfigError，信息和配置文件写错时一样，开头是"网页"。
"""

import json
import re
import threading
import time
import tomllib
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, fields, replace
from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.battle_summary import lane_items
from pogo_sim.best_response import (
    DECISION_KINDS,
    DecisionPoint,
    Score,
    Tried,
    format_best_response_report,
    format_score,
    search_best_response,
)
from pogo_sim.combatant import make_combatant
from pogo_sim.config import (
    REPO_ROOT,
    ConfigError,
    Participant,
    check_unknown_keys,
    entry_table,
    error_message,
    load_toml,
    marked,
    merge_tables,
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
from pogo_sim.matchups import (
    SHIELD_COUNTS,
    WIN_RATING,
    Matchups,
    ShieldGrid,
    battle_names,
    fight,
    format_csv,
    format_report,
    make_sides,
    parse_matchup_config,
    pool_summary,
    prepare_matchups,
    run_all,
    run_pools,
)
from pogo_sim.matchups import format_outcome as format_1v1_outcome
from pogo_sim.policy import ChargedAction, FastAction, SwitchAction
from pogo_sim.rules import BattleRules
from pogo_sim.rankings import (
    IV_RULES,
    POOL_KINDS,
    RANKING_CUPS,
    Pool,
    PoolBuilder,
    PoolSpec,
    RankedPokemon,
    load_rankings,
    prepare_pool,
    rankings_path,
)
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.season import LEAGUE_NAMES, SEASON_PRESETS, SeasonRules, league_name
from pogo_sim.simple_policy import SimplePolicyConfig
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
    parse_team,
    parse_team_battle_config,
    policy_text,
    prepare_team,
    prepare_team_battle,
    run_team_battle,
    segment_end_text,
    segments,
    switch_records,
    timeline_names,
)
from pogo_sim import team_library, team_matrix
from pogo_sim.team_policy import TeamPolicyConfig
from pogo_sim.toml_writer import dumps as toml_dumps
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
        "result": result_payload(result),
        "members": [asdict(s) for s in member_summaries(battle, result)],
        "opening": [{"side": o.side, "ratings": o.ratings} for o in opening_matchups(battle)],
        "switches": [asdict(r) | {"kind_text": SWITCH_KINDS[r.kind]} for r in switch_records(result)],
        "charged": [asdict(r) for r in charged_records(result)],
        "segments": segments_payload(battle, result),
        "chart": chart_payload(battle.gm, max_hps(battle), result),
        "timeline": timeline_payload(result, names),
        "report_markdown": report_markdown if report_markdown is not None else format_team_battle_report(battle, result),
    }


def result_payload(result: BattleResult) -> dict[str, Any]:
    """结果的数字（3v3 和 1v1 都用）。"""
    return {
        "winner": result.winner,
        "ratings": list(result.ratings),
        "turns": result.turns,
        "elapsed_ms": result.elapsed_ms,
        "timed_out": result.timed_out,
        "remaining": list(result.remaining),
        "shields_left": list(result.shields_left),
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


def chart_payload(gm: GameMaster, hps: Sequence[Sequence[int]], result: BattleResult) -> dict[str, Any]:
    """过程图的数据（3v3 和 1v1 都用）。hps[方][第几只] 是最大 HP。逐回合的数组都从第 0 回合（开打之前）开始，
    下标就是回合数：

    - elapsed_ms[t]：第 t 回合结束时的对战时间
    - sides[方]：active[t] 是第 t 回合在场的第几只（第 0 回合是首发）；hp[第几只][t]、energy[第几只][t]
      是第 t 回合结束时的 HP 和能量；max_hp；lane 是招式带（battle_summary.LaneItem）
    - move_names：图上用到的招式的名字
    """
    lanes = lane_items(result, gm)
    snapshots = result.snapshots
    if [s.turn for s in snapshots] != list(range(1, result.turns + 1)):
        raise ValueError("快照要每回合一个")  # 引擎每回合都记，不应该发生
    sides = []
    for side in (0, 1):
        size = len(hps[side])
        sides.append({
            "active": [0] + [s.sides[side].active for s in snapshots],
            "max_hp": list(hps[side]),
            "hp": [[hps[side][slot]] + [s.sides[side].member_hp[slot] for s in snapshots] for slot in range(size)],
            "energy": [[0] + [s.sides[side].member_energy[slot] for s in snapshots] for slot in range(size)],
            "lane": [asdict(item) for item in lanes[side]],
        })
    used = {item.move_id for lane in lanes for item in lane if item.move_id in gm.moves}
    return {
        "turns": result.turns,
        "elapsed_ms": [0] + [s.elapsed_ms for s in snapshots],
        "sides": sides,
        "move_names": {move_id: gm.get_move(move_id).name for move_id in sorted(used)},
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


# ---- 对固定对手策略的应对（4e） ----


def best_response(raw: Any) -> dict[str, Any]:
    """对另一队的固定策略（TeamPolicy），搜索第 side 方的打法（逐步试探，pogo_sim/best_response.py）。

    raw：{"config": 和 team_battle 一样的配置, "side": 搜索哪一方（0 或 1）}。
    返回：
    - search：概况——搜索的是哪一方、原策略和搜索后的结果、一共几个决定、试过几个、改了几个、打了几场、用时
    - tried：试过的每个决定点（有不止一个选项的），按搜索的顺序（tried_payload）；changed 为真的是改了的
    - result：搜索后的这一场（battle_payload；报告是 best-response 的完整报告，和命令行 --best-response 一样）
    - baseline：原策略那一场（battle_payload；和 team_battle 打出来的完全相同）
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, {"config", "side"}, WHERE)
    for key in ("config", "side"):
        if key not in raw:
            raise ConfigError(f"{WHERE}：缺少 {key}")
    side = raw["side"]
    if side not in (0, 1) or isinstance(side, bool):
        raise ConfigError(f"{WHERE}：side（搜索哪一方的打法）要是 0 或 1，得到 {side!r}")
    battle = prepared_battle(raw["config"])
    response = search_best_response(battle, side)

    result = battle_payload(battle, response.best.result, format_best_response_report(battle, response))
    policy = policy_text(battle.teams[side].setup.policy)
    result["teams"][side]["policy"] = f"逐步试探搜索出来的打法；原策略（起点）是 {policy}"
    names = [team.setup.name for team in battle.teams]
    return {
        "search": {
            "side": side,
            "team": names[side],
            "opponent": names[1 - side],
            "baseline": score_payload(response.baseline.score) | {"text": format_outcome(battle, response.baseline.result)},
            "best": score_payload(response.best.score) | {"text": format_outcome(battle, response.best.result)},
            "decisions": len(response.best.points),
            "examined": response.examined,
            "changed": len(response.changes),
            "trials": response.trials,
            "seconds": round(response.seconds, 2),
        },
        "tried": [tried_payload(battle, side, tried) for tried in response.tried],
        "result": result,
        "baseline": battle_payload(battle, response.baseline.result),
    }


def score_payload(value: Score) -> dict[str, Any]:
    """比较两场用的分数（从搜索的一方看）：outcome 赢 2 / 平 1 / 输 0，rating 是评分，short 例如"输 221"。"""
    return {"outcome": value[0], "rating": value[1], "short": format_score(value)}


def choice_label(battle: TeamBattle, side: int, point: DecisionPoint, option: Any) -> str:
    """决定点的一个选项在网页上的文字，和手动对战的按钮一样，例如"快招 Bubble""换上 Medicham""不开盾"。"""
    names = timeline_names(battle)[side]
    if point.kind == "shield":
        return "开盾" if option else "不开盾"
    if point.kind in ("zero_turn", "replacement"):
        return "不换" if option is None else f"换上 {names[option]}"
    if isinstance(option, FastAction):
        build = battle.teams[side].members[point.active].build
        return f"快招 {battle.gm.get_move(build.fast_move_id).name}"
    if isinstance(option, ChargedAction):
        return f"大招 {battle.gm.get_move(option.move_id).name}"
    if isinstance(option, SwitchAction):
        return f"换上 {names[option.to]}"
    raise ValueError(f"不认识的选项 {option!r}")


def tried_payload(battle: TeamBattle, side: int, tried: Tried) -> dict[str, Any]:
    """试过的一个决定点：第几个决定、回合、种类、原策略的选择、搜索后的选择、试之前和试之后的结果，
    以及每个选项打出来的结果（options：文字、分数、是不是原策略的选择、是不是搜索后的选择）。"""
    point = tried.point

    def label(option: Any) -> str:
        return choice_label(battle, side, point, option)

    return {
        "index": point.index,
        "turn": point.turn,
        "kind": point.kind,
        "kind_text": DECISION_KINDS[point.kind],
        "policy_choice": label(point.policy_choice),
        "chosen": label(tried.chosen),
        "changed": tried.changed,
        "before": score_payload(tried.before),
        "after": score_payload(tried.after),
        "options": [
            {
                "label": label(option),
                "score": score_payload(value),
                "policy": option == point.policy_choice,
                "chosen": option == tried.chosen,
            }
            for option, value in tried.option_scores
        ],
    }


# ---- 队伍库和导入导出（4f） ----

# 网页上每队只能改盾数和主动换不换人（4a）；配置里别的策略参数、[rules]、说明文字导入时用不上，要告诉用户。
PAGE_POLICY_KEYS = ("switching",)


def library_payload() -> dict[str, Any]:
    """队伍库（team_library.LIBRARY_DIR，即仓库的 teams/）里的全部队伍。

    - teams：每队的文件名、队名、常用联盟、用到的覆盖文件、说明，team 是 [team] 表的原样内容
      （和网页上一队的写法、3v3 配置里的一个 [[team]] 相同），unsupported 是网页上用不上的设置（page_unsupported）
    - broken：读不了的文件和原因
    """
    library = team_library.load_library()
    return {
        "dir": "teams/",
        "teams": [
            {
                "file": entry.file,
                "name": entry.name,
                "league": entry.league,
                "league_name": league_name(entry.league),
                "custom_files": list(entry.custom_files),
                "note": entry.note,
                "team": entry.team,
                "unsupported": team_unsupported(entry.team, {}),
            }
            for entry in library.teams
        ],
        "broken": [{"file": b.file, "error": b.error} for b in library.broken],
    }


def save_library_team(raw: Any) -> dict[str, Any]:
    """把页面上的一队存进队伍库。

    raw：{"league", "season", "custom_files", "team": 一队（和打一场的配置里的一队相同）, "note"（可选）, "overwrite"（可选）}。
    先和打一场一样检查、建一遍配置（建不了的不让存）；文件里记下联盟和这一队用到的覆盖文件。
    文件已经有了、又没让覆盖时不写，返回 saved = False 和已有的那一队（existing），网页问过再带 overwrite = true 重发。
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, {"league", "season", "custom_files", "team", "note", "overwrite"}, WHERE)
    if "team" not in raw:
        raise ConfigError(f"{WHERE}：缺少 team")
    note = raw.get("note", "")
    if not isinstance(note, str):
        raise ConfigError(f"{WHERE}：note 要写字符串，得到 {note!r}")
    overwrite = raw.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise ConfigError(f"{WHERE}：overwrite 要写 true / false，得到 {overwrite!r}")
    settings = parse_common_settings(
        {key: raw[key] for key in ("league", "season") if key in raw}
        | {"custom_files": custom_paths(raw.get("custom_files", []))},
        WHERE,
    )
    setup = parse_team(raw["team"], {}, PVPOKE_COMPAT, f"{WHERE}：这一队")
    gm = load_gamemaster(custom_files=settings.custom_files)
    prepare_team(gm, setup, settings.league, settings.season)  # 和打一场同一套检查

    entry = team_library.LibraryTeam(
        file=team_library.file_name(setup.name),
        league=settings.league,
        custom_files=team_library.custom_files_used(settings.custom_files, setup.members),
        note=note,
        team=raw["team"],
    )
    saved = team_library.save_team(entry, overwrite=overwrite)
    payload: dict[str, Any] = {"saved": saved, "file": entry.file, "custom_files": list(entry.custom_files)}
    if not saved:
        existing = next((t for t in library_payload()["teams"] if t["file"] == entry.file), None)
        payload["existing"] = existing or {"error": f"teams/{entry.file} 已经有了，但读不了"}
    return payload


def team_unsupported(team: Any, shared_policy: dict[str, Any]) -> list[str]:
    """一队里网页上用不上的策略参数（只认盾数和 switching），例如 ["bait_shields"]。"""
    policy = team.get("policy", {}) if isinstance(team, dict) else {}
    merged = merge_tables(shared_policy, policy if isinstance(policy, dict) else {})
    return sorted(key for key in merged if key not in PAGE_POLICY_KEYS)


def _page_team(team: dict[str, Any], shared_policy: dict[str, Any]) -> dict[str, Any]:
    """配置里的一队（或者队伍对队伍的 [opponent_sample]）写成网页的样子：策略只留网页能改的（共用的 [policy] 合并进来）。"""
    merged = merge_tables(shared_policy, team.get("policy", {}))
    page = {key: value for key, value in team.items() if key != "policy"}
    policy = {key: merged[key] for key in PAGE_POLICY_KEYS if key in merged}
    if policy:
        page["policy"] = policy
    return page


def export_team_battle(raw: Any) -> dict[str, Any]:
    """把页面上的配置写成 3v3 配置文件（TOML），命令行 tools.run_team_battle 能直接跑。

    先和打一场一样检查、建一遍两队，所以导出的文件一定能跑。覆盖文件写成 data/custom/ 下的路径。
    返回 {"filename": 建议的文件名, "text": 文件内容}。
    """
    prepared_battle(raw)  # 检查（同打一场；建好的两队缓存起来，接着打一场时不用再建）
    names = [team["name"] for team in raw["team"]]
    filename = "3v3_" + "_vs_".join(team_library.file_name(name).removesuffix(".toml") for name in names) + ".toml"
    header = export_header(" 3v3 ", "team_battle.py", "run_team_battle", filename)
    return {"filename": filename, "text": toml_dumps(ordered_config(raw, ("custom_files", "league", "season")), header)}


def import_team_battle(raw: Any) -> dict[str, Any]:
    """从 3v3 配置文件（TOML 文本）导入：检查和命令行读配置文件完全相同，再写成网页的样子。

    raw：{"text": 文件内容, "name": 文件名（可选，报错信息里用）}。
    覆盖文件只能是 data/custom/ 里的（网页的限制）。网页上用不上的设置（说明文字、[rules]、
    盾数和 switching 以外的策略参数）不导入，写在 warnings 里。
    返回 {"config": 网页的配置（同 example_config 的写法）, "warnings": [...]}。
    """
    data, where = read_imported_file(raw)
    parse_team_battle_config(data, where)
    names = imported_custom_names(data, where)

    shared_policy = data.get("policy", {})
    warnings = []
    if data.get("description"):
        warnings.append("说明文字（description）网页上不显示，没有导入")
    if data.get("rules"):
        warnings.append(rules_warning(data["rules"]))
    for team in data["team"]:
        unsupported = team_unsupported(team, shared_policy)
        if unsupported:
            warnings.append(policy_warning(team["name"], unsupported))

    config = {key: value for key, value in data.items() if key not in ("description", "rules", "policy")}
    config["custom_files"] = names
    config["team"] = [_page_team(team, shared_policy) for team in data["team"]]
    return {"config": config, "warnings": warnings}


def rules_warning(rules: dict[str, Any]) -> str:
    """导入时：配置里的 [rules] 网页上改不了。"""
    return f"机制规则 [rules] 网页上改不了，没有导入：{'、'.join(sorted(rules))}"


def policy_warning(owner: str, keys: Sequence[str]) -> str:
    """导入时：这一队（owner）的策略参数里，网页上改不了的（team_unsupported）。"""
    return f"{owner} 的策略参数网页上改不了（只能改盾数和主动换不换人），没有导入：{'、'.join(keys)}"


def read_imported_file(raw: Any) -> tuple[dict[str, Any], str]:
    """导入的配置文件：raw = {"text": 文件内容, "name": 文件名（可选）}。返回读出来的表和报错信息的开头。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, {"text", "name"}, WHERE)
    text, name = raw.get("text"), raw.get("name", "")
    if not isinstance(text, str) or not isinstance(name, str):
        raise ConfigError(f"{WHERE}：text 和 name 要写字符串")
    where = f"导入的文件{name and f' {name}'}"
    try:
        return tomllib.loads(text), where
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{where}：不是合法的 TOML（{e}）") from e


def imported_custom_names(data: dict[str, Any], where: str) -> list[str]:
    """导入的文件里的覆盖文件（路径）→ 网页用的文件名。网页只能用 data/custom/ 里的。"""
    names = []
    for path in data.get("custom_files", []):
        file = path.removeprefix("data/custom/")
        if "/" in file or file not in available_custom_files():
            raise ConfigError(f"{where}：网页只能用 data/custom/ 里的覆盖文件，{path!r} 不在那里")
        names.append(file)
    return names


def export_header(kind: str, module: str, tool: str, filename: str) -> list[str]:
    """导出的配置文件开头的注释：是什么、格式在哪里、怎么运行。"""
    return [
        f"网页导出的{kind}配置（格式见 pogo_sim/{module} 开头）。运行：",
        f"  .venv/bin/python -m tools.{tool} {filename}",
        "不写 IV 和等级的，按赛季规则取 IV 排名第 1 和合法的最高等级。",
    ]


def ordered_config(raw: Any, first: Sequence[str]) -> dict[str, Any]:
    """网页的配置写成配置文件的样子：覆盖文件换成 data/custom/ 下的路径（没有时不写），first 里的键排在前面。"""
    data = _with_custom_paths(raw)
    if not data["custom_files"]:
        del data["custom_files"]
    ordered = {key: data[key] for key in first if key in data}
    return ordered | {key: value for key, value in data.items() if key not in ordered}


# ---- 手动对战（4c） ----


@lru_cache(maxsize=8)
def _prepare_from_key(key: str) -> TeamBattle:
    return prepare_team_battle(parse_team_battle_config(json.loads(key)["config"], WHERE))


def prepared_battle(raw: Any) -> TeamBattle:
    """检查配置并按赛季规则建好两队。手动对战每做一个决定都要重打，同一个配置只建一次（建配置比打一场慢得多）。

    缓存的键是配置本身和选中的覆盖文件的修改时间（config_key），所以改了覆盖文件会重新建。
    """
    return _prepare_from_key(config_key(raw))


def config_key(raw: Any) -> str:
    """缓存建好的配置用的键：网页的配置（覆盖文件换成路径）和选中的覆盖文件的修改时间，写成 JSON。"""
    converted = _with_custom_paths(raw)
    mtimes = [(REPO_ROOT / path).stat().st_mtime_ns for path in converted["custom_files"]]
    try:
        return json.dumps({"config": converted, "mtimes": mtimes}, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"{WHERE}：配置里有不能转成 JSON 的值（{e}）") from e


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


# ---- 1v1 九宫格和环境前 N（4g） ----
#
# 和命令行 tools.run_matchups 是同一套配置（matchups.py 开头）和计算：每个测试对象对每个手写的对手、
# 每组环境前 N 里的每一只，0–2 盾对 0–2 盾各打一场，双方都用简单规则策略（SimplePolicy，参数双方相同）。

MATCHUP_EXAMPLE = REPO_ROOT / "experiments" / "gl_mega_froslass_top.toml"

# SimplePolicyConfig 的参数在网页上怎么说（参数的意思见 simple_policy.py）
SIMPLE_POLICY_NAMES = {
    "charged_move_choice": "平时攒能量放哪个大招",
    "optimize_timing": "放大招前等对手的快招结束",
    "bait_shields": "骗盾：对手有盾时先放便宜的招",
    "shielding": "开盾",
    "shield_hp_fraction": "开盾的 HP 线",
}
SIMPLE_POLICY_CHOICES = {
    "charged_move_choice": {
        "best_dpe": "每点能量伤害最高的",
        "most_damage": "单发伤害最高的",
        "cheapest": "最便宜的（能放就放）",
    },
    "shielding": {
        "always": "有盾就开",
        "never": "从不开",
        "when_low": "挨这一下后剩余 HP 低于 HP 线才开（会被打倒时一定开）",
    },
}


def matchup_options() -> dict[str, Any]:
    """九宫格页的选项（联盟、赛季规则、覆盖文件用 options() 里的）：

    - policy：SimplePolicyConfig 的每个参数：key、name、default，type 是 "choice"（带 choices）/ "bool" / "number"
    - pool：环境前 N 能选什么（pool_choices）
    - shield_counts、win_rating：九宫格的盾数，评分大于 win_rating 算赢
    - example：第一次打开时用的例子配置（experiments/gl_mega_froslass_top.toml，网页的格式）
    """
    hints = get_type_hints(SimplePolicyConfig)
    policy = []
    for field in fields(SimplePolicyConfig):
        hint = hints[field.name]
        item: dict[str, Any] = {
            "key": field.name,
            "name": SIMPLE_POLICY_NAMES.get(field.name, field.name),
            "default": field.default,
        }
        if get_origin(hint) is Literal:
            names = SIMPLE_POLICY_CHOICES.get(field.name, {})
            item |= {"type": "choice", "choices": [{"key": k, "name": names.get(k, k)} for k in get_args(hint)]}
        elif hint is bool:
            item["type"] = "bool"
        else:
            item["type"] = "number"
        policy.append(item)
    return {
        "policy": policy,
        "pool": pool_choices(),
        "shield_counts": list(SHIELD_COUNTS),
        "win_rating": WIN_RATING,
        "example": example_matchups(),
    }


def pool_choices() -> dict[str, Any]:
    """环境前 N 能选的排名、Mega / 非 Mega、IV 规则（取值和说明），以及每个联盟有哪些排名文件（小联盟没有）。
    九宫格页的环境前 N 和队伍对队伍页的随机抽共用。"""

    def describe(options: dict[str, str]) -> list[dict[str, str]]:
        return [{"key": key, "name": name} for key, name in options.items()]

    return {
        "rankings": describe(RANKING_CUPS),
        "kinds": describe(POOL_KINDS),
        "ivs": describe(IV_RULES),
        "available": {cp: [cup for cup in RANKING_CUPS if rankings_path(cup, cp).exists()] for cp in LEAGUE_NAMES},
    }


def example_matchups() -> dict[str, Any]:
    """九宫格的例子配置，写成网页的格式（覆盖文件写文件名）。"""
    raw = load_toml(MATCHUP_EXAMPLE)
    raw["custom_files"] = [path.rsplit("/", 1)[-1] for path in raw.get("custom_files", [])]
    return raw


# 建好的环境前 N（rankings.prepare_pool：每只算 IV 排名，前 50 只约 1 秒）。改测试对象、手写的对手时不用重建。
_POOL_CACHE: OrderedDict[tuple[Any, ...], Pool] = OrderedDict()
_POOL_CACHE_SIZE = 32
_POOL_LOCK = threading.Lock()


def cached_pool_builder(custom_key: tuple[tuple[str, int], ...]) -> PoolBuilder:
    """带缓存的 rankings.prepare_pool（给 prepare_matchups 用）。

    缓存的键：覆盖文件（路径和修改时间，custom_key）、这一组的设置（名字除外）、联盟、赛季规则。
    只改了这一组的名字时直接用建好的，换上新名字。
    """

    def build(gm: GameMaster, spec: PoolSpec, league: int, season: SeasonRules) -> Pool:
        key = (custom_key, replace(spec, name=""), league, season)
        with _POOL_LOCK:
            pool = _POOL_CACHE.get(key)
            if pool is not None:
                _POOL_CACHE.move_to_end(key)
                return replace(pool, spec=spec)
        pool = prepare_pool(gm, spec, league, season)
        with _POOL_LOCK:
            _POOL_CACHE[key] = pool
            while len(_POOL_CACHE) > _POOL_CACHE_SIZE:
                _POOL_CACHE.popitem(last=False)
        return pool

    return build


@lru_cache(maxsize=8)
def _matchups_from_key(key: str) -> Matchups:
    data = json.loads(key)
    config = parse_matchup_config(data["config"], WHERE)
    custom_key = tuple(zip(data["config"]["custom_files"], data["mtimes"]))
    return prepare_matchups(config, cached_pool_builder(custom_key))


def prepared_matchups(raw: Any) -> Matchups:
    """检查九宫格的配置并按赛季规则建好双方（同命令行）。同一个配置只建一次：点一格看一场时不用重建。"""
    return _matchups_from_key(config_key(raw))


def _grid_payload(grid: ShieldGrid) -> dict[str, Any]:
    """一个九宫格：ratings[自己的盾数][对手的盾数]（从测试对象一方看的评分），九格里赢了几格，平均评分。"""
    return {"ratings": [list(row) for row in grid.ratings], "wins": grid.wins, "average": grid.average}


def _participant_payload(gm: GameMaster, participant: Participant) -> dict[str, Any]:
    """一只的配置（_member_info），marked 是报告里的名字（带了招式池外的招时后面加 *）。"""
    return _member_info(gm, participant) | {"marked": marked(participant)}


def matchups(raw: Any) -> dict[str, Any]:
    """跑九宫格（同命令行 tools.run_matchups）。raw 和九宫格的配置文件写法相同（覆盖文件写文件名）。

    - settings：联盟、赛季规则、策略参数、覆盖文件的记录
    - subjects、opponents：测试对象和手写的对手（_participant_payload）
    - grids[第几个测试对象][第几个手写的对手]：九宫格（_grid_payload）
    - pools：每组环境前 N：name、description（来源）、skipped（前 N 只里建不了配置、跳过的，和原因）、
      members（名次 rank、PvPoke 综合分 score，加上这一只的配置）、grids[第几个测试对象][第几个对手]、
      summary[第几个测试对象]（matchups.pool_summary：同样盾数时赢了几只、九格一共赢了几格、平均评分）
    - battles、seconds：一共打了几场、花了几秒（含建配置；环境前 N 第一次要建，之后用缓存）
    - report_markdown、csv：和命令行的报告、--csv 完全相同
    """
    start = time.perf_counter()
    prepared = prepared_matchups(raw)
    grids = run_all(prepared)
    pool_grids = run_pools(prepared)
    seconds = time.perf_counter() - start

    gm = prepared.gm
    config = prepared.config
    n_opponents = len(prepared.opponents)
    battles = len(SHIELD_COUNTS) ** 2 * len(prepared.subjects) * (
        n_opponents + sum(len(pool.members) for pool in prepared.pools)
    )
    return {
        "settings": {
            "league": config.league,
            "league_name": league_name(config.league),
            "season": config.season.name,
            "policy": asdict(config.policy),
            "custom_log": list(gm.custom_log),
        },
        "subjects": [_participant_payload(gm, p) for p in prepared.subjects],
        "opponents": [_participant_payload(gm, p) for p in prepared.opponents],
        "grids": [
            [_grid_payload(grid) for grid in grids[i * n_opponents:(i + 1) * n_opponents]]
            for i in range(len(prepared.subjects))
        ],
        "pools": [
            {
                "name": pg.pool.spec.name,
                "description": pg.pool.spec.describe(pg.pool.league),
                "skipped": [
                    {"rank": s.ranked.rank, "species": s.ranked.species_id, "name": gm.get_species(s.ranked.species_id).name,
                     "reason": s.reason}
                    for s in pg.pool.skipped
                ],
                "members": [
                    {"rank": m.ranked.rank, "score": m.ranked.score} | _participant_payload(gm, m.participant)
                    for m in pg.pool.members
                ],
                "grids": [[_grid_payload(grid) for grid in subject_grids] for subject_grids in pg.by_subject],
                "summary": [asdict(pool_summary(subject_grids)) for subject_grids in pg.by_subject],
            }
            for pg in pool_grids
        ],
        "battles": battles,
        "seconds": round(seconds, 2),
        "report_markdown": format_report(prepared, grids, pool_grids=pool_grids),
        "csv": format_csv(prepared, grids, pool_grids),
    }


def _index(raw: dict[str, Any], key: str, size: int, what: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < size:
        raise ConfigError(f"{WHERE}：{key} 要写第几个{what}（0 到 {size - 1}），得到 {value!r}")
    return value


def matchup_battle(raw: Any) -> dict[str, Any]:
    """九宫格里的一场（网页上点一格）：过程图和逐回合时间线。

    raw：{"config": 九宫格的配置（同 matchups）, "subject": 第几个测试对象, "pool": 第几组环境前 N（手写的对手写 null）,
    "opponent": 第几个对手, "shields": [测试对象的盾数, 对手的盾数]}。都从 0 数起。
    返回和打一场的结果（battle_payload）同样结构的一部分，网页用同一套画法（web/battle_view.js）：
    settings、teams（每方一只，队名就是这一只的名字）、outcome、result、chart、timeline。
    """
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, {"config", "subject", "pool", "opponent", "shields"}, WHERE)
    if "config" not in raw:
        raise ConfigError(f"{WHERE}：缺少 config")
    prepared = prepared_matchups(raw["config"])
    subject = prepared.subjects[_index(raw, "subject", len(prepared.subjects), "测试对象")]
    if raw.get("pool") is None:
        if not prepared.opponents:
            raise ConfigError(f"{WHERE}：没有手写的对手（pool 要写第几组环境前 N）")
        group = prepared.opponents
    else:
        group = prepared.pools[_index(raw, "pool", len(prepared.pools), "环境前 N")].participants
    opponent = group[_index(raw, "opponent", len(group), "对手")]
    shields = raw.get("shields")
    if not (
        isinstance(shields, list)
        and len(shields) == 2
        and all(isinstance(s, int) and not isinstance(s, bool) and s in SHIELD_COUNTS for s in shields)
    ):
        raise ConfigError(f"{WHERE}：shields 要写 [测试对象的盾数, 对手的盾数]，每个是 0、1 或 2，得到 {shields!r}")

    sides = make_sides(prepared, subject, opponent, shields[0], shields[1])
    hps = ((sides[0].active_member.stats.hp,), (sides[1].active_member.stats.hp,))
    result = fight(prepared, sides)
    names = battle_names(subject, opponent)
    gm = prepared.gm
    config = prepared.config
    return {
        "settings": {
            "league": config.league,
            "league_name": league_name(config.league),
            "season": config.season.name,
            "custom_log": list(gm.custom_log),
        },
        "teams": [
            {"name": names[side], "shields": shields[side], "names": [names[side]], "members": [_member_info(gm, p)]}
            for side, p in enumerate((subject, opponent))
        ],
        "outcome": format_1v1_outcome(names, result),
        "result": result_payload(result),
        "chart": chart_payload(gm, hps, result),
        "timeline": timeline_payload(result, ((names[0],), (names[1],))),
    }


def export_matchups(raw: Any) -> dict[str, Any]:
    """把页面上的九宫格配置写成配置文件（TOML），命令行 tools.run_matchups 能直接跑。

    先和跑九宫格一样检查、建一遍（建好的缓存起来），所以导出的文件一定能跑。返回 {"filename", "text"}。
    """
    prepared = prepared_matchups(raw)
    labels = [p.label for p in prepared.subjects]
    stem = team_library.file_name(labels[0]).removesuffix(".toml")
    filename = f"1v1_{stem}{f'_and_{len(labels) - 1}_more' if len(labels) > 1 else ''}.toml"
    data = ordered_config(raw, ("description", "custom_files", "league", "season", "policy"))
    if not data.get("policy"):
        data.pop("policy", None)
    header = export_header(" 1v1 九宫格", "matchups.py", "run_matchups", filename)
    return {"filename": filename, "text": toml_dumps(data, header)}


def import_matchups(raw: Any) -> dict[str, Any]:
    """从九宫格的配置文件（TOML 文本）导入：检查和命令行读配置文件完全相同，覆盖文件只能是 data/custom/ 里的。

    raw：{"text": 文件内容, "name": 文件名（可选）}。返回 {"config": 网页的配置（同 example_matchups 的写法）}。
    """
    data, where = read_imported_file(raw)
    parse_matchup_config(data, where)
    return {"config": data | {"custom_files": imported_custom_names(data, where)}}


# ---- 队伍对队伍（4h） ----
#
# 和命令行 tools.run_team_matrix 是同一套配置（team_matrix.py 开头）和计算：我方每一队对每一队对手（手写的，以及从
# 环境前 N 随机抽的）各打一场 3v3。场数多时要打十几秒，所以边打边给出进度（team_matrix_stream；服务器把每一项
# 写成 NDJSON 的一行发出去，网页一边收一边显示）。

MATRIX_EXAMPLE = REPO_ROOT / "experiments" / "gl_team_matrix_example.toml"
MATRIX_PROGRESS_SECONDS = 0.2  # 边打边发进度：每隔这么久发一批打完的结果

# 网页上打开"随机抽"时先填的值（同例子配置）
SAMPLE_DEFAULTS = {
    "rankings": "mega",
    "top": 30,
    "mega_top": 10,
    "count": 50,
    "seed": 1,
    "ivs": "rank1",
    "shields": PVPOKE_COMPAT.max_shields,
}


def matrix_options() -> dict[str, Any]:
    """队伍对队伍页的选项（联盟、赛季规则、覆盖文件、盾数、主动换人用 options() 里的）：

    - pool：随机抽能选什么（pool_choices）
    - sample_defaults：打开"随机抽"时先填的值
    - example：第一次打开时用的例子配置（experiments/gl_team_matrix_example.toml，网页的格式）
    """
    return {"pool": pool_choices(), "sample_defaults": dict(SAMPLE_DEFAULTS), "example": example_matrix()}


def example_matrix() -> dict[str, Any]:
    """队伍对队伍的例子配置，写成网页的格式（覆盖文件写文件名）。"""
    raw = load_toml(MATRIX_EXAMPLE)
    raw["custom_files"] = [path.rsplit("/", 1)[-1] for path in raw.get("custom_files", [])]
    return raw


@lru_cache(maxsize=4)
def _matrix_from_key(key: str) -> team_matrix.TeamMatrix:
    data = json.loads(key)
    config = team_matrix.parse_team_matrix_config(data["config"], WHERE)
    custom_key = tuple(zip(data["config"]["custom_files"], data["mtimes"]))
    return team_matrix.prepare_team_matrix(config, cached_pool_builder(custom_key))


def prepared_matrix(raw: Any) -> team_matrix.TeamMatrix:
    """检查队伍对队伍的配置，建好每一队、抽好样（同命令行）。同一个配置只建一次：点一场看时不用重建。

    抽样的候选（环境前 N）用九宫格同一个缓存（cached_pool_builder）。
    """
    return _matrix_from_key(config_key(raw))


def _matrix_team_payload(gm: GameMaster, team: team_matrix.MatrixTeam) -> dict[str, Any]:
    """一队：名字、哪一组（我方 / 手写 / 抽样）、盾数、策略、每只的配置（_member_info），
    member_names 是报告里的名字（抽样的带排名里的名次，例如 "Altaria #3"）。"""
    return {
        "name": team.name,
        "group": team.group,
        "shields": team.setup.shields,
        "policy": policy_text(team.setup.policy),
        "member_names": team.member_names(),
        "ranks": list(team.ranks),
        "members": [_member_info(gm, p) for p in team.members],
    }


def _sample_payload(matrix: team_matrix.TeamMatrix) -> dict[str, Any] | None:
    """随机抽的说明（同报告）、候选（每组环境前 N 的名次、综合分、名字）、建不了配置不参加抽样的。"""
    sample = matrix.sample
    if sample is None:
        return None
    spec = sample.spec
    gm = matrix.gm
    return {
        "description": spec.describe(matrix.config.league, matrix.config.rules.max_team_size),
        "shields": spec.shields,
        "policy": policy_text(spec.policy),
        "candidates": [
            {
                "name": pool.spec.name,
                "members": [{"rank": m.ranked.rank, "score": m.ranked.score, "label": m.participant.label} for m in pool.members],
                "skipped": [
                    {"rank": s.ranked.rank, "name": gm.get_species(s.ranked.species_id).name, "reason": s.reason}
                    for s in pool.skipped
                ],
            }
            for pool in sample.pools
        ],
    }


def matrix_result_payload(result: BattleResult) -> dict[str, Any]:
    """一场的结果，从我方看：outcome 是"赢" / "平" / "输"（team_matrix.outcome），其余同 result_payload。"""
    return {"outcome": team_matrix.outcome(result)} | result_payload(result)


def matrix_summary(
    matrix: team_matrix.TeamMatrix, results: Sequence[Sequence[BattleResult]]
) -> list[dict[str, Any]]:
    """总表（同报告）：我方每一队对每组对手（手写 / 抽样 / 全部）的场数、赢、平、输、平均评分、平均剩余只数。"""
    return [
        {"team": i, "group": group} | asdict(team_matrix.tally([row[j] for j in indices]))
        for i, row in enumerate(results)
        for group, indices in team_matrix.opponent_groups(matrix)
    ]


def team_matrix_stream(raw: Any) -> Iterator[dict[str, Any]]:
    """队伍对队伍，边打边给出进度（服务器把每一项写成 NDJSON 的一行）。raw 和配置文件写法相同（覆盖文件写文件名）。

    先检查、建好每一队、抽好样：写错时这里就抛出 ConfigError（服务器回 400，还没开始发）。然后返回一个迭代器，依次给出：
    - {"type": "start", "total": 一共几场, "settings", "teams", "opponents"（_matrix_team_payload；手写的在前、抽样的在后）,
      "sample"（_sample_payload，没有随机抽时为 None）}
    - {"type": "progress", "done": 打完了几场, "results": [{"team", "opponent", 这一场的结果（matrix_result_payload）}, ...]}：
      按打的顺序（先按我方，再按对手），每隔 MATRIX_PROGRESS_SECONDS 秒一批
    - {"type": "done", "seconds", "summary"（matrix_summary）, "report_markdown", "csv"}：和命令行的报告、--csv 完全相同
    网页点"停止"就断开请求：服务器不再往下取，也就不再打（team_matrix.iter_team_matrix）。
    """
    start = time.perf_counter()
    matrix = prepared_matrix(raw)
    return _matrix_events(matrix, start)


def _matrix_events(matrix: team_matrix.TeamMatrix, start: float) -> Iterator[dict[str, Any]]:
    gm = matrix.gm
    config = matrix.config
    yield {
        "type": "start",
        "total": len(matrix.teams) * len(matrix.opponents),
        "settings": {
            "league": config.league,
            "league_name": league_name(config.league),
            "season": config.season.name,
            "custom_log": list(gm.custom_log),
        },
        "teams": [_matrix_team_payload(gm, team) for team in matrix.teams],
        "opponents": [_matrix_team_payload(gm, team) for team in matrix.opponents],
        "sample": _sample_payload(matrix),
    }
    results: list[list[BattleResult | None]] = [[None] * len(matrix.opponents) for _ in matrix.teams]
    batch: list[dict[str, Any]] = []
    done = 0
    last = time.perf_counter()
    for i, j, result in team_matrix.iter_team_matrix(matrix):
        results[i][j] = result
        done += 1
        batch.append({"team": i, "opponent": j} | matrix_result_payload(result))
        now = time.perf_counter()
        if now - last >= MATRIX_PROGRESS_SECONDS:
            yield {"type": "progress", "done": done, "results": batch}
            batch = []
            last = now
    if batch:
        yield {"type": "progress", "done": done, "results": batch}
    finished = [[result for result in row if result is not None] for row in results]  # 到这里每一场都打完了
    yield {
        "type": "done",
        "seconds": round(time.perf_counter() - start, 2),
        "summary": matrix_summary(matrix, finished),
        "report_markdown": team_matrix.format_report(matrix, finished),
        "csv": team_matrix.format_csv(matrix, finished),
    }


def _matrix_pair(raw: Any) -> tuple[team_matrix.TeamMatrix, team_matrix.MatrixTeam, team_matrix.MatrixTeam]:
    """{"config", "team": 我方第几队, "opponent": 对手第几队}（从 0 数起；对手手写的在前、抽样的在后）。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"{WHERE}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, {"config", "team", "opponent"}, WHERE)
    if "config" not in raw:
        raise ConfigError(f"{WHERE}：缺少 config")
    matrix = prepared_matrix(raw["config"])
    team = matrix.teams[_index(raw, "team", len(matrix.teams), "我方队伍")]
    opponent = matrix.opponents[_index(raw, "opponent", len(matrix.opponents), "对手队伍")]
    return matrix, team, opponent


def matrix_battle(raw: Any) -> dict[str, Any]:
    """队伍对队伍里的一场（网页上点一场）：和打一场的结果完全相同的结构（battle_payload），含完整的 Markdown 报告。

    raw 见 _matrix_pair。和命令行 tools.run_team_matrix --battle 打的是同一场。
    """
    matrix, team, opponent = _matrix_pair(raw)
    battle = team_matrix.pairing(matrix, team, opponent)
    return battle_payload(battle, run_team_battle(battle))


def matrix_pairing_config(raw: Any) -> dict[str, Any]:
    """队伍对队伍里的一场写成"打一场"页的配置（网页的"在打一场页打开"）。raw 见 _matrix_pair。

    返回 {"config": 3v3 配置（同 example_config 的写法）, "warnings": [...]}。每队写成 [[team]] 的样子：
    队名、盾数、switching、3 只（config.entry_table；随机抽的队伍也一样，打出来和这里同一场）。
    "打一场"页只能改盾数和 switching，其余和默认不同的策略参数写进 warnings。
    """
    matrix, team, opponent = _matrix_pair(raw)
    settings = raw["config"]
    default = TeamPolicyConfig()
    teams = []
    warnings = []
    for t in (team, opponent):
        setup = t.setup
        if replace(setup.policy, switching=default.switching) != default:
            warnings.append(f"{setup.name} 的策略参数“打一场”页上改不了（只能改盾数和主动换不换人），没有带过去")
        teams.append({
            "name": setup.name,
            "shields": setup.shields,
            "policy": {"switching": setup.policy.switching},
            "member": [entry_table(entry) for entry in setup.members],
        })
    config = {
        "league": matrix.config.league,
        "season": settings["season"],
        "custom_files": list(settings.get("custom_files", [])),
        "team": teams,
    }
    return {"config": config, "warnings": warnings}


def export_matrix(raw: Any) -> dict[str, Any]:
    """把页面上的队伍对队伍配置写成配置文件（TOML），命令行 tools.run_team_matrix 能直接跑。

    先和跑的时候一样检查、建一遍（建好的缓存起来），所以导出的文件一定能跑。返回 {"filename", "text"}。
    """
    matrix = prepared_matrix(raw)
    names = [team.name for team in matrix.teams]
    stem = team_library.file_name(names[0]).removesuffix(".toml")
    filename = f"matrix_{stem}{f'_and_{len(names) - 1}_more' if len(names) > 1 else ''}.toml"
    data = ordered_config(raw, ("description", "custom_files", "league", "season"))
    header = export_header("队伍对队伍", "team_matrix.py", "run_team_matrix", filename)
    return {"filename": filename, "text": toml_dumps(data, header)}


def import_matrix(raw: Any) -> dict[str, Any]:
    """从队伍对队伍的配置文件（TOML 文本）导入：检查和命令行读配置文件完全相同，覆盖文件只能是 data/custom/ 里的。

    raw：{"text": 文件内容, "name": 文件名（可选）}。网页上每队（包括随机抽的队伍）只能改盾数和 switching：
    共用的 [policy] 里的 switching 合并到每一队，其余的策略参数和 [rules] 不导入，写在 warnings 里。
    返回 {"config": 网页的配置（同 example_matrix 的写法）, "warnings": [...]}。
    """
    data, where = read_imported_file(raw)
    team_matrix.parse_team_matrix_config(data, where)
    names = imported_custom_names(data, where)

    shared_policy = data.get("policy", {})
    warnings = []
    if data.get("rules"):
        warnings.append(rules_warning(data["rules"]))
    config = {key: value for key, value in data.items() if key not in ("rules", "policy")}
    config["custom_files"] = names
    for key in ("team", "opponent_team"):
        if key not in data:
            continue
        for team in data[key]:
            unsupported = team_unsupported(team, shared_policy)
            if unsupported:
                warnings.append(policy_warning(team["name"], unsupported))
        config[key] = [_page_team(team, shared_policy) for team in data[key]]
    if "opponent_sample" in data:
        sample = data["opponent_sample"]
        unsupported = team_unsupported(sample, shared_policy)
        if unsupported:
            warnings.append(policy_warning("随机抽的队伍", unsupported))
        config["opponent_sample"] = _page_team(sample, shared_policy)
    return {"config": config, "warnings": warnings}

