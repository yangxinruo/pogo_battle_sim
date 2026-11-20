"""回合结算的单项规则测试：每个测试搭一个最小的场景，只看一条规则。

这些测试不依赖 PvPoke 的参考数据，方便单独读懂每条规则。需要特定局面时，
直接改对战开始前的 HP / 能量（测试里才这么做）。
"""

from dataclasses import replace

import pytest

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.combatant import Combatant, PokemonBuild, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import ScriptedCharged, ScriptedPolicy
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.stats import IVs
from pogo_sim.team import Team
from pogo_sim.timeline import CancelledEvent, DecisionEvent, MoveEvent

MAX_IVS = IVs(15, 15, 15)


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _combatant(
    gm: GameMaster,
    index: int,
    species: str,
    fast: str,
    charged: tuple[str, ...],
    level: float = 40,
) -> Combatant:
    build = PokemonBuild(species, level, MAX_IVS, fast, charged)
    return make_combatant(gm, build, index)


def _charged_on(turn: int, move_id: str) -> ScriptedPolicy:
    return ScriptedPolicy(charged={turn: ScriptedCharged(turn, move_id)})


def _moves(result: BattleResult) -> list[tuple[int, int, str, int]]:
    """(回合, 出招方, 招式, 伤害)"""
    return [(e.turn, e.actor, e.move_id, e.damage) for e in result.events if isinstance(e, MoveEvent)]


def _cancelled(result: BattleResult) -> list[tuple[int, int, str]]:
    return [(e.turn, e.actor, e.move_id) for e in result.events if isinstance(e, CancelledEvent)]


def _teams(a: Combatant, b: Combatant, shields: tuple[int, int] = (0, 0)) -> tuple[Team, Team]:
    """1v1：每队一只。"""
    return Team((a,), shields[0]), Team((b,), shields[1])


def _run(a: Combatant, b: Combatant, pa: ScriptedPolicy, pb: ScriptedPolicy,
         rules: BattleRules = PVPOKE_COMPAT, seed: int | None = None,
         shields: tuple[int, int] = (0, 0)) -> BattleResult:
    return Battle(_teams(a, b, shields), (pa, pb), rules, seed).run()


def test_simultaneous_fast_moves_both_land(gm: GameMaster) -> None:
    """同回合结算的快招都生效，即使双方都因此倒下（1 回合快招必定打平）。"""
    a = _combatant(gm, 0, "registeel", "LOCK_ON", ("FOCUS_BLAST",))
    b = _combatant(gm, 1, "altaria", "DRAGON_BREATH", ("SKY_ATTACK",))
    a.hp = b.hp = 1
    result = _run(a, b, ScriptedPolicy(), ScriptedPolicy())
    assert [(turn, actor, move) for turn, actor, move, _ in _moves(result)] == [
        (1, 0, "LOCK_ON"),
        (1, 1, "DRAGON_BREATH"),
    ]
    assert a.is_fainted and b.is_fainted
    assert result.turns == 1


