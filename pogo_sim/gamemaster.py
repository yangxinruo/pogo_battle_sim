"""读取 PvPoke 的 gamemaster.json，转成本项目的数据结构。

数据来源和版本见 data/SOURCE.md。这里只读取、不修改原始文件；
自定义宝可梦和技能放在单独的覆盖文件里（见 custom.py），读入后在内存里合并。

字段含义参考 PvPoke src/js/GameMaster.js 的 getMoveById 和
src/js/pokemon/Pokemon.js 的构造函数。
"""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pogo_sim.conversion import MEGA_NERF, STANDARD_NERF, NerfRule
from pogo_sim.cpm import MIN_LEVEL
from pogo_sim.custom import CustomDataError, RawEntry, apply_custom_file
from pogo_sim.stats import BaseStats, IVs

DEFAULT_GAMEMASTER_PATH: Path = (
    Path(__file__).resolve().parent.parent / "data" / "gamemaster.json"
)

# gamemaster 里用 "none" 表示没有第二属性。
NO_TYPE: str = "none"


@dataclass(frozen=True)
class StatChange:
    """一次能力等级变化：攻击和防御各变化多少级（可为负）。"""

    atk: int
    def_: int


@dataclass(frozen=True)
class MoveEffect:
    """招式附带的能力变化效果。

    chance 是触发概率（0 到 1）。
    on_self / on_opponent 分别是对使用者和对对手的变化，没有则为 None。
    """

    chance: float
    on_self: StatChange | None
    on_opponent: StatChange | None


@dataclass(frozen=True)
class Move:
    """一个招式（快速技能或大招）。

    快速技能：energy_gain > 0，turns 是持续回合数（1 回合 = 0.5 秒）。
    大招：energy_cost > 0，没有时长。
    """

    move_id: str
    name: str
    type: str
    power: float
    energy_cost: int
    energy_gain: int
    turns: int
    is_fast: bool
    effect: MoveEffect | None
    is_mega_move: bool
    damage_method: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class DefaultSpread:
    """PvPoke 给某个联盟预设的等级和 IV。"""

    level: float
    ivs: IVs


@dataclass(frozen=True)
class Species:
    """一种宝可梦（含形态，如暗影、Mega 都是单独的条目）。"""

    species_id: str
    name: str
    dex: int
    base_stats: BaseStats
    types: tuple[str, ...]
    fast_move_ids: tuple[str, ...]
    charged_move_ids: tuple[str, ...]
    extra_charged_move_ids: tuple[str, ...]
    tags: tuple[str, ...]
    released: bool
    default_spreads: dict[int, DefaultSpread]
    # gamemaster 的 levelFloor：能获得的最低等级（如只能从调查或 Raid 获得，最低 15 或 20 级），
    # 没写的是 1。PvPoke 在 IV 排名时不考虑低于这个等级的情况（见 iv_ranking.py）。
    level_floor: float

    @property
    def is_shadow(self) -> bool:
        return "shadow" in self.tags

    @property
    def is_mega(self) -> bool:
        return "mega" in self.tags


@dataclass(frozen=True)
class GameMaster:
    """全部宝可梦和招式，按 id 索引。"""

    species: dict[str, Species]
    moves: dict[str, Move]
    timestamp: str
    # 覆盖文件做了哪些改动，每条一行（没有加载覆盖文件时为空）。见 custom.py。
    custom_log: tuple[str, ...] = ()

    def get_species(self, species_id: str) -> Species:
        if species_id not in self.species:
            raise KeyError(f"找不到宝可梦：{species_id}")
        return self.species[species_id]

    def get_move(self, move_id: str) -> Move:
        if move_id not in self.moves:
            raise KeyError(f"找不到招式：{move_id}")
        return self.moves[move_id]


def _parse_effect(raw: dict) -> MoveEffect | None:
    """解析招式的能力变化。

    gamemaster 的写法：
      buffs: [攻击变化, 防御变化]
      buffTarget: "self" / "opponent" / "both"
      buffApplyChance: 字符串形式的概率，如 "1"、".125"
      buffTarget 为 "both" 时，另有 buffsSelf 和 buffsOpponent 分别给出两边的变化。
    """
    if "buffs" not in raw:
        return None

    target = raw["buffTarget"]
    chance = float(raw["buffApplyChance"])

    if target == "self":
        on_self = StatChange(*raw["buffs"])
        on_opponent = None
    elif target == "opponent":
        on_self = None
        on_opponent = StatChange(*raw["buffs"])
    elif target == "both":
        on_self = StatChange(*raw["buffsSelf"])
        on_opponent = StatChange(*raw["buffsOpponent"])
    else:
        raise ValueError(f"招式 {raw['moveId']} 的 buffTarget 不认识：{target}")

    return MoveEffect(chance=chance, on_self=on_self, on_opponent=on_opponent)


