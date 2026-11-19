"""简单规则策略：每条规则一个测试。

场景主要是超级联盟默认配置的 Azumarill（Bubble 3 回合；Ice Beam 55 能量 / Play Rough 60 能量）
对 Medicham（Counter 2 回合；Ice Punch 40 / Psychic 55）。
对 Medicham：Ice Beam 40 伤害，Play Rough 76 伤害，Bubble 5 伤害；Medicham 的 Counter 打 Azumarill 4 伤害。
需要特定局面时直接改双方的 HP / 能量 / 盾 / 冷却。
"""

from dataclasses import replace

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import Combatant, league_build, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import BattleView, ChargedAction, Decision, FastAction
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig

# 只测某一条规则时，把出招时机和骗盾关掉，免得干扰
PLAIN = SimplePolicyConfig(optimize_timing=False, bait_shields=False)


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _great_league(gm: GameMaster, index: int, species: str, fast: str, charged: tuple[str, ...]) -> Combatant:
    return make_combatant(gm, league_build(gm, species, 1500, fast, charged), index, shields=0)


@pytest.fixture
def azumarill(gm: GameMaster) -> Combatant:
    return _great_league(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH"))


@pytest.fixture
def medicham(gm: GameMaster) -> Combatant:
    return _great_league(gm, 1, "medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC"))


def _decide(config: SimplePolicyConfig, me: Combatant, opponent: Combatant) -> Decision:
    return SimplePolicy(config).decide_action(BattleView(turn=1, me=me, opponent=opponent))


def _move_of(decision: Decision) -> str:
    """快招返回 "fast"，大招返回招式 ID。"""
    if isinstance(decision.action, FastAction):
        return "fast"
    assert isinstance(decision.action, ChargedAction)
    return decision.action.move_id


# ---- 出招规则 ----


def test_rule1_no_energy(azumarill: Combatant, medicham: Combatant) -> None:
    decision = _decide(PLAIN, azumarill, medicham)
    assert _move_of(decision) == "fast"
    assert "energy 0 < 55" in decision.reason


def test_rule2_about_to_faint_from_fast_move(azumarill: Combatant, medicham: Combatant) -> None:
    """对手下一个快招就能打倒我：把能放的伤害最高的大招放掉。"""
    azumarill.hp = 4
    azumarill.energy = 55
    decision = _decide(PLAIN, azumarill, medicham)
    assert _move_of(decision) == "ICE_BEAM"
    assert decision.reason.startswith("about to faint")


def test_rule2_about_to_faint_from_charged_move(azumarill: Combatant, medicham: Combatant) -> None:
    """自己没盾、对手能量够放一个能打倒我的大招（Psychic 47 伤害）：也算快被打倒。"""
    azumarill.hp = 40
    azumarill.energy = 55
    medicham.energy = 55
    decision = _decide(PLAIN, azumarill, medicham)
    assert _move_of(decision) == "ICE_BEAM"
    assert "PSYCHIC" in decision.reason


def test_rule3_finish_with_fast_move(azumarill: Combatant, medicham: Combatant) -> None:
    medicham.hp = 3
    azumarill.energy = 60
    decision = _decide(PLAIN, azumarill, medicham)
    assert _move_of(decision) == "fast"
    assert "opponent HP 3 <= fast move damage 5" in decision.reason


def test_rule4_cheapest_lethal_move(azumarill: Combatant, medicham: Combatant) -> None:
    """对手没盾、HP 30：Ice Beam（40 伤害、55 能量）就够了，不用等 Play Rough。"""
    medicham.hp = 30
    azumarill.energy = 60
    assert _move_of(_decide(PLAIN, azumarill, medicham)) == "ICE_BEAM"


def test_rule4_not_used_when_opponent_has_shields(azumarill: Combatant, medicham: Combatant) -> None:
    medicham.hp = 30
    medicham.shields = 1
    azumarill.energy = 55
    decision = _decide(PLAIN, azumarill, medicham)
    assert _move_of(decision) == "fast"
    assert decision.reason.startswith("saving for PLAY_ROUGH")


@pytest.mark.parametrize(
    ("choice", "expected"),
    [("best_dpe", "PLAY_ROUGH"), ("most_damage", "PLAY_ROUGH"), ("cheapest", "ICE_BEAM")],
)
def test_rule5_target_move(azumarill: Combatant, medicham: Combatant, choice: str, expected: str) -> None:
    azumarill.energy = 60
    assert _move_of(_decide(replace(PLAIN, charged_move_choice=choice), azumarill, medicham)) == expected


