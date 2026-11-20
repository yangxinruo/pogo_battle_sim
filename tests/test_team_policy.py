"""3v3 策略（pogo_sim/team_policy.py，docs/mechanics.md 13.7）。"""

from dataclasses import replace

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import Combatant, league_build, make_combatant
from pogo_sim.damage import calculate_damage
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import BattleView, FastAction, SwitchAction
from pogo_sim.report import format_result
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team
from pogo_sim.team_policy import TeamPolicy, TeamPolicyConfig
from pogo_sim.timeline import DecisionEvent, MoveEvent, SwitchEvent

AZUMARILL = ("azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH"))
MEDICHAM = ("medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC"))
REGISTEEL = ("registeel", "LOCK_ON", ("FOCUS_BLAST", "ZAP_CANNON"))
SWAMPERT = ("swampert", "MUD_SHOT", ("HYDRO_CANNON", "EARTHQUAKE"))
ALTARIA = ("altaria", "DRAGON_BREATH", ("SKY_ATTACK", "MOONBLAST"))
TREVENANT = ("trevenant", "SHADOW_CLAW", ("SEED_BOMB", "SHADOW_BALL"))
SKARMORY = ("skarmory", "AIR_SLASH", ("BRAVE_BIRD", "SKY_ATTACK"))
WALREIN = ("walrein", "POWDER_SNOW", ("ICICLE_SPEAR", "EARTHQUAKE"))


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


def _rating(gm_team: Team, slot: int, opponent: Combatant) -> float:
    """和 TeamPolicy 同样的评估（两队都是 2 个盾）。"""
    return MatchupEvaluator().evaluate(gm_team.members[slot], opponent, 2, 2, PVPOKE_COMPAT).rating


# ---- 主动换人（3v3-d2）----


def test_switches_out_of_a_bad_matchup(gm: GameMaster) -> None:
    """当前对位 < 450、后备里最好的 ≥ 500 且比当前高 100 以上：换上它（占用这一回合）。"""
    mine = _team(gm, 0, REGISTEEL, ALTARIA, TREVENANT)
    theirs = _team(gm, 1, SWAMPERT)
    swampert = theirs.members[0]
    current, altaria, trevenant = (_rating(mine, slot, swampert) for slot in (0, 1, 2))
    assert current < 450 and trevenant > altaria >= 500  # 钢被地面克制；草/幽灵、龙/飞都克制水/地面

    decision = TeamPolicy().decide_action(BattleView(5, mine, theirs, PVPOKE_COMPAT))
    assert decision.action == SwitchAction(2)
    assert decision.reason == (
        f"switch: matchup vs Swampert {round(current)} < 450, Trevenant {round(trevenant)} >= 500 "
        f"(Trevenant {round(trevenant)}, Altaria {round(altaria)})"
    )


def test_stays_in_a_good_matchup(gm: GameMaster) -> None:
    """当前对位 ≥ 450：不换，出招照简单规则策略；刚评估过，原因前面写出为什么不换。"""
    mine = _team(gm, 0, TREVENANT, REGISTEEL)
    theirs = _team(gm, 1, SWAMPERT)
    current = _rating(mine, 0, theirs.members[0])
    view = BattleView(5, mine, theirs, PVPOKE_COMPAT)
    decision = TeamPolicy().decide_action(view)
    simple = SimplePolicy().decide_action(view)
    assert decision.action == simple.action
    assert decision.reason == f"stay: matchup vs Swampert {round(current)} >= 450; {simple.reason}"


def test_stays_when_no_bench_option_is_good_enough(gm: GameMaster) -> None:
    mine = _team(gm, 0, REGISTEEL, SKARMORY, AZUMARILL)
    theirs = _team(gm, 1, SWAMPERT)
    swampert = theirs.members[0]
    current, skarmory, azumarill = (_rating(mine, slot, swampert) for slot in (0, 1, 2))
    assert current < 450 and skarmory < 500 and azumarill < 500
    decision = TeamPolicy().decide_action(BattleView(5, mine, theirs, PVPOKE_COMPAT))
    assert isinstance(decision.action, FastAction)
    assert decision.reason.startswith(
        f"stay: matchup vs Swampert {round(current)} < 450, no bench option >= 500 "
        f"(Azumarill {round(azumarill)}, Skarmory {round(skarmory)}); "
    )


def test_switch_margin(gm: GameMaster) -> None:
    """换上去的那只还要比当前高 switch_margin：把差距调大，同一个局面就不换了。"""
    mine = _team(gm, 0, REGISTEEL, MEDICHAM)
    theirs = _team(gm, 1, SWAMPERT)
    current, medicham = _rating(mine, 0, theirs.members[0]), _rating(mine, 1, theirs.members[0])
    assert current + 100 <= medicham < current + 300 and medicham >= 500
    view = BattleView(5, mine, theirs, PVPOKE_COMPAT)
    assert TeamPolicy().decide_action(view).action == SwitchAction(1)
    strict = TeamPolicy(TeamPolicyConfig(switch_margin=300)).decide_action(view)
    assert isinstance(strict.action, FastAction)
    assert f"no bench option >= {round(current + 300)}" in strict.reason


