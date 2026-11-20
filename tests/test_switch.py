"""换人的单项规则测试（3v3-b，docs/mechanics.md 13.5）：每个测试搭一个最小的场景，只看一条规则。

和 tests/test_battle.py 一样，需要特定局面时直接改对战开始前的 HP / 能量 / 冷却。
HP 设得很大（BIG）是为了让对战不因倒下而结束，只看换人本身。
"""

from dataclasses import replace

import pytest

from pogo_sim.battle import Battle, BattleResult, battle_rating, team_rating
from pogo_sim.combatant import Combatant, PokemonBuild, league_build, make_combatant
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import ScriptedCharged, ScriptedPolicy, ScriptedReplacement
from pogo_sim.report import format_result
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.simple_policy import SimplePolicy
from pogo_sim.stats import IVs
from pogo_sim.team import Team
from pogo_sim.timeline import (
    CancelledEvent,
    DecisionEvent,
    Event,
    FaintEvent,
    MoveEvent,
    SwitchEvent,
    format_timeline,
    team_names,
)

BIG = 100_000

# 常用的几只：快招回合数写在名字旁边
REGISTEEL = ("registeel", "LOCK_ON", ("FOCUS_BLAST",))  # 1 回合
AZUMARILL = ("azumarill", "BUBBLE", ("ICE_BEAM",))  # 3 回合
MEDICHAM = ("medicham", "COUNTER", ("ICE_PUNCH",))  # 2 回合
SWAMPERT = ("swampert", "MUD_SHOT", ("HYDRO_CANNON",))  # 2 回合
MAGIKARP = ("magikarp", "SPLASH", ("STRUGGLE",))  # 4 回合，威力 0（伤害 1）


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _mon(gm: GameMaster, index: int, spec: tuple[str, str, tuple[str, ...]], hp: int = BIG) -> Combatant:
    species, fast, charged = spec
    combatant = make_combatant(gm, PokemonBuild(species, 40, IVs(15, 15, 15), fast, charged), index)
    combatant.hp = hp
    return combatant


def _team(gm: GameMaster, index: int, *specs: tuple[str, str, tuple[str, ...]], shields: int = 0) -> Team:
    return Team(tuple(_mon(gm, index, spec) for spec in specs), shields)


def _play(battle: Battle, turns: int) -> None:
    for _ in range(turns):
        battle.play_turn()


def _of(events: list[Event], kind: type, turn: int | None = None) -> list:
    return [e for e in events if isinstance(e, kind) and (turn is None or e.turn == turn)]


# ---- 主动换人 ----


def test_active_switch(gm: GameMaster) -> None:
    """主动换人占用这一回合；换下去的保留 HP、能量和概率计数器，能力等级清零；开始 45 秒冷却。"""
    mine = _team(gm, 0, AZUMARILL, REGISTEEL)
    azumarill = mine.members[0]
    azumarill.energy = 30
    azumarill.atk_stage, azumarill.def_stage = 2, -1
    azumarill.chance_meters["TEST"] = 0.375  # 计数器换下场不清零（Q17）
    battle = Battle((mine, _team(gm, 1, MEDICHAM)), (ScriptedPolicy(switches={1: 1}), ScriptedPolicy()))

    _play(battle, 2)
    events = battle.events
    assert [(e.kind, e.from_slot, e.to_slot, e.switch_timer_ms) for e in _of(events, SwitchEvent)] == [
        ("switch", 0, 1, 45_000)
    ]
    assert [e.actor for e in _of(events, MoveEvent, turn=1)] == []  # 第 1 回合我方没出招
    # 换上来的第 2 回合就能出招
    assert [(e.actor, e.move_id) for e in _of(events, DecisionEvent, turn=2) if e.actor == 0] == [(0, "LOCK_ON")]
    assert (azumarill.hp, azumarill.energy, azumarill.atk_stage, azumarill.def_stage) == (BIG, 30, 0, 0)
    assert azumarill.chance_meters["TEST"] == 0.375
    assert battle.snapshots[0].sides[0].active == 1


