"""伤害计算的测试。

前半部分是不依赖 PvPoke 的基本性质；后半部分逐个对照 PvPoke 源码算出的 423 个用例。
"""

from dataclasses import replace

import pytest

from pogo_sim.damage import (
    DamageSide,
    calculate_damage,
    effective_attack,
    effective_defense,
    stab_multiplier,
    stat_stage_multiplier,
)
from pogo_sim.gamemaster import GameMaster, Move, load_gamemaster
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.stats import BattleStats, IVs, calculate_battle_stats, calculate_cp
from pogo_sim.typechart import type_effectiveness
from tests.pvpoke_reference import load_damage_reference


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _test_move(power: float, move_type: str = "normal") -> Move:
    """一个只用于测试的快招。"""
    return Move(
        move_id="TEST_MOVE",
        name="Test Move",
        type=move_type,
        power=power,
        energy_cost=0,
        energy_gain=10,
        turns=1,
        is_fast=True,
        effect=None,
        is_mega_move=False,
        damage_method="default",
        tags=(),
    )


# ---- 基本性质 ----


@pytest.mark.parametrize(
    ("stage", "expected"),
    [(-4, 4 / 8), (-3, 4 / 7), (-2, 4 / 6), (-1, 4 / 5), (0, 1.0),
     (1, 5 / 4), (2, 6 / 4), (3, 7 / 4), (4, 8 / 4)],
)
def test_stat_stage_multiplier(stage: int, expected: float) -> None:
    assert stat_stage_multiplier(stage) == expected


@pytest.mark.parametrize("stage", [-5, 5])
def test_stat_stage_out_of_range(stage: int) -> None:
    with pytest.raises(ValueError):
        stat_stage_multiplier(stage)


def test_minimum_damage_is_one() -> None:
    """威力 0 的招式（如 Splash）也造成 1 点伤害：floor(0) + 1。"""
    side = DamageSide(types=("water",), stats=BattleStats(atk=100.0, def_=100.0, hp=100))
    assert calculate_damage(_test_move(power=0), side, side) == 1


def test_float32_bonus_changes_result() -> None:
    """说明为什么照搬 PvPoke 的 float32 常数。

    威力 20、攻防相等、无加成：20 × 0.5 × 1.3 正好是 13，floor 后 +1 得 14；
    但 1.3 的 float32 值是 1.2999999523…，乘出来是 12.99999952…，floor 后 +1 得 13。
    PvPoke（以及游戏本身用 float32 计算）得到的是 13。
    """
    side = DamageSide(types=("water",), stats=BattleStats(atk=100.0, def_=100.0, hp=100))
    move = _test_move(power=20)
    assert calculate_damage(move, side, side, PVPOKE_COMPAT) == 13
    exact_rules = replace(PVPOKE_COMPAT, pvp_bonus=1.3)
    assert calculate_damage(move, side, side, exact_rules) == 14


def test_percent_max_hp_moves_not_supported(gm: GameMaster) -> None:
    side = DamageSide(types=("water",), stats=BattleStats(atk=100.0, def_=100.0, hp=100))
    with pytest.raises(NotImplementedError):
        calculate_damage(gm.get_move("GULP_MISSILE_ARROKUDA"), side, side)


def test_invalid_mega_level() -> None:
    with pytest.raises(ValueError):
        DamageSide(types=("fairy",), stats=BattleStats(atk=1.0, def_=1.0, hp=10), mega_level=5)


# ---- 对照 PvPoke ----

REFERENCE = load_damage_reference()
DAMAGE_CASES = REFERENCE["damage_cases"]


def _case_id(index: int, case: dict) -> str:
    return f"{index:03d}-{case['attacker']['species']}-{case['move']}-vs-{case['defender']['species']}"


def _make_side(gm: GameMaster, spec: dict) -> tuple[DamageSide, int]:
    """把用例里的一方转成 DamageSide，同时返回 CP（顺便核对）。"""
    species = gm.get_species(spec["species"])
    ivs = IVs(*spec["ivs"])
    side = DamageSide(
        types=species.types,
        stats=calculate_battle_stats(species.base_stats, ivs, spec["level"]),
        is_shadow=species.is_shadow,
        atk_stage=spec.get("atk_stage", 0),
        def_stage=spec.get("def_stage", 0),
        mega_level=spec.get("mega_level"),
    )
    cp = calculate_cp(species.base_stats, ivs, spec["level"])
    return side, cp


def test_reference_comes_from_snapshot_commit() -> None:
    """参考数据必须和 data/ 里的 gamemaster 快照来自同一个 PvPoke commit。"""
    assert REFERENCE["source"]["pvpoke_commit"] == "d02018eb6bfc4a041cca69d7bc9de0d5179a8365"


@pytest.mark.parametrize(
    "case", DAMAGE_CASES, ids=[_case_id(i, c) for i, c in enumerate(DAMAGE_CASES)]
)
def test_matches_pvpoke(gm: GameMaster, case: dict) -> None:
    """中间值（CP、有效攻防、克制、STAB）和最终伤害都要与 PvPoke 逐位相同。"""
    attacker, attacker_cp = _make_side(gm, case["attacker"])
    defender, defender_cp = _make_side(gm, case["defender"])
    move = gm.get_move(case["move"])
    expected = case["expected"]

    # 先比中间值：出错时能直接看出是哪一步不同
    assert attacker_cp == expected["attacker_cp"]
    assert defender_cp == expected["defender_cp"]
    assert effective_attack(attacker) == expected["attack"]
    assert effective_defense(defender) == expected["defense"]
    assert type_effectiveness(move.type, defender.types, PVPOKE_COMPAT) == expected["effectiveness"]
    assert stab_multiplier(move.type, attacker.types) == expected["stab"]

    assert calculate_damage(move, attacker, defender) == expected["damage"]
