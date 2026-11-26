"""PvPoke 的排名（data/rankings/，来源和 SHA-256 见 data/SOURCE.md）：取环境前 N 只做对手。

PvPoke 的排名是 1v1 的综合排名（overall），每只带一套推荐配招（moveset：快招 + 大招，Mega 可能有第三个大招）。
本项目只用名次、种类和推荐配招；对战结果都由本项目的引擎重新算。

两套排名（cup）：
- "all"：普通联盟，不含 Mega；
- "mega"：Mega 版联盟，Mega 和非 Mega 一起排。

环境前 N（PoolSpec，配置里写成 [[opponent_pool]]）：
- Mega 和非 Mega 分开取（docs/mechanics.md 13.2 D5）：有 Mega 的规则下排名前列多是 Mega，但每队只能带一只。
  "前 N"是在这一类里按排名顺序数的前 N 只；报告里的名次是排名文件里的名次（两类一起排）。
- IV 和等级（用户 2026-11-21 选定）：默认 IV 排名第 1，等级按赛季规则定，和配置文件里不写 IV 时一样
  （config.prepare_entry → season.season_build）。可以改成 PvPoke 默认 IV（gamemaster 的 defaultIVs，
  大师联盟 50 级 15/15/15；combatant.league_build），方便和 PvPoke 对照；这时等级照 PvPoke，不跟赛季规则走
  （CP 超过上限的 Mega 仍按赛季规则自动降等级）。
- 前 N 名里建不了配置的（例如这个赛季规则下没有合法的等级），跳过，并在报告里写明原因。
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pogo_sim.combatant import league_build
from pogo_sim.config import (
    REPO_ROOT,
    ConfigError,
    Entry,
    Participant,
    check_unknown_keys,
    error_message,
    format_table,
    prepare_entry,
)
from pogo_sim.gamemaster import GameMaster
from pogo_sim.moveset import Moveset
from pogo_sim.season import SeasonRules, league_name
from pogo_sim.stats import calculate_cp

RANKINGS_DIR: Path = REPO_ROOT / "data" / "rankings"

RANKING_CUPS: dict[str, str] = {
    "all": "普通联盟，不含 Mega",
    "mega": "Mega 版，Mega 和非 Mega 一起排",
}
POOL_KINDS: dict[str, str] = {"mega": "Mega", "non_mega": "非 Mega"}
IV_RULES: dict[str, str] = {
    "rank1": "IV 排名第 1，等级按赛季规则（和配置文件不写 IV 时一样）",
    "pvpoke_default": "PvPoke 默认 IV（gamemaster 的 defaultIVs；大师联盟 50 级 15/15/15）",
}

POOL_KEYS = frozenset({"name", "rankings", "kind", "top", "ivs"})


# ---- 排名文件 ----


@dataclass(frozen=True)
class RankedPokemon:
    """排名里的一只。"""

    rank: int  # 在排名文件里的名次，从 1 开始（"mega" 排名里 Mega 和非 Mega 一起排）
    species_id: str
    moveset: Moveset  # PvPoke 的推荐配招
    score: float  # PvPoke 的综合分（0–100）


def rankings_path(cup: str, league: int) -> Path:
    return RANKINGS_DIR / cup / "overall" / f"rankings-{league}.json"


@cache
def load_rankings(cup: str, league: int) -> tuple[RankedPokemon, ...]:
    """读一个排名文件，按名次排好。没有这个排名时抛出 ValueError。"""
    if cup not in RANKING_CUPS:
        raise ValueError(f"不认识的排名 {cup!r}（可用：{', '.join(RANKING_CUPS)}）")
    path = rankings_path(cup, league)
    if not path.exists():
        raise ValueError(f"没有{league_name(league)}的 {cup} 排名（{path.relative_to(REPO_ROOT)}）")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        RankedPokemon(
            rank=i + 1,
            species_id=item["speciesId"],
            moveset=Moveset(item["moveset"][0], tuple(item["moveset"][1:])),
            score=float(item["score"]),
        )
        for i, item in enumerate(raw)
    )


def top_ranked(gm: GameMaster, cup: str, league: int, kind: str, top: int) -> tuple[RankedPokemon, ...]:
    """排名里这一类（Mega / 非 Mega）的前 top 只，按名次。"""
    if kind not in POOL_KINDS:
        raise ValueError(f"不认识的类别 {kind!r}（可用：{', '.join(POOL_KINDS)}）")
    selected = []
    for ranked in load_rankings(cup, league):
        try:
            species = gm.get_species(ranked.species_id)
        except KeyError as e:
            raise ValueError(
                f"{cup} 排名里的 {ranked.species_id} 在 gamemaster 里找不到"
                "（排名和 gamemaster 要用同一个 PvPoke commit，见 data/SOURCE.md）"
            ) from e
        if species.is_mega == (kind == "mega"):
            selected.append(ranked)
            if len(selected) == top:
                break
    return tuple(selected)


# ---- 环境前 N ----


@dataclass(frozen=True)
class PoolSpec:
    """配置里的一组环境前 N：从哪个排名取、Mega 还是非 Mega、前几只、IV 怎么定。"""

    name: str  # 报告里的名字
    rankings: str  # RANKING_CUPS 的键
    kind: str  # POOL_KINDS 的键
    top: int
    ivs: str = "rank1"  # IV_RULES 的键

    def describe(self, league: int) -> str:
        """例如"PvPoke 的 mega 排名（Mega 版，…），超级联盟，非 Mega 前 50 只；IV 排名第 1，…"。"""
        return (
            f"PvPoke 的 {self.rankings} 排名（{RANKING_CUPS[self.rankings]}），{league_name(league)}，"
            f"{POOL_KINDS[self.kind]} 前 {self.top} 只；{IV_RULES[self.ivs]}"
        )


def parse_pool_spec(raw: Any, where: str) -> PoolSpec:
    """配置里的一个 [[opponent_pool]] 表。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}：要写成表，得到 {raw!r}")
    check_unknown_keys(raw, POOL_KEYS, where)
    for key in ("rankings", "kind", "top"):
        if key not in raw:
            raise ConfigError(f"{where}：缺少 {key}")

    def choice(key: str, options: dict[str, str]) -> str:
        value = raw[key]
        if not isinstance(value, str) or value not in options:
            raise ConfigError(f"{where}：{key} 要写 {' / '.join(repr(o) for o in options)}，得到 {value!r}")
        return value

    rankings = choice("rankings", RANKING_CUPS)
    kind = choice("kind", POOL_KINDS)
    ivs = choice("ivs", IV_RULES) if "ivs" in raw else "rank1"
    top = raw["top"]
    if not isinstance(top, int) or isinstance(top, bool) or top <= 0:
        raise ConfigError(f"{where}：top 要写正整数，得到 {top!r}")
    name = raw.get("name", f"{POOL_KINDS[kind]} 前 {top}（{rankings} 排名）")
    if not isinstance(name, str) or not name:
        raise ConfigError(f"{where}：name 要写非空的字符串，得到 {name!r}")
    return PoolSpec(name=name, rankings=rankings, kind=kind, top=top, ivs=ivs)


