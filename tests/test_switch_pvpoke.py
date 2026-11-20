"""换人结算对照 PvPoke（3v3-c）：同一个剧本分别交给 PvPoke 和我们的引擎，逐回合比较双方全队的状态。

参考数据的来历见 tools/pvpoke_ref/export_switch_reference.js：结算用 PvPoke 的 Battle.step()，
倒下后换人、全队的盾和换人计时照抄 PvPoke 训练模式的代码（docs/mechanics.md 13.6）。
"""

from dataclasses import replace

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import PokemonBuild, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import ScriptedCharged, ScriptedPolicy, ScriptedReplacement
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.stats import IVs
from pogo_sim.team import Team
from pogo_sim.timeline import FaintEvent, MoveEvent, SwitchEvent, TurnSnapshot
from tests.pvpoke_reference import load_switch_reference

REFERENCE = load_switch_reference()
# 已知差异的场景（原因见各自的 note）不做逐回合比较，由下面单独的测试检查差异本身
SCENARIOS = [s for s in REFERENCE["scenarios"] if not s["known_difference"]]
KNOWN_DIFFERENCES = {s["id"]: s for s in REFERENCE["scenarios"] if s["known_difference"]}


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _make_teams(gm: GameMaster, scenario: dict) -> tuple[Team, Team]:
    teams = []
    for index, spec in enumerate(scenario["teams"]):
        members = []
        for member in spec["members"]:
            build = PokemonBuild(
                species_id=member["species"],
                level=member["level"],
                ivs=IVs(*member["ivs"]),
                fast_move_id=member["fast"],
                charged_move_ids=tuple(member["charged"]),
            )
            combatant = make_combatant(gm, build, index)
            # 先确认配置本身一致，否则后面的比较没有意义
            assert combatant.cp == member["cp"]
            assert combatant.stats.hp == member["hp"]
            combatant.hp = member["start_hp"]
            combatant.energy = member["start_energy"]
            members.append(combatant)
        teams.append(Team(tuple(members), shields=spec["shields"], switch_timer_ms=spec["switch_timer_ms"]))
    return teams[0], teams[1]


def _make_policies(scenario: dict) -> tuple[ScriptedPolicy, ScriptedPolicy]:
    """把剧本拆给双方：放大招、换人归自己；开不开盾归守方（按对手大招所在的回合）。"""
    script = scenario["script"]
    charged: list[dict[int, ScriptedCharged]] = [{}, {}]
    shields: list[dict[int, bool]] = [{}, {}]
    switches: list[dict[int, int]] = [{}, {}]
    replacements: list[dict[int, ScriptedReplacement]] = [{}, {}]
    for step in script["charged"]:
        actor, turn = step["actor"], step["turn"]
        charged[actor][turn] = ScriptedCharged(turn, step["move"], apply_effect=step["apply_effect"])
        shields[1 - actor][turn] = step["shielded"]
    for step in script["switches"]:
        switches[step["actor"]][step["turn"]] = step["to"]
    for step in script["replacements"]:
        replacements[step["actor"]][step["turn"]] = ScriptedReplacement(step["to"], step["wait_ms"])
    policies = [
        ScriptedPolicy(
            charged=charged[side], shields=shields[side], switches=switches[side], replacements=replacements[side]
        )
        for side in (0, 1)
    ]
    return policies[0], policies[1]


def _rules(scenario: dict) -> BattleRules:
    return replace(PVPOKE_COMPAT, switch_cooldown_ms=scenario["switch_cooldown_ms"])


def _snapshot_as_dict(snapshot: TurnSnapshot) -> dict:
    """转成和参考数据相同的格式，方便直接比较。"""
    return {
        "turn": snapshot.turn,
        "sides": [
            {
                "active": side.active,
                "hp": list(side.member_hp),
                "energy": list(side.member_energy),
                "cooldown": side.cooldown,
                "stages": [side.atk_stage, side.def_stage],
                "shields": side.shields,
                "switch_timer_ms": side.switch_timer_ms,
            }
            for side in snapshot.sides
        ],
    }


