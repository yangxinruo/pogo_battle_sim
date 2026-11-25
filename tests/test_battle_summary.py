"""对位分段和招式带（pogo_sim/battle_summary.py，docs/mechanics.md 14.4）。

分段和招式带都是从事件里数出来的，所以主要核对：例子那一场的分段对得上过程；
几场不同的对战里，分段首尾相接、各段的计数加起来等于整场的计数；招式带和事件一一对应。
"""

import copy
from collections import Counter

import pytest

from pogo_sim import web_api
from pogo_sim.battle import Battle
from pogo_sim.battle_summary import battle_segments, lane_items
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.best_response import search_best_response
from pogo_sim.config import REPO_ROOT
from pogo_sim.team_battle import (
    format_team_battle_report,
    load_team_battle_config,
    max_hps,
    member_summaries,
    parse_team_battle_config,
    prepare_team_battle,
    run_team_battle,
    segment_end_text,
    segments,
    timeline_names,
)
from pogo_sim.timeline import DecisionEvent, FaintEvent, MoveEvent, SwitchEvent
from tests.test_switch_pvpoke import REFERENCE, _make_policies, _make_teams, _rules

EXAMPLE = REPO_ROOT / "experiments" / "gl_3v3_example.toml"


def _battle(raw: dict):
    battle = prepare_team_battle(parse_team_battle_config(raw, "测试"))
    return battle, run_team_battle(battle)


def _example_raw() -> dict:
    return copy.deepcopy(web_api.example_config())


@pytest.fixture(scope="module")
def example():
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    return battle, run_team_battle(battle)


def _variants() -> list[dict]:
    """几种不同的对战：例子、A 不主动换人、两队换首发、时间很短（时间到）、Mega 雪妖女（覆盖文件）。"""
    variants = [_example_raw()]

    raw = _example_raw()
    raw["team"][0]["policy"] = {"switching": "never"}
    variants.append(raw)

    raw = _example_raw()
    for team in raw["team"]:
        team["member"] = team["member"][1:] + team["member"][:1]
    variants.append(raw)

    raw = _example_raw()
    raw["rules"] = {"time_limit_ms": 30000}
    variants.append(raw)

    raw = _example_raw()
    raw["custom_files"] = ["data/custom/mega_froslass.toml"]
    raw["team"][0]["member"][2] = {
        "species": "froslass_mega", "fast": "POWDER_SNOW", "charged": ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"],
    }
    raw["team"][1]["shields"] = 1
    variants.append(raw)
    return variants


@pytest.fixture(scope="module")
def battles():
    return [_battle(raw) for raw in _variants()]


# ---- 例子那一场 ----


def test_example_segments(example):
    battle, result = example
    names = timeline_names(battle)
    found = [
        (s.start_turn, s.end_turn, names[0][s.sides[0].slot], names[1][s.sides[1].slot], s.fainted, s.switched)
        for s in segments(battle, result)
    ]
    # 第 30 回合 Swampert 放 Hydro Cannon（被挡下），第 31 回合（空回合）B 0 回合换上 Trevenant；
    # 之后 Trevenant 依次打倒 A 的三只，A 每次倒下后在下一回合换上下一只
    assert found == [
        (1, 30, "Azumarill", "Swampert", (), ((1, "zero_turn"),)),
        (31, 55, "Azumarill", "Trevenant", (0,), ()),
        (56, 86, "Registeel", "Trevenant", (0,), ()),
        (87, 100, "Medicham", "Trevenant", (0,), ()),
    ]
    first = segments(battle, result)[0]
    azumarill, swampert = first.sides
    assert (azumarill.hp_start, azumarill.hp_end, azumarill.energy_start, azumarill.energy_end) == (196, 155, 0, 44)
    assert (azumarill.fast_moves, azumarill.shields_used) == (9, 2)
    assert [(c.turn, c.move_id, c.damage, c.shielded) for c in azumarill.charged] == [(26, "ICE_BEAM", 1, True)]
    assert [(c.turn, c.move_id, c.shielded) for c in swampert.charged] == [
        (21, "HYDRO_CANNON", True), (30, "HYDRO_CANNON", True),
    ]
    assert swampert.shields_used == 1