def test_switch_cooldown_counts_turns_charged_moves_and_waits(gm: GameMaster) -> None:
    """换人冷却按对战时间走：普通回合 0.5 秒，大招 10 秒（Q13、Q14）。"""
    theirs = _team(gm, 1, MEDICHAM)
    theirs.members[0].energy = 100
    battle = Battle(
        (_team(gm, 0, REGISTEEL, AZUMARILL), theirs),
        (ScriptedPolicy(switches={1: 1}), ScriptedPolicy(charged={3: ScriptedCharged(3, "ICE_PUNCH")})),
    )
    _play(battle, 4)
    # 第 1 回合换人 → 45 秒；第 2、3 回合开头各扣 0.5 秒；第 3 回合有大招，第 4 回合开头扣 10 秒
    assert [s.sides[0].switch_timer_ms for s in battle.snapshots] == [45_000, 44_500, 44_000, 34_000]


@pytest.mark.parametrize(("switch_back_turn", "allowed"), [(90, False), (91, True)])
def test_cannot_switch_until_cooldown_ends(gm: GameMaster, switch_back_turn: int, allowed: bool) -> None:
    """第 1 回合换人，只用快招时要 90 回合（45 秒）后才能再换：第 91 回合可以，第 90 回合不行。"""
    battle = Battle(
        (_team(gm, 0, REGISTEEL, REGISTEEL), _team(gm, 1, MAGIKARP)),
        (ScriptedPolicy(switches={1: 1, switch_back_turn: 0}), ScriptedPolicy()),
    )
    if not allowed:
        with pytest.raises(ValueError, match="现在不能换"):
            _play(battle, switch_back_turn)
        return
    _play(battle, switch_back_turn)
    assert [(e.turn, e.to_slot) for e in _of(battle.events, SwitchEvent)] == [(1, 1), (91, 0)]


def test_switch_target_must_be_on_the_bench(gm: GameMaster) -> None:
    mine = _team(gm, 0, REGISTEEL, AZUMARILL, MEDICHAM)
    mine.members[1].hp = 0
    for target, message in [(0, "不在后备里"), (1, "已经倒下")]:
        battle = Battle((mine, _team(gm, 1, MAGIKARP)), (ScriptedPolicy(switches={1: target}), ScriptedPolicy()))
        with pytest.raises(ValueError, match=message):
            battle.play_turn()


# ---- 换人先于同回合的伤害（官方说明，PvPoke 相同）----


def test_incoming_takes_fast_move_that_lands_this_turn(gm: GameMaster) -> None:
    """在对方快招完成的回合换人：快招打在换上来的那只身上，按它的属性和防御算伤害。"""
    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL), _team(gm, 1, MEDICHAM)
    battle = Battle((mine, theirs), (ScriptedPolicy(switches={2: 1}), ScriptedPolicy()))
    _play(battle, 2)  # Counter 第 1 回合开始、第 2 回合结算；我方第 2 回合换人
    counter = _of(battle.events, MoveEvent, turn=2)
    assert [(e.move_id, e.target_slot) for e in counter] == [("COUNTER", 1)]
    medicham, azumarill = theirs.members[0], mine.members[1]
    expected = calculate_damage(medicham.fast_move, medicham.damage_side(), azumarill.damage_side())
    assert counter[0].damage == expected
    assert azumarill.hp == BIG - expected and mine.members[0].hp == BIG


@pytest.mark.parametrize("use_shield", [True, False])
def test_incoming_takes_charged_move_started_this_turn(gm: GameMaster, use_shield: bool) -> None:
    """在对方大招开始的回合换人：大招打在换上来的那只身上，开不开盾也是问它（盾是全队的）。"""
    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL, shields=1), _team(gm, 1, MEDICHAM)
    theirs.members[0].energy = 100
    policies = (
        ScriptedPolicy(switches={1: 1}, shields={1: use_shield}),
        ScriptedPolicy(charged={1: ScriptedCharged(1, "ICE_PUNCH")}),
    )
    battle = Battle((mine, theirs), policies)
    battle.play_turn()
    [ice_punch] = [e for e in _of(battle.events, MoveEvent) if e.is_charged]
    assert (ice_punch.target_slot, ice_punch.shielded) == (1, use_shield)
    assert mine.shields == (0 if use_shield else 1)
    assert mine.members[0].hp == BIG