def test_low_hp_stays_in(gm: GameMaster) -> None:
    """自己 HP 不超过 25% 时不主动换（PvPoke 高难度 AI）。"""
    mine = _team(gm, 0, REGISTEEL, TREVENANT)
    mine.members[0].hp = mine.members[0].stats.hp // 5
    decision = TeamPolicy().decide_action(BattleView(5, mine, _team(gm, 1, SWAMPERT), PVPOKE_COMPAT))
    assert isinstance(decision.action, FastAction)
    assert decision.reason.startswith("stay: HP 19% <= 25%; ")


def test_no_switch_logic_while_switch_is_locked(gm: GameMaster) -> None:
    """换人冷却没走完：只按简单规则策略出招，原因也和它一样。"""
    mine = _team(gm, 0, REGISTEEL, TREVENANT)
    mine.switch_timer_ms = 10_000
    view = BattleView(5, mine, _team(gm, 1, SWAMPERT), PVPOKE_COMPAT)
    assert TeamPolicy().decide_action(view) == SimplePolicy().decide_action(view)


def test_reevaluates_only_when_the_situation_changes(gm: GameMaster) -> None:
    """reevaluate = "on_change"：快招造成的小变化沿用上次的结论；有人放了大招、换了人、盾数变了才重算。"""
    mine = _team(gm, 0, TREVENANT, REGISTEEL)
    theirs = _team(gm, 1, SWAMPERT, AZUMARILL)  # Trevenant 对两只都占优，结论一直是"不换"
    policy = TeamPolicy()

    def evaluated(turn: int) -> bool:
        """这一回合是不是重新评估了：新评估的结论会写在原因的最前面。"""
        reason = policy.decide_action(BattleView(turn, mine, theirs, PVPOKE_COMPAT)).reason
        return reason.startswith(("stay: ", "switch: "))

    assert evaluated(5)  # 第一次：评估
    mine.members[0].hp -= 10
    theirs.members[0].energy = 30
    assert not evaluated(7)  # 只有快招的变化：沿用
    theirs.members[0].energy = 0  # 对手放了大招
    assert evaluated(9)
    assert not evaluated(11)
    theirs.active = 1  # 对手换了人
    assert evaluated(13)
    assert not evaluated(15)
    mine.shields = 1  # 盾数变了
    assert evaluated(17)

    every = TeamPolicy(TeamPolicyConfig(reevaluate="every_decision"))
    for turn in (5, 7):
        assert every.decide_action(BattleView(turn, mine, theirs, PVPOKE_COMPAT)).reason.startswith(
            ("stay: ", "switch: ")
        )


def test_zero_turn_switch_uses_the_same_rule(gm: GameMaster) -> None:
    mine = _team(gm, 0, REGISTEEL, ALTARIA, TREVENANT)
    view = BattleView(5, mine, _team(gm, 1, SWAMPERT), PVPOKE_COMPAT)
    decision = TeamPolicy().decide_zero_turn_switch(view)
    assert decision.to == 2 and decision.reason.startswith("switch: matchup vs Swampert ")


def test_zero_turn_switch_while_opponent_chooses(gm: GameMaster) -> None:
    """对手正在选人（它在场的那只倒下了）：对手按它剩下的每一只取平均。"""
    mine = _team(gm, 0, REGISTEEL, TREVENANT)
    theirs = _team(gm, 1, MEDICHAM, SWAMPERT, WALREIN)
    theirs.members[0].hp = 0
    decision = TeamPolicy().decide_zero_turn_switch(BattleView(5, mine, theirs, PVPOKE_COMPAT))
    assert "vs Swampert/Walrein (opponent also choosing: average)" in decision.reason


def test_switching_never(gm: GameMaster) -> None:
    """switching = "never"（D3 的基准 (a)）：同样的坏对位也不换。"""
    mine = _team(gm, 0, REGISTEEL, ALTARIA, TREVENANT)
    view = BattleView(5, mine, _team(gm, 1, SWAMPERT), PVPOKE_COMPAT)
    policy = TeamPolicy(TeamPolicyConfig(switching="never"))
    assert policy.decide_action(view) == SimplePolicy().decide_action(view)
    assert policy.decide_zero_turn_switch(view).to is None


# ---- 开盾（3v3-d3）----


def _shield_view(gm: GameMaster, me: tuple, attacker: tuple, *bench: tuple) -> tuple[BattleView, int]:
    """对手（attacker）刚放了 Hydro Cannon 之类的大招：能量已经扣掉，问 me 开不开盾。"""
    mine = _team(gm, 0, me, *bench)
    theirs = _team(gm, 1, attacker)
    move = theirs.members[0].charged_moves[0]
    damage = calculate_damage(move, theirs.members[0].damage_side(), mine.members[0].damage_side(), PVPOKE_COMPAT)
    return BattleView(5, mine, theirs, PVPOKE_COMPAT), damage