def _run(gm: GameMaster, scenario: dict) -> tuple[Battle, tuple[ScriptedPolicy, ScriptedPolicy]]:
    """打和 PvPoke 一样多的回合。"""
    policies = _make_policies(scenario)
    battle = Battle(_make_teams(gm, scenario), policies, _rules(scenario))
    for _ in scenario["snapshots"]:
        assert not battle.is_over(), f"我们的对战在第 {battle.turn} 回合前就结束了"
        battle.play_turn()
    return battle, policies


def test_reference_comes_from_snapshot_commit() -> None:
    assert REFERENCE["source"]["pvpoke_commit"] == "d02018eb6bfc4a041cca69d7bc9de0d5179a8365"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_turn_by_turn_matches_pvpoke(gm: GameMaster, scenario: dict) -> None:
    battle, _ = _run(gm, scenario)
    ours = [_snapshot_as_dict(s) for s in battle.snapshots]
    # 找出第一个不同的回合，报错时直接显示那一回合双方的状态
    for our_turn, expected_turn in zip(ours, scenario["snapshots"]):
        assert our_turn == expected_turn, f"第 {expected_turn['turn']} 回合起不一致"
    assert len(ours) == len(scenario["snapshots"])


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_events_and_result_match_pvpoke(gm: GameMaster, scenario: dict) -> None:
    battle, policies = _run(gm, scenario)
    expected = scenario["events"]

    moves = [
        {
            "turn": e.turn,
            "actor": e.actor,
            "actor_slot": e.actor_slot,
            "target_slot": e.target_slot,
            "move": e.move_id,
            "charged": e.is_charged,
            "damage": e.damage,
            "shielded": e.shielded,
        }
        for e in battle.events
        if isinstance(e, MoveEvent)
    ]
    assert moves == expected["moves"]

    switches = [
        {"turn": e.turn, "actor": e.actor, "from": e.from_slot, "to": e.to_slot, "switch_timer_ms": e.switch_timer_ms}
        for e in battle.events
        if isinstance(e, SwitchEvent)
    ]
    assert switches == expected["switches"]

    faints = [{"turn": e.turn, "actor": e.actor, "slot": e.slot} for e in battle.events if isinstance(e, FaintEvent)]
    assert faints == expected["faints"]

    # 剧本里的大招都要用到（排错回合会被悄悄忽略）
    assert policies[0].unused_charged() == [] and policies[1].unused_charged() == []
    # PvPoke 认为无效的换人（换人冷却没走完），我们的引擎根本不会问策略
    for rejected in expected["rejected"]:
        assert rejected["turn"] in policies[rejected["actor"]].unused_switches()

    result = battle.result()
    assert result.turns == scenario["result"]["turns"]
    assert list(result.remaining) == scenario["result"]["remaining"]
    assert result.elapsed_ms == scenario["result"]["elapsed_ms"]


def test_known_difference_survivor_switch_on_side_1(gm: GameMaster) -> None:
    """对手倒下、正在选人的回合，存活的第 1 方换人（Q21）：PvPoke 判无效，我们的引擎照换。

    PvPoke 同回合的两个换人按排队顺序结算（优先级相同，第 0 方在前）。第 0 方的倒下换人先结算，
    把对手在场那只的冷却设成 500 毫秒（Battle.js processAction），接着第 1 方的换人检查"冷却为 0"不通过。
    存活的是第 0 方时没有这个问题（见 replacement_wait_and_survivor_switch）。用户的规则（Q21）不分哪一方。
    """
    scenario = KNOWN_DIFFERENCES["survivor_switch_side_1"]
    # PvPoke：第 1 方第 3 回合的换人无效，只有第 0 方的倒下换人
    assert scenario["events"]["rejected"] == [{"turn": 3, "actor": 1, "to": 1}]
    assert [(e["turn"], e["actor"]) for e in scenario["events"]["switches"]] == [(3, 0)]

    battle, _ = _run(gm, scenario)
    # 前两回合（倒下之前和倒下的那一回合）完全相同
    ours = [_snapshot_as_dict(s) for s in battle.snapshots]
    assert ours[:2] == scenario["snapshots"][:2]
    # 第 3 回合：我们的引擎里双方都换了人
    assert [(e.turn, e.actor, e.kind) for e in battle.events if isinstance(e, SwitchEvent)] == [
        (3, 0, "replacement"),
        (3, 1, "zero_turn"),
    ]