def test_segment_end_text(example):
    battle, result = example
    all_segments = segments(battle, result)
    texts = [segment_end_text(battle, result, s, last=i == len(all_segments) - 1) for i, s in enumerate(all_segments)]
    assert texts == ["Team B 0 回合换人", "Azumarill 倒下", "Registeel 倒下", "Medicham 倒下"]


def test_timeout_segment_says_time_is_up():
    raw = _example_raw()
    raw["rules"] = {"time_limit_ms": 30000}
    battle, result = _battle(raw)
    assert result.timed_out
    all_segments = segments(battle, result)
    assert segment_end_text(battle, result, all_segments[-1], last=True) == "时间到"


def test_switch_on_the_first_turn_is_not_a_segment_of_its_own(example):
    """搜索后的打法第 1 回合就换上 Medicham：不单独算一段 0 回合长的 Azumarill 对 Swampert。"""
    battle, _ = example
    response = search_best_response(battle, 0)
    result = response.best.result
    first_switch = next(e for e in result.events if isinstance(e, SwitchEvent))
    assert (first_switch.turn, first_switch.to_slot) == (1, 1)
    first = segments(battle, result)[0]
    assert (first.start_turn, first.sides[0].slot, first.sides[1].slot) == (1, 1, 0)
    assert first.sides[0].hp_start == max_hps(battle)[0][1]


def test_segments_in_report(example):
    battle, result = example
    report = format_team_battle_report(battle, result)
    assert "## 对位分段" in report
    assert report.index("## 开局对位评分") < report.index("## 对位分段") < report.index("## 换人")
    assert (
        "| 1–30 | Azumarill：HP 196 → 155，能量 0 → 44；快招 9 次；大招 ICE_BEAM 挡下；开盾 2 次 | "
        "Swampert：HP 139 → 84，能量 0 → 37；快招 13 次；大招 HYDRO_CANNON 挡下、HYDRO_CANNON 挡下；开盾 1 次 | "
        "Team B 0 回合换人 |"
    ) in report


# ---- 几场不同的对战：分段首尾相接，计数对得上 ----


def test_segments_cover_the_battle(battles):
    for battle, result in battles:
        all_segments = segments(battle, result)
        assert all_segments[0].start_turn == 1
        assert all_segments[-1].end_turn == result.turns
        for before, after in zip(all_segments, all_segments[1:]):
            assert before.start_turn <= before.end_turn
            # 后一段从前一段结束的下一回合开始；漂浮快招时两段共用一个回合
            assert after.start_turn in (before.end_turn, before.end_turn + 1)
            assert before.sides[0].slot != after.sides[0].slot or before.sides[1].slot != after.sides[1].slot


def test_segment_counts_add_up(battles):
    for battle, result in battles:
        all_segments = segments(battle, result)
        summaries = {(s.side, s.slot): s for s in member_summaries(battle, result)}
        for side in (0, 1):
            fast = Counter()
            charged = Counter()
            dealt = Counter()
            for segment in all_segments:
                mine = segment.sides[side]
                fast[mine.slot] += mine.fast_moves
                charged[mine.slot] += len(mine.charged)
                dealt[mine.slot] += mine.damage_dealt
            for slot in range(len(battle.teams[side].members)):
                summary = summaries[(side, slot)]
                assert fast[slot] == summary.fast_moves
                assert charged[slot] == len(summary.charged_moves)
                assert dealt[slot] == summary.damage_dealt
            shields = sum(segment.sides[side].shields_used for segment in all_segments)
            assert shields == sum(summaries[(side, slot)].charged_shielded for slot in range(len(battle.teams[side].members)))


