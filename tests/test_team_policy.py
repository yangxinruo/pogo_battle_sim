"""3v3 策略（pogo_sim/team_policy.py，docs/mechanics.md 13.7）。"""

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import Combatant, league_build, make_combatant
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import BattleView
from pogo_sim.report import format_result
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team
from pogo_sim.team_policy import TeamPolicy, TeamPolicyConfig
from pogo_sim.timeline import DecisionEvent, SwitchEvent

AZUMARILL = ("azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH"))
MEDICHAM = ("medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC"))
REGISTEEL = ("registeel", "LOCK_ON", ("FOCUS_BLAST", "ZAP_CANNON"))
SWAMPERT = ("swampert", "MUD_SHOT", ("HYDRO_CANNON", "EARTHQUAKE"))
ALTARIA = ("altaria", "DRAGON_BREATH", ("SKY_ATTACK", "MOONBLAST"))
TREVENANT = ("trevenant", "SHADOW_CLAW", ("SEED_BOMB", "SHADOW_BALL"))


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _mon(gm: GameMaster, spec: tuple[str, str, tuple[str, ...]], index: int) -> Combatant:
    species, fast, charged = spec
    return make_combatant(gm, league_build(gm, species, 1500, fast, charged), index)


def _team(gm: GameMaster, index: int, *specs: tuple[str, str, tuple[str, ...]], shields: int = 2) -> Team:
    return Team(tuple(_mon(gm, spec, index) for spec in specs), shields)


def test_replacement_picks_best_matchup(gm: GameMaster) -> None:
    """倒下后换上对位评分最高的，不管队伍顺序；原因里按评分列出每个候选。"""
    mine = _team(gm, 0, AZUMARILL, REGISTEEL, TREVENANT)
    mine.members[0].hp = 0
    theirs = _team(gm, 1, SWAMPERT, ALTARIA)
    view = BattleView(5, mine, theirs, PVPOKE_COMPAT)

    policy = TeamPolicy()
    choice = policy.choose_replacement(view)

    evaluator = MatchupEvaluator()
    trevenant = evaluator.evaluate(mine.members[2], theirs.members[0], 2, 2, PVPOKE_COMPAT).rounded
    registeel = evaluator.evaluate(mine.members[1], theirs.members[0], 2, 2, PVPOKE_COMPAT).rounded
    assert trevenant > registeel  # 草/幽灵克制水/地面，钢被地面克制
    assert (choice.to, choice.wait_ms) == (2, 0)
    assert choice.reason == f"best matchup vs Swampert: Trevenant {trevenant}, Registeel {registeel}"


def test_replacement_tie_keeps_team_order(gm: GameMaster) -> None:
    """评分相同时换上队伍里靠前的：对手只剩 1 HP，两个候选第 1 回合都能无伤打倒它。"""
    mine = _team(gm, 0, AZUMARILL, REGISTEEL, ALTARIA)
    mine.members[0].hp = 0
    theirs = _team(gm, 1, SWAMPERT)
    theirs.members[0].hp = 1
    choice = TeamPolicy().choose_replacement(BattleView(5, mine, theirs, PVPOKE_COMPAT))
    assert choice.to == 1
    assert choice.reason == "best matchup vs Swampert: Registeel 1000, Altaria 1000"


def test_replacement_when_both_choose_averages_over_opponent_bench(gm: GameMaster) -> None:
    """双方同时倒下：看不到对手换谁上，就和对手剩下的每一只评估，取平均。"""
    mine = _team(gm, 0, AZUMARILL, REGISTEEL, TREVENANT)
    theirs = _team(gm, 1, MEDICHAM, SWAMPERT, ALTARIA)
    mine.members[0].hp = theirs.members[0].hp = 0
    choice = TeamPolicy().choose_replacement(BattleView(5, mine, theirs, PVPOKE_COMPAT))

    evaluator = MatchupEvaluator()

    def average(slot: int) -> float:
        member = mine.members[slot]
        ratings = [evaluator.evaluate(member, theirs.members[o], 2, 2, PVPOKE_COMPAT).rating for o in (1, 2)]
        return sum(ratings) / 2

    best = max((1, 2), key=lambda slot: (average(slot), -slot))
    assert choice.to == best
    assert choice.reason.startswith("best matchup vs Swampert/Altaria (opponent also choosing: average): ")


def test_never_switches_by_choice(gm: GameMaster) -> None:
    view = BattleView(5, _team(gm, 0, AZUMARILL, REGISTEEL), _team(gm, 1, SWAMPERT), PVPOKE_COMPAT)
    decision = TeamPolicy().decide_zero_turn_switch(view)
    assert decision.to is None


def test_moves_and_shields_follow_simple_policy(gm: GameMaster) -> None:
    """1v1 里没有换人，团队策略打出来的和简单规则策略完全一样。"""
    config = SimplePolicyConfig(shielding="when_low", bait_shields=False)

    def run(policy_a, policy_b) -> list:
        teams = (_team(gm, 0, AZUMARILL, shields=1), _team(gm, 1, MEDICHAM, shields=1))
        return Battle(teams, (policy_a, policy_b)).run().events

    team = run(TeamPolicy(TeamPolicyConfig(moves=config)), TeamPolicy(TeamPolicyConfig(moves=config)))
    simple = run(SimplePolicy(config), SimplePolicy(config))
    assert team == simple


def test_evaluator_must_match_config() -> None:
    with pytest.raises(ValueError, match="config.evaluation"):
        TeamPolicy(evaluator=MatchupEvaluator(SimplePolicyConfig(shielding="never")))


def test_full_3v3(gm: GameMaster) -> None:
    """README 那两队，双方都用团队策略。和简单规则策略（倒下后按队伍顺序换）比，第 56 回合 A 换上的是
    对 Altaria 评分更高的 Registeel，而不是排在前面的 Medicham。"""
    a = _team(gm, 0, AZUMARILL, MEDICHAM, REGISTEEL)
    b = _team(gm, 1, SWAMPERT, ALTARIA, TREVENANT)
    result = Battle((a, b), (TeamPolicy(), TeamPolicy())).run()
    assert format_result(result, ("Team A", "Team B")) == (
        "Team B wins: rating 374 vs 625, Pokemon left 0 vs 1, shields left 0 vs 0, 123 turns"
    )
    assert [(e.turn, e.actor, e.to_slot) for e in result.events if isinstance(e, SwitchEvent)] == [
        (54, 1, 1),
        (56, 0, 2),
        (94, 1, 2),
        (110, 0, 1),
    ]
    reasons = [e.reason for e in result.events if isinstance(e, DecisionEvent) and e.action == "replacement"]
    assert reasons[1] == "best matchup vs Altaria: Registeel 724, Medicham 387"
