"""伤害计算（docs/mechanics.md 第 3 节）。

伤害 = floor(威力 × STAB × (有效攻击 / 有效防御) × 克制倍率 × 蓄力比例 × Mega 招式加成 × 0.5 × PvP 加成) + 1

来源：PvPoke battle/DamageCalculator.js 的 damage()，pokemon/Pokemon.js 的 getEffectiveStat()。
状态：参考 PvPoke，已用 PvPoke 源码逐个核对 423 个用例（tests/test_damage.py）。

关于乘法顺序：浮点数乘法不满足结合律，(a × b) × c 和 a × (b × c) 末位可能不同，
落在整数边界附近时 floor 的结果就会差 1。所以这里的乘法顺序与 PvPoke 完全一致，不要"化简"。

暂不支持（第 3a 步范围外）：
- 按最大 HP 百分比计算伤害的招式（Gulp Missile，属于 Cramorant 的形态变化）；
- 形态变化的特殊规则（例如 Aegislash 盾牌形态放大招时用剑形态的攻击）。
"""

from dataclasses import dataclass
from math import floor

from pogo_sim.gamemaster import Move
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.stats import BattleStats
from pogo_sim.typechart import type_effectiveness


@dataclass(frozen=True)
class DamageSide:
    """计算一次伤害时，一方（攻方或守方）需要的数据。

    攻方只用到 atk_stage 和 mega_level，守方只用到 def_stage；两边用同一个类，省得记两套。
    第 3b 步的对战状态会在每次出招时生成它。
    """

    types: tuple[str, ...]
    stats: BattleStats
    is_shadow: bool = False
    atk_stage: int = 0
    def_stage: int = 0
    mega_level: int | None = None  # Mega 等级 1–4；不是 Mega 时为 None

    def __post_init__(self) -> None:
        if self.mega_level is not None and not 1 <= self.mega_level <= 4:
            raise ValueError(f"Mega 等级必须是 1 到 4，得到 {self.mega_level}")


def stat_stage_multiplier(stage: int, rules: BattleRules = PVPOKE_COMPAT) -> float:
    """能力等级对应的倍率：+1 → 5/4，+4 → 8/4，−1 → 4/5，−4 → 4/8。"""
    if not -rules.max_stat_stage <= stage <= rules.max_stat_stage:
        raise ValueError(
            f"能力等级必须在 ±{rules.max_stat_stage} 之间，得到 {stage}"
        )
    divisor = rules.stat_stage_divisor
    if stage > 0:
        return (divisor + stage) / divisor
    return divisor / (divisor - stage)


def effective_attack(side: DamageSide, rules: BattleRules = PVPOKE_COMPAT) -> float:
    """有效攻击 = 攻击 × (能力等级倍率 × 暗影倍率)。

    PvPoke 先把两个倍率乘在一起，再乘到攻击上；顺序照搬。
    """
    multiplier = stat_stage_multiplier(side.atk_stage, rules)
    if side.is_shadow:
        multiplier *= rules.shadow_attack
    return side.stats.atk * multiplier


def effective_defense(side: DamageSide, rules: BattleRules = PVPOKE_COMPAT) -> float:
    """有效防御 = 防御 × (能力等级倍率 × 暗影倍率)。"""
    multiplier = stat_stage_multiplier(side.def_stage, rules)
    if side.is_shadow:
        multiplier *= rules.shadow_defense
    return side.stats.def_ * multiplier


def stab_multiplier(
    move_type: str, attacker_types: tuple[str, ...], rules: BattleRules = PVPOKE_COMPAT
) -> float:
    """招式属性与攻方的任一属性相同时有本系加成。"""
    return rules.stab if move_type in attacker_types else 1.0


def mega_move_multiplier(
    move: Move, attacker: DamageSide, rules: BattleRules = PVPOKE_COMPAT
) -> float:
    """Mega 专属招式按 Mega 等级加成；其他情况为 1。"""
    if attacker.mega_level is not None and move.is_mega_move:
        return rules.mega_move_bonus[attacker.mega_level - 1]
    return 1.0


def calculate_damage(
    move: Move,
    attacker: DamageSide,
    defender: DamageSide,
    rules: BattleRules = PVPOKE_COMPAT,
    charge: float = 1.0,
) -> int:
    """一次招式命中（未被盾挡下）造成的伤害。

    charge 是大招的蓄力比例。模拟里一律满蓄力（1.0），保留参数只是为了以后可调。
    被盾挡下时的伤害（1 点）由对战结算处理，不在这里。
    """
    if move.damage_method != "default":
        raise NotImplementedError(
            f"{move.move_id} 的伤害算法 {move.damage_method!r} 尚未支持（见本模块说明）"
        )

    stab = stab_multiplier(move.type, attacker.types, rules)
    attack = effective_attack(attacker, rules)
    defense = effective_defense(defender, rules)
    effectiveness = type_effectiveness(move.type, defender.types, rules)
    mega_bonus = mega_move_multiplier(move, attacker, rules)

    # 顺序与 PvPoke DamageCalculator.damage() 一致。
    raw = (
        move.power
        * stab
        * (attack / defense)
        * effectiveness
        * charge
        * mega_bonus
        * 0.5
        * rules.pvp_bonus
    )
    return floor(raw) + 1
