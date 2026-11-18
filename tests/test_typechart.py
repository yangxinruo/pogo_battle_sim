"""属性克制表的测试。"""

import pytest

from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.typechart import ALL_TYPES, DEFENSIVE_TRAITS, type_effectiveness
from tests.pvpoke_reference import load_damage_reference


def test_table_covers_all_types() -> None:
    assert set(DEFENSIVE_TRAITS) == set(ALL_TYPES)
    for traits in DEFENSIVE_TRAITS.values():
        for listed in (traits.weak_to, traits.resists, traits.immune_to):
            assert listed <= set(ALL_TYPES)
        # 同一个属性不会同时出现在两个列表里
        assert not (traits.weak_to & traits.resists)
        assert not (traits.weak_to & traits.immune_to)
        assert not (traits.resists & traits.immune_to)


@pytest.mark.parametrize(
    ("move_type", "defender_types", "expected"),
    [
        ("water", ("fire",), 1.6),
        ("fire", ("water",), 0.625),
        ("ghost", ("normal",), 0.390625),
        ("ice", ("dragon", "ground"), 1.6 * 1.6),  # 双重弱点
        ("fire", ("water", "dragon"), 0.625 * 0.625),  # 双重抵抗
        ("electric", ("ground", "flying"), 0.390625 * 1.6),  # 免疫 × 弱点
        ("normal", ("water",), 1.0),
    ],
)
def test_examples(move_type: str, defender_types: tuple[str, ...], expected: float) -> None:
    """几个容易看懂的例子。PvPoke 的常数是 float32 精度，所以这里只比到 1e-6。"""
    actual = type_effectiveness(move_type, defender_types, PVPOKE_COMPAT)
    assert actual == pytest.approx(expected, rel=1e-6)


def test_matches_pvpoke_exactly() -> None:
    """18 种招式属性 × 171 种防守属性组合（18 种单属性 + 153 种双属性），逐位相同。"""
    entries = load_damage_reference()["type_effectiveness"]
    assert len(entries) == 18 * (18 + 18 * 17 // 2)

    mismatches = [
        entry
        for entry in entries
        if type_effectiveness(entry["move_type"], entry["defender_types"], PVPOKE_COMPAT)
        != entry["value"]
    ]
    assert mismatches == []