def test_rule5_saving_for_target(azumarill: Combatant, medicham: Combatant) -> None:
    """有 55 能量能放 Ice Beam，但目标是 Play Rough（60），所以继续攒。"""
    azumarill.energy = 55
    decision = _decide(PLAIN, azumarill, medicham)
    assert _move_of(decision) == "fast"
    assert decision.reason.startswith("saving for PLAY_ROUGH (55/60")


@pytest.mark.parametrize(("opponent_cooldown", "expected"), [(0, "fast"), (2, "fast"), (1, "PLAY_ROUGH")])
def test_rule6_timing(azumarill: Combatant, medicham: Combatant, opponent_cooldown: int, expected: str) -> None:
    """Bubble 3 回合对 Counter 2 回合：对手冷却是 1（快招本回合结束）才放。"""
    azumarill.energy = 60
    medicham.cooldown = opponent_cooldown
    config = replace(PLAIN, optimize_timing=True)
    assert _move_of(_decide(config, azumarill, medicham)) == expected


def test_rule6_no_wait_if_energy_would_overflow(azumarill: Combatant, medicham: Combatant) -> None:
    azumarill.energy = 95  # 再打一个 Bubble 就超过 100
    medicham.cooldown = 0
    config = replace(PLAIN, optimize_timing=True)
    assert _move_of(_decide(config, azumarill, medicham)) == "PLAY_ROUGH"


def test_rule6_no_wait_against_one_turn_fast_move(gm: GameMaster, azumarill: Combatant) -> None:
    registeel = _great_league(gm, 1, "registeel", "LOCK_ON", ("FOCUS_BLAST", "ZAP_CANNON"))
    azumarill.energy = 60
    config = replace(PLAIN, optimize_timing=True)
    assert _move_of(_decide(config, azumarill, registeel)) == "PLAY_ROUGH"


@pytest.mark.parametrize(("opponent_cooldown", "expected"), [(2, "PSYCHIC"), (3, "fast")])
def test_rule6_window_widens_with_common_divisor(
    gm: GameMaster, medicham: Combatant, opponent_cooldown: int, expected: str
) -> None:
    """Counter 2 回合对 Volt Switch 4 回合：最大公约数 2，冷却 1 可能永远等不到，冷却 2 也算好时机。"""
    galvantula = _great_league(gm, 0, "galvantula", "VOLT_SWITCH", ("LUNGE", "DISCHARGE"))
    medicham.energy = 55
    galvantula.cooldown = opponent_cooldown
    config = replace(PLAIN, optimize_timing=True, charged_move_choice="most_damage")
    assert _move_of(_decide(config, medicham, galvantula)) == expected


def test_rule7_bait(azumarill: Combatant, medicham: Combatant) -> None:
    azumarill.energy = 60
    medicham.shields = 1
    decision = _decide(replace(PLAIN, bait_shields=True), azumarill, medicham)
    assert _move_of(decision) == "ICE_BEAM"
    assert decision.reason.startswith("bait")


# ---- 开盾 ----


@pytest.mark.parametrize(
    ("shielding", "damage", "expected"),
    [
        ("always", 10, True),
        ("never", 500, False),
        ("when_low", 76, True),  # 141 → 65，剩 46%，低于 50%
        ("when_low", 40, False),  # 141 → 101，剩 72%
        ("when_low", 500, True),  # 会被打倒
    ],
)
def test_shield_decision(
    gm: GameMaster, azumarill: Combatant, medicham: Combatant, shielding: str, damage: int, expected: bool
) -> None:
    medicham.shields = 1
    policy = SimplePolicy(SimplePolicyConfig(shielding=shielding, shield_hp_fraction=0.5))
    view = BattleView(turn=1, me=medicham, opponent=azumarill)
    decision = policy.decide_shield(view, gm.get_move("PLAY_ROUGH"), damage)
    assert decision.use_shield is expected
    assert decision.reason


# ---- 整场 ----


def test_full_battle_is_deterministic(gm: GameMaster) -> None:
    def run() -> tuple:
        a = make_combatant(gm, league_build(gm, "azumarill", 1500, "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), 0, 2)
        b = make_combatant(gm, league_build(gm, "medicham", 1500, "COUNTER", ("ICE_PUNCH", "PSYCHIC")), 1, 2)
        result = Battle((a, b), (SimplePolicy(), SimplePolicy())).run()
        return result.ratings, result.turns, len(result.events)

    assert run() == run()
