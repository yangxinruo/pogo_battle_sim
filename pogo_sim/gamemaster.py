"""读取 PvPoke 的 gamemaster.json，转成本项目的数据结构。

数据来源和版本见 data/SOURCE.md。这里只读取、不修改原始数据；
自定义宝可梦和技能以后放在单独的覆盖文件里。

字段含义参考 PvPoke src/js/GameMaster.js 的 getMoveById 和
src/js/pokemon/Pokemon.js 的构造函数。
"""

import json
from dataclasses import dataclass
from pathlib import Path

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
    )


def load_gamemaster(path: Path = DEFAULT_GAMEMASTER_PATH) -> GameMaster:
    """读取 gamemaster.json。"""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    moves = {m["moveId"]: _parse_move(m) for m in raw["moves"]}
    species = {p["speciesId"]: _parse_species(p) for p in raw["pokemon"]}

    return GameMaster(species=species, moves=moves, timestamp=raw["timestamp"])
