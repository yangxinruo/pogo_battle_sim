"""回合结算对照 PvPoke：用 PvPoke 同一场的剧本驱动我们的引擎，逐回合比较双方状态。

参考数据的来历见 tools/pvpoke_ref/export_battle_reference.js：PvPoke 的 AI 先模拟一场，
再转成剧本（哪一回合放哪个大招、开没开盾、概率效果有没有触发），按剧本重放时逐回合记录状态。
"""

import pytest

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.combatant import Combatant, PokemonBuild, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import ScriptedCharged, ScriptedPolicy
from pogo_sim.stats import IVs
from pogo_sim.timeline import MoveEvent, TurnSnapshot
from tests.pvpoke_reference import load_battle_reference

REFERENCE = load_battle_reference()
BATTLES = REFERENCE["battles"]


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _make_combatants(gm: GameMaster, battle: dict) -> tuple[Combatant, Combatant]:
    sides = []
    for index, spec in enumerate(battle["pokemon"]):
        build = PokemonBuild(
            species_id=spec["species"],
            level=spec["level"],
            ivs=IVs(*spec["ivs"]),
            fast_move_id=spec["fast"],
            charged_move_ids=tuple(spec["charged"]),
            mega_level=spec["mega_level"],
        )
        combatant = make_combatant(gm, build, index, spec["shields"])
        # 先确认配置本身一致，否则后面的比较没有意义
        assert combatant.cp == spec["cp"]
        assert combatant.stats.hp == spec["hp"]
        sides.append(combatant)
    return sides[0], sides[1]


def _make_policies(battle: dict) -> tuple[ScriptedPolicy, ScriptedPolicy]:
    """把 PvPoke 的剧本拆给双方：放大招归攻方，开不开盾归守方（按大招所在的回合）。"""
    charged: list[dict[int, ScriptedCharged]] = [{}, {}]
    shields: list[dict[int, bool]] = [{}, {}]
    for step in battle["script"]:
        actor = step["actor"]
        turn = step["turn"]
        charged[actor][turn] = ScriptedCharged(turn, step["move"], apply_effect=step["apply_effect"])
        shields[1 - actor][turn] = step["shielded"]
    return (
        ScriptedPolicy(charged=charged[0], shields=shields[0]),
        ScriptedPolicy(charged=charged[1], shields=shields[1]),
    )


def _snapshot_as_dict(snapshot: TurnSnapshot) -> dict:
    """转成和参考数据相同的格式，方便直接比较。"""
    a, b = snapshot.sides
    return {
        "turn": snapshot.turn,
        "hp": [a.hp, b.hp],
        "energy": [a.energy, b.energy],
        "cooldown": [a.cooldown, b.cooldown],
        "stages": [[a.atk_stage, a.def_stage], [b.atk_stage, b.def_stage]],
        "shields": [a.shields, b.shields],
    }


def _move_events(result: BattleResult) -> list[dict]:
    return [
        {
            "kind": "move",
            "turn": event.turn,
            "actor": event.actor,
            "move": event.move_id,
            "charged": event.is_charged,
            "damage": event.damage,
            "shielded": event.shielded,
        }
        for event in result.events
        if isinstance(event, MoveEvent)
    ]


def _run(gm: GameMaster, battle: dict) -> BattleResult:
    return Battle(_make_combatants(gm, battle), _make_policies(battle)).run()


def test_reference_comes_from_snapshot_commit() -> None:
    assert REFERENCE["source"]["pvpoke_commit"] == "d02018eb6bfc4a041cca69d7bc9de0d5179a8365"


@pytest.mark.parametrize("battle", BATTLES, ids=[b["id"] for b in BATTLES])
def test_turn_by_turn_matches_pvpoke(gm: GameMaster, battle: dict) -> None:
    result = _run(gm, battle)
    ours = [_snapshot_as_dict(s) for s in result.snapshots]
    expected = battle["snapshots"]

    # 找出第一个不同的回合，报错时直接显示那一回合双方的状态
    for our_turn, expected_turn in zip(ours, expected):
        assert our_turn == expected_turn, f"第 {expected_turn['turn']} 回合起不一致"
    assert len(ours) == len(expected)


@pytest.mark.parametrize("battle", BATTLES, ids=[b["id"] for b in BATTLES])
def test_moves_and_result_match_pvpoke(gm: GameMaster, battle: dict) -> None:
    policies = _make_policies(battle)
    result = Battle(_make_combatants(gm, battle), policies).run()
    # 剧本里的每个大招都应该在我们的引擎里被用到（排错回合会被悄悄忽略）
    assert policies[0].unused_charged() == [] and policies[1].unused_charged() == []
    expected_moves = [e for e in battle["events"] if e["kind"] == "move"]
    assert _move_events(result) == expected_moves
    assert list(result.ratings) == battle["result"]["ratings"]
    assert result.turns == battle["result"]["turns"]
    assert result.elapsed_ms == battle["result"]["duration_ms"]