# ---- 0 回合换人（大招后的空回合）----


@pytest.mark.parametrize("thrower", [0, 1])
def test_zero_turn_switch_after_charged_move(gm: GameMaster, thrower: int) -> None:
    """大招后的空回合可以换人，不花回合，放大招的一方也可以（Q15）；会开始换人冷却。"""
    teams = (_team(gm, 0, REGISTEEL, AZUMARILL), _team(gm, 1, REGISTEEL))
    teams[thrower].members[0].energy = 100
    policies = [ScriptedPolicy(switches={2: 1}), ScriptedPolicy()]
    policies[thrower] = replace(policies[thrower], charged={1: ScriptedCharged(1, "FOCUS_BLAST")})
    battle = Battle(teams, tuple(policies))
    _play(battle, 3)

    assert [(e.turn, e.kind, e.switch_timer_ms) for e in _of(battle.events, SwitchEvent)] == [
        (2, "zero_turn", 45_000)
    ]
    assert _of(battle.events, MoveEvent, turn=2) == []  # 空回合双方都不出招
    # 第 3 回合双方同时行动
    assert sorted(e.actor for e in _of(battle.events, DecisionEvent, turn=3)) == [0, 1]


@pytest.mark.parametrize(("hits", "expected_target"), [("outgoing", 0), ("incoming", 1)])
def test_floating_fast_move_and_zero_turn_switch(gm: GameMaster, hits: str, expected_target: int) -> None:
    """大招后 0 回合换人时，漂浮的快招打谁（Q3）：默认打在换下去的那只身上（PvPoke），可改成官方字面。"""
    mine, theirs = _team(gm, 0, REGISTEEL, MEDICHAM), _team(gm, 1, AZUMARILL)
    mine.members[0].energy = 100
    theirs.members[0].cooldown = 2  # Bubble 在第 2 回合开始，本该第 4 回合结算
    rules = replace(PVPOKE_COMPAT, zero_turn_switch_floating_fast_hits=hits)
    policies = (
        ScriptedPolicy(charged={2: ScriptedCharged(2, "FOCUS_BLAST")}, switches={3: 1}),
        ScriptedPolicy(),
    )
    battle = Battle((mine, theirs), policies, rules)
    _play(battle, 3)
    turn3 = [e for e in battle.events if e.turn == 3 and isinstance(e, MoveEvent | SwitchEvent)]
    bubble = next(e for e in turn3 if isinstance(e, MoveEvent))
    assert bubble.move_id == "BUBBLE" and bubble.target_slot == expected_target
    order = ["move" if isinstance(e, MoveEvent) else "switch" for e in turn3]
    assert order == (["move", "switch"] if hits == "outgoing" else ["switch", "move"])


def test_floating_fast_move_knocks_out_before_zero_turn_switch(gm: GameMaster) -> None:
    """漂浮快招先把要换下去的打倒：换人照样进行，但算倒下后换人——不开始冷却，也不再多一个换人回合。"""
    mine, theirs = _team(gm, 0, REGISTEEL, MEDICHAM), _team(gm, 1, AZUMARILL)
    mine.members[0].energy = 100
    mine.members[0].hp = 1
    theirs.members[0].cooldown = 2
    policies = (
        ScriptedPolicy(charged={2: ScriptedCharged(2, "FOCUS_BLAST")}, switches={3: 1}),
        ScriptedPolicy(),
    )
    battle = Battle((mine, theirs), policies)
    _play(battle, 4)
    assert [(e.turn, e.slot) for e in _of(battle.events, FaintEvent)] == [(3, 0)]
    assert [(e.turn, e.kind, e.switch_timer_ms) for e in _of(battle.events, SwitchEvent)] == [(3, "zero_turn", 0)]
    assert not battle.replacement_turn
    assert sorted(e.actor for e in _of(battle.events, DecisionEvent, turn=4)) == [0, 1]