def test_charged_move_resolves_before_fast_move(gm: GameMaster) -> None:
    """大招先于同回合的快招结算；被大招打倒的一方，同回合的快招作废（Q5）。"""
    a = _combatant(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM",))
    b = _combatant(gm, 1, "registeel", "LOCK_ON", ("FOCUS_BLAST",))
    a.energy = 100
    b.hp = 1
    result = _run(a, b, _charged_on(1, "ICE_BEAM"), ScriptedPolicy())
    assert [(turn, actor, move) for turn, actor, move, _ in _moves(result)] == [(1, 0, "ICE_BEAM")]
    assert _cancelled(result) == [(1, 1, "LOCK_ON")]
    assert a.hp == a.stats.hp


def test_cmp_higher_attack_goes_first(gm: GameMaster) -> None:
    """同回合双方放大招：攻击高的先结算；后手被打倒则大招作废。"""
    a = _combatant(gm, 0, "registeel", "LOCK_ON", ("FOCUS_BLAST",))
    b = _combatant(gm, 1, "machamp", "COUNTER", ("CROSS_CHOP",))
    assert b.stats.atk > a.stats.atk
    a.energy = b.energy = 100
    a.hp = b.hp = 1
    result = _run(a, b, _charged_on(1, "FOCUS_BLAST"), _charged_on(1, "CROSS_CHOP"))
    assert [(turn, actor, move) for turn, actor, move, _ in _moves(result)] == [(1, 1, "CROSS_CHOP")]
    assert _cancelled(result) == [(1, 0, "FOCUS_BLAST")]
    assert a.is_fainted and not b.is_fainted


def test_cmp_tie_both_fire_by_default(gm: GameMaster) -> None:
    """攻击完全相同（镜像）时没有先后，双方大招都生效（PvPoke 的做法）。"""
    a = _combatant(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM",))
    b = _combatant(gm, 1, "azumarill", "BUBBLE", ("ICE_BEAM",))
    a.energy = b.energy = 100
    a.hp = b.hp = 1
    result = _run(a, b, _charged_on(1, "ICE_BEAM"), _charged_on(1, "ICE_BEAM"))
    assert [(turn, actor) for turn, actor, _, _ in _moves(result)] == [(1, 0), (1, 1)]
    assert a.is_fainted and b.is_fainted


def test_cmp_tie_random_option(gm: GameMaster) -> None:
    """开关 cmp_tie="random"：随机决定先后，后手作废；同一个种子结果相同。"""
    rules = replace(PVPOKE_COMPAT, cmp_tie="random")
    outcomes = set()
    for seed in range(20):
        a = _combatant(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM",))
        b = _combatant(gm, 1, "azumarill", "BUBBLE", ("ICE_BEAM",))
        a.energy = b.energy = 100
        a.hp = b.hp = 1
        result = _run(a, b, _charged_on(1, "ICE_BEAM"), _charged_on(1, "ICE_BEAM"), rules, seed)
        assert len(_moves(result)) == 1 and len(_cancelled(result)) == 1
        outcomes.add(_moves(result)[0][1])
    assert outcomes == {0, 1}  # 20 个种子里两边都赢过


def test_charged_move_takes_two_turns(gm: GameMaster) -> None:
    """第 T 回合放大招：T+1 是空回合（双方都不能出新招），T+2 双方同时恢复行动。"""
    a = _combatant(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM",))
    b = _combatant(gm, 1, "medicham", "COUNTER", ("ICE_PUNCH",))
    a.energy = 100
    result = _run(a, b, _charged_on(1, "ICE_BEAM"), ScriptedPolicy())
    decision_turns = {(e.turn, e.actor) for e in result.events if isinstance(e, DecisionEvent)}
    assert (2, 0) not in decision_turns and (2, 1) not in decision_turns
    assert (3, 0) in decision_turns and (3, 1) in decision_turns


def test_fast_move_started_on_charged_turn_lands_next_turn(gm: GameMaster) -> None:
    """对手在大招当回合开始的快招（这里 3 回合的 Bubble），在 T+1 就结算，不用等满（Sneak）。"""
    a = _combatant(gm, 0, "medicham", "COUNTER", ("ICE_PUNCH",))
    b = _combatant(gm, 1, "azumarill", "BUBBLE", ("ICE_BEAM",))
    a.energy = 100
    result = _run(a, b, _charged_on(1, "ICE_PUNCH"), ScriptedPolicy())
    first_bubble = next(m for m in _moves(result) if m[2] == "BUBBLE")
    assert first_bubble[0] == 2  # 正常要到第 3 回合


def test_shield_blocks_damage_but_self_debuff_applies(gm: GameMaster) -> None:
    """被挡下的大招只造成 1 点伤害；Close Combat 对自己的降防仍然生效。"""
    a = _combatant(gm, 0, "machamp", "COUNTER", ("CLOSE_COMBAT",))
    b = _combatant(gm, 1, "registeel", "LOCK_ON", ("FOCUS_BLAST",))
    a.energy = 100
    result = _run(a, b, _charged_on(1, "CLOSE_COMBAT"), ScriptedPolicy(shields={1: True}), shields=(0, 1))
    close_combat = next(e for e in result.events if isinstance(e, MoveEvent) and e.move_id == "CLOSE_COMBAT")
    assert close_combat.damage == 1 and close_combat.shielded
    assert result.snapshots[0].sides[1].shields == 0
    assert result.snapshots[0].sides[0].def_stage == -2


@pytest.mark.parametrize(("apply_when_shielded", "expected_stage"), [(True, -1), (False, 0)])
def test_opponent_debuff_through_shield_option(
    gm: GameMaster, apply_when_shielded: bool, expected_stage: int
) -> None:
    """Icy Wind 被挡下时是否仍降对手攻击，由开关决定（默认生效，Q6）。"""
    rules = replace(PVPOKE_COMPAT, opponent_effects_apply_when_shielded=apply_when_shielded)
    a = _combatant(gm, 0, "dewgong", "ICE_SHARD", ("ICY_WIND",))
    b = _combatant(gm, 1, "swampert", "MUD_SHOT", ("HYDRO_CANNON",))
    a.energy = 100
    result = _run(a, b, _charged_on(1, "ICY_WIND"), ScriptedPolicy(shields={1: True}), rules, shields=(0, 1))
    assert result.snapshots[0].sides[1].atk_stage == expected_stage


@pytest.mark.parametrize(
    ("move_id", "expected"),
    [
        ("NIGHT_SLASH", [False] * 6 + [True] + [False] * 7 + [True]),  # 12.5%：第 7、15 次
        ("ANCIENT_POWER", [False] * 9 + [True]),  # 10%：第 10 次（浮点累加，见下）
    ],
)
def test_pvpoke_chance_counter(gm: GameMaster, move_id: str, expected: list[bool]) -> None:
    """PvPoke 的确定性计数器：初始值为概率本身，每用一次加上概率，跨过整数时触发。

    直接调用引擎内部的 _effect_triggers，只为把计数规则写清楚。
    12.5%：初始 0.125，第 7 次用后正好累计到 1.0，第 7 次触发。
    10%：初始 0.1，第 9 次用后浮点累计是 0.9999999999999999（不到 1），所以第 10 次才触发。
    这里和 PvPoke 用完全相同的浮点运算，结果一致。
    """
    species = {"NIGHT_SLASH": ("obstagoon", "COUNTER"), "ANCIENT_POWER": ("mamoswine", "POWDER_SNOW")}
    name, fast = species[move_id]
    a = _combatant(gm, 0, name, fast, (move_id,))
    b = _combatant(gm, 1, "registeel", "LOCK_ON", ("FOCUS_BLAST",))
    battle = Battle(_teams(a, b), (ScriptedPolicy(), ScriptedPolicy()))
    move = gm.get_move(move_id)
    assert [battle._effect_triggers(move, a, None) for _ in expected] == expected


def test_scripted_charged_without_energy_falls_back_to_fast(gm: GameMaster) -> None:
    """剧本要放大招但能量不够时改用快招（PvPoke 沙盒模式也是这样）。"""
    a = _combatant(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM",))
    b = _combatant(gm, 1, "medicham", "COUNTER", ("ICE_PUNCH",))
    result = _run(a, b, _charged_on(1, "ICE_BEAM"), ScriptedPolicy())
    first = next(e for e in result.events if isinstance(e, DecisionEvent) and e.actor == 0)
    assert first.action == "fast" and "energy 0 < 55" in first.reason


def test_time_limit(gm: GameMaster) -> None:
    """对战时间超过 240 秒结束：只用快招时是第 481 回合（PvPoke 判断 time > 240000）。"""
    a = _combatant(gm, 0, "magikarp", "SPLASH", ("STRUGGLE",))
    b = _combatant(gm, 1, "magikarp", "SPLASH", ("STRUGGLE",))
    a.hp = b.hp = 10_000
    result = _run(a, b, ScriptedPolicy(), ScriptedPolicy())
    assert result.timed_out
    assert result.turns == 481
    assert result.elapsed_ms == 240_500


def test_shedinja_has_ten_hp(gm: GameMaster) -> None:
    shedinja = _combatant(gm, 0, "shedinja", "BUG_BITE", ("SHADOW_SNEAK",))
    assert shedinja.stats.hp == 10 and shedinja.hp == 10
