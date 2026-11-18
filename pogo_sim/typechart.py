"""属性克制表。

来源：PvPoke battle/DamageCalculator.js 的 getTypeTraits / getEffectiveness。
状态：参考 PvPoke，并已用 PvPoke 源码对全部 18 种招式属性 × 171 种防守属性组合逐一核对
（tests/test_typechart.py）。
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pogo_sim.rules import BattleRules

# 18 种属性，顺序与 PvPoke 的 Pokemon.getAllTypes() 相同。
ALL_TYPES: tuple[str, ...] = (
    "bug",
    "dark",
    "dragon",
    "electric",
    "fairy",
    "fighting",
    "fire",
    "flying",
    "ghost",
    "grass",
    "ground",
    "ice",
    "normal",
    "poison",
    "psychic",
    "rock",
    "steel",
    "water",
)


@dataclass(frozen=True)
class DefensiveTraits:
    """一种防守属性怕什么（weak_to）、抵抗什么（resists）、"免疫"什么（immune_to）。

    GO 里没有真正的免疫：正作里的免疫在 GO 里是 0.390625 倍，与双重抵抗相同。
    """

    weak_to: frozenset[str]
    resists: frozenset[str]
    immune_to: frozenset[str]


def _traits(weak_to: str, resists: str, immune_to: str = "") -> DefensiveTraits:
    """用空格分隔的属性名写起来更紧凑。"""
    return DefensiveTraits(
        weak_to=frozenset(weak_to.split()),
        resists=frozenset(resists.split()),
        immune_to=frozenset(immune_to.split()),
    )


# 键是防守方的属性。
DEFENSIVE_TRAITS: dict[str, DefensiveTraits] = {
    "normal": _traits(weak_to="fighting", resists="", immune_to="ghost"),
    "fighting": _traits(weak_to="flying psychic fairy", resists="rock bug dark"),
    "flying": _traits(weak_to="rock electric ice", resists="fighting bug grass", immune_to="ground"),
    "poison": _traits(weak_to="ground psychic", resists="fighting poison bug fairy grass"),
    "ground": _traits(weak_to="water grass ice", resists="poison rock", immune_to="electric"),
    "rock": _traits(weak_to="fighting ground steel water grass", resists="normal flying poison fire"),
    "bug": _traits(weak_to="flying rock fire", resists="fighting ground grass"),
    "ghost": _traits(weak_to="ghost dark", resists="poison bug", immune_to="normal fighting"),
    "steel": _traits(
        weak_to="fighting ground fire",
        resists="normal flying rock bug steel grass psychic ice dragon fairy",
        immune_to="poison",
    ),
    "fire": _traits(weak_to="ground rock water", resists="bug steel fire grass ice fairy"),
    "water": _traits(weak_to="grass electric", resists="steel fire water ice"),
    "grass": _traits(weak_to="flying poison bug fire ice", resists="ground water grass electric"),
    "electric": _traits(weak_to="ground", resists="flying steel electric"),
    "psychic": _traits(weak_to="bug ghost dark", resists="fighting psychic"),
    "ice": _traits(weak_to="fighting fire steel rock", resists="ice"),
    "dragon": _traits(weak_to="dragon ice fairy", resists="fire water grass electric"),
    "dark": _traits(weak_to="fighting fairy bug", resists="ghost dark", immune_to="psychic"),
    "fairy": _traits(weak_to="poison steel", resists="fighting bug dark", immune_to="dragon"),
}


def type_effectiveness(
    move_type: str, defender_types: Sequence[str], rules: BattleRules
) -> float:
    """招式属性对防守方的总倍率：对防守方的每个属性各乘一次。

    从 1 开始，按防守方属性的顺序依次相乘，与 PvPoke 相同。
    （两个浮点数相乘与顺序无关，但从同一个起点、同样的步骤算，才能保证和 PvPoke 逐位相同。）
    例：冰打龙/地面 = 1.6 × 1.6；火打水/龙 = 0.625 × 0.625；电打地面/飞行 = 0.390625 × 1.6。
    """
    multiplier = 1.0
    for defender_type in defender_types:
        traits = DEFENSIVE_TRAITS[defender_type]
        if move_type in traits.weak_to:
            multiplier *= rules.super_effective
        elif move_type in traits.resists:
            multiplier *= rules.resisted
        elif move_type in traits.immune_to:
            multiplier *= rules.double_resisted
    return multiplier