# ---- 倒下后换人 ----


def test_replacement_after_faint(gm: GameMaster) -> None:
    """倒下后：清空排队中的行动；下一回合是换人回合，存活的一方不出招；换上后双方同时行动。

    倒下后换人不开始换人冷却；选人等的时间计入对战时间，也从双方的换人冷却里扣（Q14）。
    """
    mine, theirs = _team(gm, 0, AZUMARILL, REGISTEEL), _team(gm, 1, MEDICHAM, SWAMPERT)
    mine.members[0].hp = 1  # 第 2 回合被 Counter 打倒；它第 1 回合开始的 Bubble 还没结算
    theirs.switch_timer_ms = 20_000
    policies = (ScriptedPolicy(replacements={3: ScriptedReplacement(1, wait_ms=4_000)}), ScriptedPolicy())
    battle = Battle((mine, theirs), policies, replace(PVPOKE_COMPAT, switch_during_opponent_replacement=False))
    _play(battle, 4)
    events = battle.events

    assert [(e.turn, e.actor, e.slot) for e in _of(events, FaintEvent)] == [(2, 0, 0)]
    assert [(e.actor, e.move_id, e.reason) for e in _of(events, CancelledEvent)] == [
        (0, "BUBBLE", "cleared after a faint")
    ]
    assert [(e.turn, e.kind, e.to_slot, e.switch_timer_ms, e.wait_ms) for e in _of(events, SwitchEvent)] == [
        (3, "replacement", 1, 0, 4_000)
    ]
    assert [e.actor for e in _of(events, DecisionEvent, turn=3)] == [0]  # 只有选人，存活的一方不出招
    assert sorted(e.actor for e in _of(events, DecisionEvent, turn=4)) == [0, 1]
    assert battle.elapsed_ms == 500 + 500 + (500 + 4_000) + 500
    # 第 4 回合开头扣掉前三个回合（含 4 秒等待）
    assert battle.snapshots[3].sides[1].switch_timer_ms == 20_000 - 500 - 500 - 4_500


def test_replacement_wait_is_capped(gm: GameMaster) -> None:
    mine = _team(gm, 0, AZUMARILL, REGISTEEL)
    mine.members[0].hp = 1
    battle = Battle(
        (mine, _team(gm, 1, MEDICHAM)),
        (ScriptedPolicy(replacements={3: ScriptedReplacement(1, wait_ms=13_001)}), ScriptedPolicy()),
    )
    with pytest.raises(ValueError, match="0 到 13000"):
        _play(battle, 3)


@pytest.mark.parametrize("allowed", [True, False])
def test_survivor_switch_during_opponent_replacement(gm: GameMaster, allowed: bool) -> None:
    """对手倒下、正在换人的那一回合，存活的一方可以同时换人，不花回合（Q21，用户确认；PvPoke 相同）。"""
    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL), _team(gm, 1, MEDICHAM, SWAMPERT)
    mine.members[0].hp = 1
    survivor = ScriptedPolicy(switches={3: 1})
    rules = replace(PVPOKE_COMPAT, switch_during_opponent_replacement=allowed)
    battle = Battle((mine, theirs), (ScriptedPolicy(), survivor), rules)
    _play(battle, 3)
    switches = [(e.actor, e.kind) for e in _of(battle.events, SwitchEvent, turn=3)]
    if allowed:
        assert switches == [(0, "replacement"), (1, "zero_turn")]
        assert theirs.switch_timer_ms == 45_000
    else:
        assert switches == [(0, "replacement")]
        assert survivor.unused_switches() == [3]


