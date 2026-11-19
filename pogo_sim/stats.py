"""CP、HP 和实际攻防的计算。

公式来源：PvPoke src/js/pokemon/Pokemon.js 的 initialize 和 calculateCP，
对应 docs/mechanics.md 第 2 节。
"""

from dataclasses import dataclass
from math import floor, sqrt

from pogo_sim.cpm import LEVEL_STEP, MIN_LEVEL, get_cpm, is_valid_level

# CP 的最小值。来源：PvPoke Pokemon.initialize。验证状态：参考 PvPoke。
MIN_CP: int = 10

# HP 的最小值。来源：PvPoke Pokemon.initialize。验证状态：参考 PvPoke。
MIN_HP: int = 10

MIN_IV: int = 0
MAX_IV: int = 15


@dataclass(frozen=True)
class BaseStats:
    """GO 里的种族值（不含 IV 和等级）。"""

    atk: int
    def_: int
    hp: int


@dataclass(frozen=True)
class IVs:
    """个体值，每项 0 到 15。"""

    atk: int
    def_: int
    hp: int

    def __post_init__(self) -> None:
        for name, value in (("atk", self.atk), ("def_", self.def_), ("hp", self.hp)):
            if not MIN_IV <= value <= MAX_IV:
                raise ValueError(f"IV {name}={value} 超出范围 {MIN_IV}–{MAX_IV}")


@dataclass(frozen=True)
class BattleStats:
    """对战中实际使用的能力值。

    攻击和防御保留小数（PvPoke 不取整，这会影响伤害的断点），HP 是整数。
    """

    atk: float
    def_: float
    hp: int


def calculate_cp(base: BaseStats, ivs: IVs, level: float) -> int:
    """计算 CP。

    CP = floor((攻+IV) × sqrt(防+IV) × sqrt(HP+IV) × CPM² / 10)，最低 10。
    验证状态：已验证（见 tests/test_stats.py）。
    """
    cpm = get_cpm(level)
    atk = base.atk + ivs.atk
    def_ = base.def_ + ivs.def_
    hp = base.hp + ivs.hp
    cp = floor(atk * sqrt(def_) * sqrt(hp) * cpm**2 / 10)
    return max(cp, MIN_CP)


def calculate_battle_stats(base: BaseStats, ivs: IVs, level: float) -> BattleStats:
    """计算某个等级和 IV 下的实际攻击、防御和 HP。

    攻击 = CPM × (种族攻击 + IV)，不取整
    防御 = CPM × (种族防御 + IV)，不取整
    HP   = floor(CPM × (种族HP + IV))，最低 10
    验证状态：参考 PvPoke。
    """
    cpm = get_cpm(level)
    atk = cpm * (base.atk + ivs.atk)
    def_ = cpm * (base.def_ + ivs.def_)
    hp = max(floor(cpm * (base.hp + ivs.hp)), MIN_HP)
    return BattleStats(atk=atk, def_=def_, hp=hp)


def highest_level_under_cp(
    base: BaseStats,
    ivs: IVs,
    cp_limit: int,
    level_cap: float = 50.0,
    level_floor: float = MIN_LEVEL,
) -> float | None:
    """给定 IV，返回 CP 不超过上限的最高等级（步长 0.5，在 level_floor 到 level_cap 之间）。

    如果在 level_floor 就已经超过上限，返回 None。
    CPM 随等级严格增大，所以 CP 随等级单调不减，可以用二分查找。
    """
    if not (is_valid_level(level_floor) and is_valid_level(level_cap)):
        raise ValueError(f"不合法的等级范围：{level_floor} 到 {level_cap}")
    if level_floor > level_cap:
        raise ValueError(f"最低等级 {level_floor} 高于等级上限 {level_cap}")

    def level_at(step: int) -> float:
        return level_floor + step * LEVEL_STEP

    def fits(step: int) -> bool:
        return calculate_cp(base, ivs, level_at(step)) <= cp_limit

    if not fits(0):
        return None

    # 二分查找最后一个合法的格子。不变式：low 合法；high 之后的都不合法。
    low = 0
    high = round((level_cap - level_floor) / LEVEL_STEP)
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    return level_at(low)