def test_segment_hp_follows_on(battles):
    """同一只连着在场的两段之间（不共用回合时），前一段结束的 HP 就是后一段开始的 HP。"""
    for battle, result in battles:
        all_segments = segments(battle, result)
        for before, after in zip(all_segments, all_segments[1:]):
            if after.start_turn != before.end_turn + 1:
                continue
            for side in (0, 1):
                if before.sides[side].slot == after.sides[side].slot:
                    assert before.sides[side].hp_end == after.sides[side].hp_start
                    assert before.sides[side].energy_end == after.sides[side].energy_start


def test_fainted_matches_faint_events(battles):
    for battle, result in battles:
        faints = [(e.actor, e.slot) for e in result.events if isinstance(e, FaintEvent)]
        listed = [(side, s.sides[side].slot) for s in segments(battle, result) for side in s.fainted]
        assert listed == faints
        for s in segments(battle, result):
            for side in s.fainted:
                assert s.sides[side].hp_end == 0


def test_single_pokemon_is_one_segment():
    """1v1（每队一只）就是一段。"""
    raw = _example_raw()
    for team in raw["team"]:
        team["member"] = team["member"][:1]
    raw["rules"] = {"max_team_size": 1}
    battle, result = _battle(raw)
    all_segments = segments(battle, result)
    assert len(all_segments) == 1
    assert (all_segments[0].start_turn, all_segments[0].end_turn) == (1, result.turns)


# ---- 招式带 ----


def test_lane_items_match_events(battles):
    for battle, result in battles:
        lanes = lane_items(result, battle.gm)
        for side in (0, 1):
            kinds = Counter(item.kind for item in lanes[side])
            moves = [e for e in result.events if isinstance(e, MoveEvent) and e.actor == side]
            assert kinds["fast"] == sum(1 for e in moves if not e.is_charged)
            assert kinds["charged"] == sum(1 for e in moves if e.is_charged)
            assert kinds["switch"] == sum(1 for e in result.events if isinstance(e, SwitchEvent) and e.actor == side)
            assert kinds["faint"] == sum(1 for e in result.events if isinstance(e, FaintEvent) and e.actor == side)
            for item in lanes[side]:
                assert 1 <= item.start_turn <= item.end_turn <= result.turns


def test_fast_blocks_start_when_decided(battles):
    """快招从决定的回合画到结算的回合；中间没有大招时，长度就是招式的回合数。"""
    for battle, result in battles:
        charged_turns = {e.turn for e in result.events if isinstance(e, MoveEvent) and e.is_charged}
        decided = {
            (e.actor, e.turn) for e in result.events if isinstance(e, DecisionEvent) and e.action == "fast"
        }
        for side, lane in enumerate(lane_items(result, battle.gm)):
            for item in lane:
                if item.kind != "fast":
                    continue
                assert (side, item.start_turn) in decided
                if not any(item.start_turn <= t <= item.end_turn for t in charged_turns):
                    assert item.end_turn - item.start_turn + 1 == battle.gm.get_move(item.move_id).turns


def test_example_lane(example):
    battle, result = example
    lanes = lane_items(result, battle.gm)
    first = lanes[0][0]
    assert (first.kind, first.start_turn, first.end_turn, first.move_id, first.damage) == ("fast", 1, 3, "BUBBLE", 6)
    switch = next(item for item in lanes[1] if item.kind == "switch")
    assert (switch.start_turn, switch.from_slot, switch.slot, switch.switch_kind) == (31, 0, 2, "zero_turn")


# ---- 快照里的对战时间 ----


def test_snapshot_elapsed_ms(battles):
    for _, result in battles:
        times = [s.elapsed_ms for s in result.snapshots]
        assert times == sorted(times)
        assert times[-1] == result.elapsed_ms
        assert times[0] == 500  # 第 1 回合没有大招：0.5 秒



