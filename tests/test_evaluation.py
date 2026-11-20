"""对位评估（pogo_sim/evaluation.py，docs/mechanics.md 13.7）。"""

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import Combatant, league_build, make_combatant
from pogo_sim.evaluation import SHIELD_WEIGHTS, MatchupEvaluator
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team

AZUMARILL = ("azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH"))
MEDICHAM = ("medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC"))


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _mon(gm: GameMaster, spec: tuple[str, str, tuple[str, ...]], index: int) -> Combatant:
    species, fast, charged = spec
    return make_combatant(gm, league_build(gm, species, 1500, fast, charged), index)


def test_zero_shields_is_a_single_battle(gm: GameMaster) -> None:
    """双方都没盾时只打一场，评分就是这场 1v1 的评分。"""
    evaluation = MatchupEvaluator().evaluate(_mon(gm, AZUMARILL, 0), _mon(gm, MEDICHAM, 1), 0, 0, PVPOKE_COMPAT)
    teams = (Team((_mon(gm, AZUMARILL, 0),), 0), Team((_mon(gm, MEDICHAM, 1),), 0))
    expected = Battle(teams, (SimplePolicy(), SimplePolicy())).run().ratings[0]
    assert evaluation.by_shields == ((0, 0, expected),)
    assert evaluation.rating == expected


def test_weighted_average_over_shield_combinations(gm: GameMaster) -> None:
    """双方盾数从 0 到现有的盾数，每种组合各打一场，按 [4, 4, 1] 的乘积加权平均。"""
    evaluation = MatchupEvaluator().evaluate(_mon(gm, AZUMARILL, 0), _mon(gm, MEDICHAM, 1), 2, 1, PVPOKE_COMPAT)
    assert [(mine, theirs) for mine, theirs, _ in evaluation.by_shields] == [
        (0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)
    ]
    weights = [SHIELD_WEIGHTS[mine] * SHIELD_WEIGHTS[theirs] for mine, theirs, _ in evaluation.by_shields]
    assert weights == [16, 16, 16, 16, 4, 4]
    ratings = [rating for _, _, rating in evaluation.by_shields]
    assert evaluation.rating == pytest.approx(sum(r * w for r, w in zip(ratings, weights)) / sum(weights))
    # 每个组合就是那个盾数的一场 1v1
    teams = (Team((_mon(gm, AZUMARILL, 0),), 2), Team((_mon(gm, MEDICHAM, 1),), 1))
    assert ratings[-1] == Battle(teams, (SimplePolicy(), SimplePolicy())).run().ratings[0]


def test_starts_from_current_state_without_changing_it(gm: GameMaster) -> None:
    """从现在的 HP、能量、能力等级开始打；冷却从 0 开始；原来的两只不受影响。"""
    me, opponent = _mon(gm, AZUMARILL, 0), _mon(gm, MEDICHAM, 1)
    fresh = MatchupEvaluator().evaluate(me, opponent, 1, 1, PVPOKE_COMPAT).rating

    me.hp = me.stats.hp // 2
    me.energy = 40
    me.atk_stage = 1
    me.cooldown = 2
    me.chance_meters["ICE_BEAM"] = 0.25
    damaged = MatchupEvaluator().evaluate(me, opponent, 1, 1, PVPOKE_COMPAT).rating
    assert damaged != fresh

    assert (me.hp, me.energy, me.atk_stage, me.cooldown, me.chance_meters) == (
        me.stats.hp // 2, 40, 1, 2, {"ICE_BEAM": 0.25}
    )
    assert (opponent.hp, opponent.energy, opponent.index) == (opponent.stats.hp, 0, 1)

    me.cooldown = 0
    assert MatchupEvaluator().evaluate(me, opponent, 1, 1, PVPOKE_COMPAT).rating == damaged


def test_rating_is_from_my_side(gm: GameMaster) -> None:
    """换个方向评估，两边加起来约等于 1000（每场评分各自向下取整，所以可能差 1）。"""
    evaluator = MatchupEvaluator()
    mine = evaluator.evaluate(_mon(gm, AZUMARILL, 0), _mon(gm, MEDICHAM, 1), 1, 1, PVPOKE_COMPAT).rating
    theirs = evaluator.evaluate(_mon(gm, MEDICHAM, 0), _mon(gm, AZUMARILL, 1), 1, 1, PVPOKE_COMPAT).rating
    assert 998 <= mine + theirs <= 1000


def test_results_are_cached(gm: GameMaster) -> None:
    evaluator = MatchupEvaluator()
    me, opponent = _mon(gm, AZUMARILL, 0), _mon(gm, MEDICHAM, 1)
    first = evaluator.evaluate(me, opponent, 2, 2, PVPOKE_COMPAT)
    assert evaluator.evaluate(_mon(gm, AZUMARILL, 1), _mon(gm, MEDICHAM, 0), 2, 2, PVPOKE_COMPAT) is first
    me.energy = 10
    assert evaluator.evaluate(me, opponent, 2, 2, PVPOKE_COMPAT) is not first


def test_policy_config_is_used(gm: GameMaster) -> None:
    """评估时双方用的策略配置可以换（这里换成从不开盾，结果应该不同）。"""
    me, opponent = _mon(gm, AZUMARILL, 0), _mon(gm, MEDICHAM, 1)
    default = MatchupEvaluator().evaluate(me, opponent, 2, 2, PVPOKE_COMPAT)
    never = MatchupEvaluator(SimplePolicyConfig(shielding="never")).evaluate(me, opponent, 2, 2, PVPOKE_COMPAT)
    assert default.by_shields != never.by_shields


def test_rejects_fainted_and_too_many_shields(gm: GameMaster) -> None:
    me, opponent = _mon(gm, AZUMARILL, 0), _mon(gm, MEDICHAM, 1)
    with pytest.raises(ValueError, match="盾数"):
        MatchupEvaluator().evaluate(me, opponent, 3, 0, PVPOKE_COMPAT)
    opponent.hp = 0
    with pytest.raises(ValueError, match="倒下"):
        MatchupEvaluator().evaluate(me, opponent, 0, 0, PVPOKE_COMPAT)