def test_survivor_cannot_switch_during_opponent_replacement_on_cooldown(gm: GameMaster) -> None:
    """同上，但存活的一方还在换人冷却中：不能换，策略也不会被问到（Q21）。"""
    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL), _team(gm, 1, MEDICHAM, SWAMPERT)
    mine.members[0].hp = 1
    theirs.switch_timer_ms = 10_000
    survivor = ScriptedPolicy(switches={3: 1})
    battle = Battle((mine, theirs), (ScriptedPolicy(), survivor))
    _play(battle, 3)
    assert [(e.actor, e.kind) for e in _of(battle.events, SwitchEvent, turn=3)] == [(0, "replacement")]
    assert survivor.unused_switches() == [3]
    assert theirs.active == 0


def test_double_knockout_both_replace(gm: GameMaster) -> None:
    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL), _team(gm, 1, REGISTEEL, MEDICHAM)
    mine.members[0].hp = theirs.members[0].hp = 1
    battle = Battle((mine, theirs), (ScriptedPolicy(), ScriptedPolicy()))
    _play(battle, 3)
    assert [(e.turn, e.actor) for e in _of(battle.events, FaintEvent)] == [(1, 0), (1, 1)]
    assert [(e.turn, e.actor, e.kind) for e in _of(battle.events, SwitchEvent)] == [
        (2, 0, "replacement"),
        (2, 1, "replacement"),
    ]
    assert sorted(e.actor for e in _of(battle.events, DecisionEvent, turn=3)) == [0, 1]


# ---- 胜负 ----


def test_team_defeated_loses(gm: GameMaster) -> None:
    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL), _team(gm, 1, MEDICHAM)
    mine.members[1].hp = 0
    mine.members[0].hp = 1
    result = Battle((mine, theirs), (ScriptedPolicy(), ScriptedPolicy())).run()
    assert (result.winner, result.remaining, result.timed_out) == (1, (0, 1), False)


def test_last_pokemon_fainting_together_is_a_draw(gm: GameMaster) -> None:
    """最后一只同时倒下：平局（Q18；PvPoke 训练模式会判负）。"""
    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL), _team(gm, 1, REGISTEEL, MEDICHAM)
    for team in (mine, theirs):
        team.members[0].hp = 1
        team.members[1].hp = 0
    result = Battle((mine, theirs), (ScriptedPolicy(), ScriptedPolicy())).run()
    assert (result.winner, result.remaining, result.ratings) == (None, (0, 0), (500, 500))


@pytest.mark.parametrize(
    ("timeout_result", "expected_winner"),
    [("draw", None), ("more_remaining", 0), ("rating", 1)],
)
def test_timeout_result(gm: GameMaster, timeout_result: str, expected_winner: int | None) -> None:
    """时间到、双方都还有宝可梦：默认平局（游戏规则，Q19）；评估时可以按剩余只数或评分判。

    这里我方剩 2 只但都是残血，对方只剩 1 只满血：按只数我方赢，按评分对方赢。
    Splash 每次只打 1 点，时限缩短到 5 秒，谁都打不倒谁。
    """
    mine, theirs = _team(gm, 0, MAGIKARP, MAGIKARP), _team(gm, 1, MAGIKARP, MAGIKARP)
    for member in mine.members:
        member.hp = member.stats.hp * 3 // 10
    theirs.members[0].hp = theirs.members[0].stats.hp
    theirs.members[1].hp = 0
    rules = replace(PVPOKE_COMPAT, timeout_result=timeout_result, time_limit_ms=5_000)
    result = Battle((mine, theirs), (ScriptedPolicy(), ScriptedPolicy()), rules).run()
    assert result.timed_out and result.remaining == (2, 1)
    assert result.ratings[1] > result.ratings[0]
    assert result.winner == expected_winner


