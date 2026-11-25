"""手动对战（pogo_sim/manual.py）和它用到的两个引擎功能：等待、大招威力（docs/mechanics.md 14.5）。"""

from dataclasses import replace

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import league_build, make_combatant
from pogo_sim.config import REPO_ROOT
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.manual import (
    ManualDecision,
    ManualError,
    format_manual_report,
    parse_decisions,
    play_manual,
)
from pogo_sim.policy import ChargedAction, Decision, WaitAction
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.simple_policy import SimplePolicy
from pogo_sim.team import Team
from pogo_sim.team_battle import load_team_battle_config, prepare_team_battle, run_team_battle
from pogo_sim.timeline import DecisionEvent, MoveEvent, SwitchEvent, format_timeline

EXAMPLE = REPO_ROOT / "experiments" / "gl_3v3_example.toml"


@pytest.fixture(scope="module")
def gm():
    return load_gamemaster()


@pytest.fixture(scope="module")
def example():
    return prepare_team_battle(load_team_battle_config(EXAMPLE))


def _one_on_one(gm, shields=(0, 0)):
    azumarill = make_combatant(gm, league_build(gm, "azumarill", 1500, "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), 0)
    medicham = make_combatant(gm, league_build(gm, "medicham", 1500, "COUNTER", ("ICE_PUNCH", "PSYCHIC")), 1)
    return Team((azumarill,), shields=shields[0]), Team((medicham,), shields=shields[1])


class _Wrapped(SimplePolicy):
    """简单规则策略，但前 wait_until 回合什么都不做；放大招时用 charge 的威力；记下问开盾时给的伤害。"""

    def __init__(self, wait_until=0, charge=1.0):
        super().__init__()
        self.wait_until = wait_until
        self.charge = charge
        self.shield_damages = []

    def decide_action(self, view):
        if view.turn < self.wait_until:
            return Decision(WaitAction(), "test: wait")
        decision = super().decide_action(view)
        if isinstance(decision.action, ChargedAction):
            return Decision(replace(decision.action, charge=self.charge), decision.reason)
        return decision

    def decide_shield(self, view, incoming, damage):
        self.shield_damages.append(damage)
        return super().decide_shield(view, incoming, damage)


# ---- 引擎：等待 ----


def test_wait_does_nothing_and_asks_again_next_turn(gm):
    waiter = _Wrapped(wait_until=6)
    result = Battle(_one_on_one(gm), (waiter, SimplePolicy())).run()
    waits = [e.turn for e in result.events if isinstance(e, DecisionEvent) and e.actor == 0 and e.action == "wait"]
    assert waits == [1, 2, 3, 4, 5]  # 冷却保持 0，每回合都再问
    first_move = next(e for e in result.events if isinstance(e, MoveEvent) and e.actor == 0)
    assert first_move.turn == 6 + 3 - 1  # 第 6 回合开始放 3 回合的 Bubble
    # 等待期间能量不变，对手照常出招
    assert [s.sides[0].energy for s in result.snapshots[:5]] == [0] * 5
    assert any(isinstance(e, MoveEvent) and e.actor == 1 and e.turn <= 5 for e in result.events)


def test_wait_in_timeline(gm):
    result = Battle(_one_on_one(gm), (_Wrapped(wait_until=2), SimplePolicy())).run()
    text = format_timeline(result.events, ("Azumarill", "Medicham"), show_decisions=True)
    first = text.splitlines()[0]
    assert first.startswith("T   1  Azumarill") and first.endswith("decides to wait  (test: wait)")


# ---- 引擎：大招威力 ----


def test_charge_scales_damage(gm):
    half = _Wrapped(charge=0.5)
    result = Battle(_one_on_one(gm), (half, SimplePolicy())).run()
    teams = _one_on_one(gm)
    me, opponent = teams[0].members[0], teams[1].members[0]
    charged = [e for e in result.events if isinstance(e, MoveEvent) and e.actor == 0 and e.is_charged]
    assert charged
    for event in charged:
        move = gm.get_move(event.move_id)
        # 两只都没有能力变化的招式（Ice Beam / Play Rough），伤害只看威力
        assert event.charge == 0.5
        assert event.damage == calculate_damage(move, me.damage_side(), opponent.damage_side(), PVPOKE_COMPAT, 0.5)
        assert event.damage < calculate_damage(move, me.damage_side(), opponent.damage_side(), PVPOKE_COMPAT)
    text = format_timeline(result.events, ("Azumarill", "Medicham"))
    assert f"CHARGED {charged[0].move_id} at 50% -> {charged[0].damage} dmg" in text


def test_shield_decision_sees_full_charge_damage(gm):
    """守方开盾时看不到攻方蓄了多少：问开盾时给的是满蓄力的伤害。"""
    defender = _Wrapped()
    result = Battle(_one_on_one(gm, shields=(0, 2)), (_Wrapped(charge=0.25), defender)).run()
    teams = _one_on_one(gm)
    me, opponent = teams[0].members[0], teams[1].members[0]
    first = next(e for e in result.events if isinstance(e, MoveEvent) and e.actor == 0 and e.is_charged)
    full = calculate_damage(gm.get_move(first.move_id), me.damage_side(), opponent.damage_side(), PVPOKE_COMPAT)
    assert defender.shield_damages[0] == full


def test_charge_out_of_range_is_an_error(gm):
    with pytest.raises(ValueError, match="威力要在 25% 到 100% 之间"):
        Battle(_one_on_one(gm), (_Wrapped(charge=0.2), SimplePolicy())).run()
    with pytest.raises(ValueError, match="威力要在"):
        Battle(_one_on_one(gm), (_Wrapped(charge=1.5), SimplePolicy())).run()
    # 规则里可以改下限
    rules = replace(PVPOKE_COMPAT, min_charge=0.1)
    Battle(_one_on_one(gm), (_Wrapped(charge=0.2), SimplePolicy()), rules).run()


# ---- 手动对战 ----


def _auto_choices(result, side):
    """自动对战里 side 方（TeamPolicy）做的每个决定，按引擎问的顺序写成 ManualDecision。"""
    decisions = []
    for event in result.events:
        if isinstance(event, DecisionEvent) and event.actor == side:
            match event.action:
                case "fast":
                    decisions.append(ManualDecision("action", "fast"))
                case "charged":
                    decisions.append(ManualDecision("action", "charged", event.move_id))
                case "switch":
                    decisions.append(ManualDecision("action", "switch", to=event.switch_to))
                case "stay":
                    decisions.append(ManualDecision("zero_turn_switch"))
                case "zero_turn_switch":
                    decisions.append(ManualDecision("zero_turn_switch", to=event.switch_to))
                case "replacement":
                    decisions.append(ManualDecision("replacement", to=event.switch_to))
        elif (
            isinstance(event, MoveEvent) and event.actor != side and event.is_charged and event.shield_reason is not None
        ):
            decisions.append(ManualDecision("shield", shield=event.shielded))
    return decisions


def _plays(result):
    """比较两场用：招式和换人（不看原因）。"""
    return [
        (e.turn, e.actor, e.move_id, e.damage, e.shielded, e.target_slot) if isinstance(e, MoveEvent)
        else (e.turn, e.actor, e.from_slot, e.to_slot, e.kind)
        for e in result.events if isinstance(e, (MoveEvent, SwitchEvent))
    ]


@pytest.mark.parametrize("side", [0, 1])
def test_playing_the_policy_choices_reproduces_the_auto_battle(example, side):
    """玩家照 TeamPolicy 的选择一步步点，打出来的就是自动对战那一场。"""
    auto = run_team_battle(example)
    decisions = _auto_choices(auto, side)
    game = play_manual(example, side, decisions)
    assert game.question is None
    assert _plays(game.result) == _plays(auto)
    assert (game.result.winner, game.result.ratings, game.result.turns) == (auto.winner, auto.ratings, auto.turns)
    # 每一步停下来时，问的正好是下一个决定
    for i in (0, 1, len(decisions) // 2, len(decisions) - 1):
        stopped = play_manual(example, side, decisions[:i])
        assert stopped.question.index == i
        assert stopped.question.kind == decisions[i].kind
        assert any(decisions[i].same_choice(option) for option in stopped.question.options)


def test_first_question(example):
    game = play_manual(example, 0, [])
    question = game.question
    assert (question.index, question.turn, question.kind) == (0, 1, "action")
    assert [(o.action, o.to) for o in question.options] == [("fast", None), ("wait", None), ("switch", 1), ("switch", 2)]
    assert game.battle.events == [] or all(e.actor == 1 for e in game.battle.events)


def test_replay_is_deterministic(example):
    decisions = _auto_choices(run_team_battle(example), 0)[:30]
    a = play_manual(example, 0, decisions)
    b = play_manual(example, 0, decisions)
    assert a.question == b.question
    assert a.battle.events == b.battle.events


def test_shield_question(example):
    auto = run_team_battle(example)
    decisions = _auto_choices(auto, 0)
    first_shield = next(i for i, d in enumerate(decisions) if d.kind == "shield")
    game = play_manual(example, 0, decisions[:first_shield])
    assert game.question.kind == "shield"
    assert game.question.turn == 21  # Swampert 第 21 回合放 Hydro Cannon
    assert [o.shield for o in game.question.options] == [True, False]


def test_manual_choices_change_the_battle(example):
    """不开盾、少放一个大招，结果和自动对战不同；放不满的大招按威力算伤害。"""
    auto = run_team_battle(example)
    decisions = _auto_choices(auto, 0)
    first_shield = next(i for i, d in enumerate(decisions) if d.kind == "shield")
    changed = decisions[:first_shield] + [ManualDecision("shield", shield=False)]
    game = play_manual(example, 0, changed)
    hit = next(e for e in game.battle.events if isinstance(e, MoveEvent) and e.turn == 21 and e.is_charged)
    assert not hit.shielded and hit.damage > 1

    first_charged = next(i for i, d in enumerate(decisions) if d.action == "charged")
    weak = decisions[:first_charged] + [replace(decisions[first_charged], charge=0.4)]
    game = play_manual(example, 0, weak)
    thrown = [e for e in game.battle.events if isinstance(e, MoveEvent) and e.actor == 0 and e.is_charged][-1]
    assert thrown.charge == 0.4


def test_manual_errors(example):
    with pytest.raises(ManualError, match="这里要回答的是出招，得到的是开不开盾"):
        play_manual(example, 0, [ManualDecision("shield", shield=True)])
    with pytest.raises(ManualError, match="现在不能选"):
        play_manual(example, 0, [ManualDecision("action", "charged", "ICE_BEAM")])  # 第 1 回合没有能量
    with pytest.raises(ManualError, match="现在不能选"):
        play_manual(example, 0, [ManualDecision("action", "switch", to=0)])  # 在场的那只
    decisions = _auto_choices(run_team_battle(example), 0)
    first_charged = next(i for i, d in enumerate(decisions) if d.action == "charged")
    too_weak = decisions[:first_charged] + [replace(decisions[first_charged], charge=0.2)]
    with pytest.raises(ManualError, match="威力要在 25% 到 100% 之间"):
        play_manual(example, 0, too_weak)
    with pytest.raises(ManualError, match="对战已经结束，后面还多了 1 个决定"):
        play_manual(example, 0, decisions + [ManualDecision("action", "fast")])
    with pytest.raises(ManualError, match="要是 0 或 1"):
        play_manual(example, 2, [])


def test_parse_decisions():
    parsed = parse_decisions([
        {"kind": "action", "action": "charged", "move_id": "ICE_BEAM", "charge": 0.5},
        {"kind": "shield", "shield": True},
        {"kind": "zero_turn_switch", "to": None},
        {"kind": "replacement", "to": 2},
        {"kind": "action", "action": "wait"},
    ])
    assert parsed == [
        ManualDecision("action", "charged", "ICE_BEAM", 0.5),
        ManualDecision("shield", shield=True),
        ManualDecision("zero_turn_switch"),
        ManualDecision("replacement", to=2),
        ManualDecision("action", "wait"),
    ]
    bad = [
        ("not a list", "要写成列表"),
        ([1], "要写成表"),
        ([{"kind": "dance"}], "kind 要是"),
        ([{"kind": "action", "action": "dance"}], "action 要是"),
        ([{"kind": "action", "action": "fast", "extra": 1}], "不认识的字段 extra"),
        ([{"kind": "replacement", "to": "1"}], "to 要写整数"),
        ([{"kind": "shield", "shield": "yes"}], "shield 要写"),
        ([{"kind": "action", "action": "charged", "move_id": "X", "charge": "half"}], "charge 要写数字"),
    ]
    for raw, message in bad:
        with pytest.raises(ManualError, match=message):
            parse_decisions(raw)


def test_manual_report(example):
    decisions = _auto_choices(run_team_battle(example), 1)
    game = play_manual(example, 1, decisions)
    report = format_manual_report(example, game.result, 1)
    assert "Team B 由玩家手动操作" in report
    assert "- 策略：玩家手动操作；配置里的这一项没有用到：TeamPolicy，默认参数" in report
    assert "## 对位分段" in report and "## 时间线" in report
    assert "(player)" in report