def _parse_move(raw: dict) -> Move:
    # PvPoke 的规则：energyGain > 0 就是快速技能，除非数据里显式写了 category。
    if "category" in raw:
        is_fast = raw["category"] == "fast"
    else:
        is_fast = raw["energyGain"] > 0

    return Move(
        move_id=raw["moveId"],
        name=raw["name"],
        type=raw["type"],
        power=raw["power"],
        energy_cost=raw["energy"],
        energy_gain=raw["energyGain"],
        turns=raw["turns"],
        is_fast=is_fast,
        effect=_parse_effect(raw),
        is_mega_move=raw.get("isMegaMove", False),
        damage_method=raw.get("damageMethod", "default"),
        tags=tuple(raw.get("tags", [])),
    )


def _parse_default_spreads(raw: dict) -> dict[int, DefaultSpread]:
    """解析 defaultIVs。只取 "cp500" / "cp1500" / "cp2500" 这类键，键转成 CP 上限。

    "cp1500l40" 这类"等级上限 40 时的预设"暂时不读。
    """
    spreads: dict[int, DefaultSpread] = {}
    for key, value in raw.items():
        cp_text = key.removeprefix("cp")
        if not cp_text.isdigit():
            continue
        level, atk_iv, def_iv, hp_iv = value
        spreads[int(cp_text)] = DefaultSpread(
            level=float(level), ivs=IVs(atk=atk_iv, def_=def_iv, hp=hp_iv)
        )
    return spreads


def _parse_species(raw: dict) -> Species:
    stats = raw["baseStats"]
    types = tuple(t for t in raw["types"] if t != NO_TYPE)

    return Species(
        species_id=raw["speciesId"],
        name=raw["speciesName"],
        dex=raw["dex"],
        base_stats=BaseStats(atk=stats["atk"], def_=stats["def"], hp=stats["hp"]),
        types=types,
        fast_move_ids=tuple(raw["fastMoves"]),
        charged_move_ids=tuple(raw["chargedMoves"]),
        extra_charged_move_ids=tuple(raw.get("extraChargedMoves", [])),
        tags=tuple(raw.get("tags", [])),
        released=raw.get("released", False),
        default_spreads=_parse_default_spreads(raw.get("defaultIVs", {})),
        level_floor=float(raw.get("levelFloor", MIN_LEVEL)),
    )


def load_gamemaster(
    path: Path = DEFAULT_GAMEMASTER_PATH,
    custom_files: Sequence[Path | str] = (),
    standard_nerf: NerfRule = STANDARD_NERF,
    mega_nerf: NerfRule = MEGA_NERF,
) -> GameMaster:
    """读取 gamemaster.json，再按顺序应用覆盖文件。

    custom_files：覆盖文件路径（TOML，格式见 custom.py）。后面的文件可以修改前面文件新加的条目。
    standard_nerf / mega_nerf：覆盖文件里用 mainSeriesStats 写的宝可梦，换算时用的削弱规则。
    改动记录在返回值的 custom_log 里。
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    raw_moves: dict[str, RawEntry] = {m["moveId"]: m for m in raw["moves"]}
    raw_species: dict[str, RawEntry] = {p["speciesId"]: p for p in raw["pokemon"]}

    custom_log: list[str] = []
    custom_species_ids: set[str] = set()
    for custom_path in custom_files:
        result = apply_custom_file(
            Path(custom_path), raw_species, raw_moves, standard_nerf, mega_nerf
        )
        custom_log.extend(result.log)
        custom_species_ids |= result.species_ids

    moves = {move_id: _parse_entry(_parse_move, entry) for move_id, entry in raw_moves.items()}
    species = {
        species_id: _parse_entry(_parse_species, entry)
        for species_id, entry in raw_species.items()
    }
    for species_id in sorted(custom_species_ids):
        _check_move_references(species[species_id], moves)

    return GameMaster(
        species=species,
        moves=moves,
        timestamp=raw["timestamp"],
        custom_log=tuple(custom_log),
    )


T = TypeVar("T")


def _parse_entry(parse: Callable[[dict], T], entry: RawEntry) -> T:
    """解析一个条目；出错时在信息里写明是哪个条目（主要为了覆盖文件写错时好找）。"""
    try:
        return parse(entry)
    except (KeyError, TypeError, ValueError) as error:
        entry_id = entry.get("speciesId", entry.get("moveId"))
        raise CustomDataError(f"解析 {entry_id} 出错：{error!r}") from error


def _check_move_references(species: Species, moves: dict[str, Move]) -> None:
    """覆盖文件里新增或修改过的宝可梦：招式都要存在，快招列表里要是快招，大招列表里要是大招。

    gamemaster 原有的条目不检查（有两个已知的原始数据特例，见 tests/test_gamemaster.py）。
    """
    for move_id in species.fast_move_ids + species.charged_move_ids + species.extra_charged_move_ids:
        if move_id not in moves:
            raise CustomDataError(f"{species.species_id} 引用了不存在的招式 {move_id}")
    for move_id in species.fast_move_ids:
        if not moves[move_id].is_fast:
            raise CustomDataError(f"{species.species_id} 的 fastMoves 里 {move_id} 不是快速技能")
    for move_id in species.charged_move_ids + species.extra_charged_move_ids:
        if moves[move_id].is_fast:
            raise CustomDataError(f"{species.species_id} 的大招列表里 {move_id} 是快速技能")