def test_team_rating(gm: GameMaster) -> None:
    """D1：每队一只时与 PvPoke 的 1v1 评分逐位相同；三只时按全队平均。"""
    for hp_a, hp_b in [(1, 1), (37, 150), (200, 3), (0, 99)]:
        a, b = _mon(gm, 0, AZUMARILL, hp=hp_a), _mon(gm, 1, MEDICHAM, hp=hp_b)
        assert team_rating(Team((a,), 0), Team((b,), 0)) == battle_rating(a, b)

    mine, theirs = _team(gm, 0, REGISTEEL, AZUMARILL, MEDICHAM), _team(gm, 1, REGISTEEL, AZUMARILL, MEDICHAM)
    for team, fractions in [(mine, (1, 0.5, 0)), (theirs, (0, 0, 0.25))]:
        for member, fraction in zip(team.members, fractions):
            member.hp = round(member.stats.hp * fraction)
    expected = 500 + 500 * (sum(m.hp / m.stats.hp for m in mine.members)
                            - sum(m.hp / m.stats.hp for m in theirs.members)) / 3
    assert team_rating(mine, theirs) == pytest.approx(expected, abs=1)
    assert team_rating(mine, theirs) + team_rating(theirs, mine) in (999, 1000)


def test_cmp_tie_uses_current_pair(gm: GameMaster) -> None:
    """CMP 攻击是否相等，按当前在场的两只判断（Q20）。"""
    mine, theirs = _team(gm, 0, MEDICHAM, AZUMARILL), _team(gm, 1, AZUMARILL)
    battle = Battle((mine, theirs), (ScriptedPolicy(switches={1: 1}), ScriptedPolicy()))
    assert battle._cmp_decides_order()  # Medicham 对 Azumarill：攻击不同，有先后
    battle.play_turn()
    assert not battle._cmp_decides_order()  # 换成同样配置的 Azumarill：攻击相等


# ---- 时间线和结果 ----


def test_timeline_and_result_text(gm: GameMaster) -> None:
    mine, theirs = _team(gm, 0, AZUMARILL, REGISTEEL), _team(gm, 1, MEDICHAM)
    mine.members[0].hp = 1
    mine.members[1].hp = mine.members[1].stats.hp
    theirs.members[0].hp = 1
    battle = Battle((mine, theirs), (ScriptedPolicy(), ScriptedPolicy()))
    result: BattleResult = battle.run()
    lines = format_timeline(result.events, team_names((mine, theirs))).splitlines()
    assert "T   2  Azumarill       FAINTS" in lines
    assert "T   3  Azumarill       sends in Registeel" in lines
    assert any(line.startswith("T   4  Registeel       fast LOCK_ON") for line in lines)
    assert format_result(result, ("Team A", "Team B")).startswith(
        "Team A wins: rating 750 vs 250, Pokemon left 1 vs 0, shields left 0 vs 0, 4 turns"
    )


def test_full_3v3_with_simple_policy(gm: GameMaster) -> None:
    """README 里的 3v3 例子：双方都用简单规则策略（不主动换人，倒下后按顺序换上）。

    结果来自本项目自己的引擎和策略，没有 PvPoke 的结果可以对照；策略改动后如果变了，要确认变化合理再更新。
    """
    def team(index: int, *members: tuple[str, str, tuple[str, ...]]) -> Team:
        return Team(
            tuple(make_combatant(gm, league_build(gm, s, 1500, f, c), index) for s, f, c in members), shields=2
        )

    a = team(0, ("azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), ("medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC")),
             ("registeel", "LOCK_ON", ("FOCUS_BLAST", "ZAP_CANNON")))
    b = team(1, ("swampert", "MUD_SHOT", ("HYDRO_CANNON", "EARTHQUAKE")),
             ("altaria", "DRAGON_BREATH", ("SKY_ATTACK", "MOONBLAST")), ("trevenant", "SHADOW_CLAW", ("SEED_BOMB", "SHADOW_BALL")))
    result = Battle((a, b), (SimplePolicy(), SimplePolicy())).run()
    assert format_result(result, ("Team A", "Team B")) == (
        "Team B wins: rating 435 vs 564, Pokemon left 0 vs 1, shields left 0 vs 0, 130 turns"
    )
    assert [(e.turn, e.actor, e.to_slot) for e in _of(result.events, SwitchEvent)] == [
        (54, 1, 1), (56, 0, 1), (85, 0, 2), (103, 1, 2),
    ]