# ---- 换人的边界情况：用和 PvPoke 对照过的换人场景（tests/test_switch_pvpoke.py） ----


@pytest.fixture(scope="module")
def scenarios():
    """每个场景：（场景 ID、结果、分段）。场景开局的 HP、能量不一定是满的。"""
    gm = load_gamemaster()
    found = {}
    for scenario in REFERENCE["scenarios"]:
        teams = _make_teams(gm, scenario)
        start_hp = [[m.hp for m in team.members] for team in teams]
        start_energy = [[m.energy for m in team.members] for team in teams]
        result = Battle(teams, _make_policies(scenario), _rules(scenario)).run()
        found[scenario["id"]] = (result, battle_segments(result, start_hp, start_energy))
    return found


def _brief(segments_):
    return [(s.start_turn, s.end_turn, tuple(side.slot for side in s.sides), s.fainted, s.switched) for s in segments_]


def test_scenario_segments_are_consistent(scenarios):
    for scenario_id, (result, all_segments) in scenarios.items():
        assert all_segments[0].start_turn == 1, scenario_id
        assert all_segments[-1].end_turn == result.turns, scenario_id
        for before, after in zip(all_segments, all_segments[1:]):
            assert after.start_turn in (before.end_turn, before.end_turn + 1), scenario_id
        moves = [e for e in result.events if isinstance(e, MoveEvent)]
        assert sum(side.fast_moves + len(side.charged) for s in all_segments for side in s.sides) == len(moves)
        faints = sorted((e.actor, e.slot) for e in result.events if isinstance(e, FaintEvent))
        listed = sorted((side, s.sides[side].slot) for s in all_segments for side in s.fainted)
        assert listed == faints, scenario_id


def test_zero_turn_switch_both_sides(scenarios):
    """大招后的空回合双方都 0 回合换人：漂浮快招先结算、打在换下去的那只身上，算前一段；两次换人只切一次。"""
    _, all_segments = scenarios["zero_turn_switch_both_sides"]
    assert _brief(all_segments)[:2] == [
        (1, 3, (0, 0), (), ((0, "zero_turn"), (1, "zero_turn"))),
        (3, 141, (1, 1), (1,), ()),
    ]
    assert all_segments[0].sides[0].hp_end == 60  # 第 3 回合被漂浮快招打到 60


def test_floating_fast_knocks_out_before_zero_turn_switch(scenarios):
    """换下去的那只先被漂浮快招打倒：倒下算前一段（虽然倒下的事件记在换人之后）。"""
    _, all_segments = scenarios["floating_fast_knocks_out_before_zero_turn_switch"]
    assert _brief(all_segments)[0] == (1, 3, (0, 0), (1,), ((1, "zero_turn"),))
    assert all_segments[0].sides[1].hp_end == 0


def test_double_knockout(scenarios):
    """双方同时倒下：这一段两方都倒下，下一回合双方同时换上，只切一次。"""
    _, all_segments = scenarios["double_knockout"]
    assert _brief(all_segments)[:2] == [(1, 1, (0, 0), (0, 1), ()), (2, 18, (1, 1), (0,), ())]


def test_survivor_switches_during_replacement(scenarios):
    """一方倒下，存活的一方在对手换人的回合同时 0 回合换人：一段同时写倒下和换人。"""
    _, all_segments = scenarios["replacement_wait_and_survivor_switch"]
    assert _brief(all_segments)[0] == (1, 2, (0, 0), (1,), ((0, "zero_turn"),))
    assert (all_segments[1].start_turn, all_segments[1].sides[0].slot, all_segments[1].sides[1].slot) == (3, 1, 2)


def test_starting_hp_and_energy_are_used(scenarios):
    """场景开局的 HP 不是满的：第一段开始时的 HP 用开局的值。"""
    _, all_segments = scenarios["double_knockout"]
    assert (all_segments[0].sides[0].hp_start, all_segments[0].sides[1].hp_start) == (1, 1)