@dataclass(frozen=True)
class PoolMember:
    ranked: RankedPokemon
    participant: Participant  # label 是宝可梦名


@dataclass(frozen=True)
class Skipped:
    """前 N 名里建不了配置的一只。"""

    ranked: RankedPokemon
    reason: str


@dataclass(frozen=True)
class Pool:
    """按赛季规则建好配置的环境前 N。"""

    spec: PoolSpec
    league: int
    members: tuple[PoolMember, ...]
    skipped: tuple[Skipped, ...]

    @property
    def participants(self) -> tuple[Participant, ...]:
        return tuple(m.participant for m in self.members)


def ranked_entry(gm: GameMaster, ranked: RankedPokemon, league: int, ivs: str) -> Entry:
    """排名里的一只写成配置（Entry）。ivs 是 IV_RULES 的键。"""
    if ivs == "rank1":
        return Entry(label=None, species_id=ranked.species_id, moveset=ranked.moveset)
    if ivs == "pvpoke_default":
        build = league_build(gm, ranked.species_id, league, ranked.moveset.fast, ranked.moveset.charged)
        return Entry(
            label=None, species_id=ranked.species_id, moveset=ranked.moveset, ivs=build.ivs, level=build.level
        )
    raise ValueError(f"不认识的 IV 规则 {ivs!r}（可用：{', '.join(IV_RULES)}）")


def prepare_pool(gm: GameMaster, spec: PoolSpec, league: int, season: SeasonRules) -> Pool:
    """取排名里的前 N 只，按赛季规则建配置。建不了的跳过，记下原因。"""
    members = []
    skipped = []
    for ranked in top_ranked(gm, spec.rankings, league, spec.kind, spec.top):
        try:
            entry = ranked_entry(gm, ranked, league, spec.ivs)
            participant = prepare_entry(gm, entry, league, season)
        except (KeyError, ValueError) as e:
            skipped.append(Skipped(ranked, error_message(e)))
            continue
        members.append(PoolMember(ranked, participant))
    return Pool(spec, league, tuple(members), tuple(skipped))



# 建一组环境前 N 的函数（默认 prepare_pool）。九宫格和队伍对队伍的抽样都可以换成别的，
# 例如网页换成带缓存的（web_api.cached_pool_builder：建环境前 N 比打对战慢得多）。
PoolBuilder = Callable[[GameMaster, PoolSpec, int, SeasonRules], Pool]

# ---- 报告 ----


def format_pool_members(gm: GameMaster, pool: Pool) -> str:
    """环境前 N 的每一只：名次、PvPoke 的分、CP、等级、IV、配招（Markdown 表格）。"""
    header = ["名次", "宝可梦", "PvPoke 分", "CP", "等级", "IV", "配招"]
    rows = []
    for member in pool.members:
        build = member.participant.build
        species = gm.get_species(build.species_id)
        ivs = build.ivs
        rows.append([
            str(member.ranked.rank),
            member.participant.label,
            f"{member.ranked.score:g}",
            str(calculate_cp(species.base_stats, ivs, build.level)),
            f"{build.level:g}",
            f"{ivs.atk}/{ivs.def_}/{ivs.hp}",
            Moveset(build.fast_move_id, build.charged_move_ids).describe(),
        ])
    return format_table(header, rows)


def format_skipped(skipped: Sequence[Skipped]) -> list[str]:
    """跳过的几只，每只一行（Markdown 列表）；没有时为空。"""
    return [f"- 第 {s.ranked.rank} 名 {s.ranked.species_id}：{s.reason}" for s in skipped]