def test_saves_shield_in_a_losing_matchup(gm: GameMaster) -> None:
    """后备还有、开了盾这一只仍然输：不开，把盾留给后面。"""
    view, damage = _shield_view(gm, REGISTEEL, SWAMPERT, TREVENANT)
    move = view.opponent.charged_moves[0]
    # 开盾后：挨 1 点伤害、少一个盾
    shielded = MatchupEvaluator().evaluate(replace(view.me, hp=view.me.hp - 1), view.opponent, 1, 2, PVPOKE_COMPAT)
    assert shielded.rating < 500
    decision = TeamPolicy().decide_shield(view, move, damage)
    assert not decision.use_shield
    assert decision.reason == (
        f"save shield for the bench: even with a shield, matchup vs Swampert {shielded.rounded} < 500"
    )


def test_shields_in_a_winning_matchup(gm: GameMaster) -> None:
    view, damage = _shield_view(gm, TREVENANT, SWAMPERT, REGISTEEL)
    decision = TeamPolicy().decide_shield(view, view.opponent.charged_moves[0], damage)
    assert decision.use_shield
    assert decision.reason.startswith("always shield (2 left); with a shield, matchup vs Swampert ")


def test_last_pokemon_follows_the_simple_rule(gm: GameMaster) -> None:
    """没有后备了：盾没有别的用处，照简单规则策略（默认有盾就开）。"""
    view, damage = _shield_view(gm, REGISTEEL, SWAMPERT)
    decision = TeamPolicy().decide_shield(view, view.opponent.charged_moves[0], damage)
    assert decision.use_shield and decision.reason == "always shield (2 left)"


def test_no_shield_when_it_would_not_save_me(gm: GameMaster) -> None:
    view, damage = _shield_view(gm, TREVENANT, SWAMPERT, REGISTEEL)
    view.me.hp = 1
    decision = TeamPolicy().decide_shield(view, view.opponent.charged_moves[0], damage)
    assert not decision.use_shield and "would not save me" in decision.reason


def test_save_shields_can_be_turned_off(gm: GameMaster) -> None:
    view, damage = _shield_view(gm, REGISTEEL, SWAMPERT, TREVENANT)
    policy = TeamPolicy(TeamPolicyConfig(save_shields_for_bench=False))
    assert policy.decide_shield(view, view.opponent.charged_moves[0], damage).use_shield


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


def _readme_teams(gm: GameMaster) -> tuple[Team, Team]:
    return _team(gm, 0, AZUMARILL, MEDICHAM, REGISTEEL), _team(gm, 1, SWAMPERT, ALTARIA, TREVENANT)


def test_full_3v3(gm: GameMaster) -> None:
    """README 那两队，双方都用默认的团队策略（按阈值换人、不在必输的对位上开盾）。"""
    a, b = _readme_teams(gm)
    result = Battle((a, b), (TeamPolicy(), TeamPolicy())).run()
    assert format_result(result, ("Team A", "Team B")) == (
        "Team B wins: rating 387 vs 612, Pokemon left 0 vs 2, shields left 0 vs 0, 126 turns"
    )
    assert [(e.turn, e.actor, e.kind, e.to_slot) for e in result.events if isinstance(e, SwitchEvent)] == [
        (41, 1, "zero_turn", 2),
        (56, 0, "replacement", 2),
        (75, 1, "zero_turn", 0),
        (76, 0, "switch", 1),
        (93, 1, "replacement", 1),
        (100, 0, "replacement", 2),
        (119, 1, "zero_turn", 2),
    ]
    saved = [
        (e.turn, e.move_id)
        for e in result.events
        if isinstance(e, MoveEvent) and e.shield_reason and e.shield_reason.startswith("save shield")
    ]
    assert saved == [(30, "HYDRO_CANNON"), (40, "HYDRO_CANNON"), (55, "SEED_BOMB")]

    # 每回合都重算评估，这一场的结果完全一样（一般不保证），只是慢
    a, b = _readme_teams(gm)
    every = TeamPolicyConfig(reevaluate="every_decision")
    slow = Battle((a, b), (TeamPolicy(every), TeamPolicy(every))).run()
    assert format_result(slow, ("Team A", "Team B")) == format_result(result, ("Team A", "Team B"))


def test_full_3v3_without_active_switching(gm: GameMaster) -> None:
    """不主动换人、照简单规则开盾：只剩"倒下后换上评分最高的"（3v3-d1）。和简单规则策略（倒下后按队伍顺序）比，
    第 56 回合 A 换上的是对 Altaria 评分更高的 Registeel，而不是排在前面的 Medicham。"""
    a, b = _readme_teams(gm)
    config = TeamPolicyConfig(switching="never", save_shields_for_bench=False)
    result = Battle((a, b), (TeamPolicy(config), TeamPolicy(config))).run()
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
