"""对固定对手策略的应对：逐步试探（pogo_sim/best_response.py，docs/mechanics.md 13.11）。"""

import re
from dataclasses import replace

import pytest

from pogo_sim.battle import BattleResult
from pogo_sim.best_response import (
    BestResponse,
    DecisionPoint,
    format_best_response_report,
    format_changes,
    format_score,
    format_tried,
    play,
    score,
    search_best_response,
)
from pogo_sim.config import REPO_ROOT
from pogo_sim.policy import ChargedAction, FastAction, SwitchAction
from pogo_sim.team_battle import TeamBattle, load_team_battle_config, prepare_team_battle, run_team_battle
from pogo_sim.timeline import DecisionEvent

EXAMPLE = REPO_ROOT / "experiments" / "gl_3v3_example.toml"


@pytest.fixture(scope="module")
def battle() -> TeamBattle:
    return prepare_team_battle(load_team_battle_config(EXAMPLE))


@pytest.fixture(scope="module")
def response(battle: TeamBattle) -> BestResponse:
    """Team A（第 0 方）对 Team B 的 TeamPolicy。"""
    return search_best_response(battle, 0)


def _summary(response: BestResponse) -> list[tuple[int, str, str, str]]:
    return [
        (c.point.turn, c.point.kind, c.point.label(c.point.policy_choice), c.point.label(c.chosen))
        for c in response.changes
    ]


# ---- 可操纵的策略 ----


def test_unsteered_play_equals_a_normal_battle(battle: TeamBattle) -> None:
    """什么都不指定时，和双方照 TeamPolicy 打一场完全相同（事件和原因都一样）。"""
    trial = play(battle, 0, {})
    normal = run_team_battle(battle)
    assert (trial.result.ratings, trial.result.turns, trial.result.events) == (
        normal.ratings, normal.turns, normal.events,
    )
    assert trial.score == (0, 221)
    assert all(p.chosen == p.policy_choice and p.policy_choice in p.options for p in trial.points)
    assert [p.index for p in trial.points] == list(range(len(trial.points)))
    assert {p.kind for p in trial.points} == {"action", "shield", "zero_turn", "replacement"}


def test_options(battle: TeamBattle) -> None:
    trial = play(battle, 0, {})
    first = trial.points[0]
    assert (first.turn, first.kind) == (1, "action")
    assert first.options == (FastAction(), SwitchAction(1), SwitchAction(2))  # 开局没有能量放大招
    assert first.labels == ("fast BUBBLE", "switch to Medicham", "switch to Registeel")
    charged = [p for p in trial.points if any(isinstance(o, ChargedAction) for o in p.options)]
    assert charged, "应该有能放大招的决定点"
    shields = [p for p in trial.points if p.kind == "shield"]
    assert all(p.options == (True, False) and p.labels == ("shield", "no shield") for p in shields)
    replacements = [p for p in trial.points if p.kind == "replacement"]
    assert [len(p.options) for p in replacements] == [2, 1]  # 第二次选人只剩一只


def test_active_member_at_each_decision(battle: TeamBattle) -> None:
    """决定点记下做决定时在场的是第几只：开局是首发，第 1 回合换上 Medicham 以后是第 1 只。"""
    trial = play(battle, 0, {0: SwitchAction(1)})
    assert trial.points[0].active == 0
    assert trial.points[1].active == 1
    replacement = next(p for p in trial.points if p.kind == "replacement")
    assert replacement.active not in replacement.options  # 倒下的那只不在选项里


def test_forced_decision_is_used_and_explained(battle: TeamBattle) -> None:
    trial = play(battle, 0, {0: SwitchAction(1)})
    first = trial.points[0]
    assert (first.policy_choice, first.chosen) == (FastAction(), SwitchAction(1))
    decision = next(e for e in trial.result.events if isinstance(e, DecisionEvent) and e.actor == 0)
    assert decision.action == "switch" and decision.switch_to == 1
    assert decision.reason.startswith("best response: switch to Medicham (policy would fast BUBBLE: ")


def test_forced_option_must_be_available(battle: TeamBattle) -> None:
    with pytest.raises(ValueError, match=re.escape("第 0 个决定指定的 ChargedAction(move_id='ICE_BEAM'")):
        play(battle, 0, {0: ChargedAction("ICE_BEAM")})  # 开局没有能量


# ---- 比较 ----


def _result(winner: int | None, ratings: tuple[int, int]) -> BattleResult:
    return BattleResult(winner, ratings, 10, 5000, winner is None, (1, 1), (0, 0), [], [])


def test_score() -> None:
    """先胜负再评分：赢 > 平 > 输，从指定的一方看。"""
    assert score(_result(0, (520, 479)), 0) == (2, 520)
    assert score(_result(0, (520, 479)), 1) == (0, 479)
    assert score(_result(None, (600, 399)), 0) == (1, 600)
    assert score(_result(0, (501, 498)), 0) > score(_result(None, (600, 399)), 0)  # 险胜好过评分高的平局
    assert format_score((0, 221)) == "输 221"


# ---- 搜索 ----


def test_example_search(response: BestResponse) -> None:
    """回归：示例里 Team A 对 Team B 的 TeamPolicy，从输 221 到赢 593（docs/experiments/gl_3v3_best_response.md）。"""
    assert response.baseline.score == (0, 221)
    assert response.best.score == (2, 593)
    assert _summary(response) == [
        (1, "action", "fast BUBBLE", "switch to Medicham"),
        (11, "shield", "shield", "no shield"),
        (21, "action", "fast COUNTER", "charged ICE_PUNCH"),
        (62, "zero_turn", "stay", "switch to Registeel"),
        (99, "zero_turn", "stay", "switch to Azumarill"),
    ]
    assert (response.examined, response.trials) == (32, 50)


def test_search_only_improves(response: BestResponse) -> None:
    """每次改动都严格更好，一环接一环：第一次从原策略开始，最后一次就是最终结果。"""
    changes = response.changes
    assert changes[0].before == response.baseline.score
    assert changes[-1].after == response.best.score
    for change, following in zip(changes, changes[1:]):
        assert change.after == following.before
    for change in changes:
        assert change.after > change.before
        values = dict(change.option_scores)
        assert values[change.point.policy_choice] == change.before
        assert values[change.chosen] == change.after == max(values.values())


def test_every_tried_point_is_recorded(response: BestResponse) -> None:
    """试过的决定点正好是搜索后那一场里有不止一个选项的决定点，按顺序；没改的没有更好的选项。"""
    best_points = [p for p in response.best.points if len(p.options) >= 2]
    assert [t.point.index for t in response.tried] == [p.index for p in best_points]
    for tried, final in zip(response.tried, best_points):
        assert (tried.point.turn, tried.point.kind, tried.point.options) == (final.turn, final.kind, final.options)
        assert tried.point.chosen == tried.point.policy_choice  # 试之前照原策略
        assert final.chosen == tried.chosen
        values = dict(tried.option_scores)
        assert set(values) == set(tried.point.options)
        assert values[tried.point.policy_choice] == tried.before
        if not tried.changed:
            assert tried.after == tried.before == max(values.values())
    assert (response.examined, len(response.changes)) == (32, 5)


def test_best_line_replays(battle: TeamBattle, response: BestResponse) -> None:
    """按搜索出来的指定重打一场，得到同样的结果；改过的决定点正好是指定的那些。"""
    best = response.best
    again = play(battle, 0, dict(best.forced))
    assert (again.score, again.result.events) == (best.score, best.result.events)
    changed = {p.index: p.chosen for p in best.points if p.chosen != p.policy_choice}
    assert changed == dict(best.forced)
    assert len(changed) == len(response.changes)


def test_search_the_other_side(battle: TeamBattle) -> None:
    """Team B 一方：本来就赢，搜索后评分更高。"""
    other = search_best_response(battle, 1)
    assert other.baseline.score == (2, 778)
    assert other.best.score == (2, 785)
    assert _summary(other) == [(23, "action", "fast MUD_SHOT", "charged HYDRO_CANNON")]


def test_bad_side(battle: TeamBattle) -> None:
    with pytest.raises(ValueError, match="side 要是 0 或 1"):
        search_best_response(battle, 2)


# ---- 报告 ----


def test_changes_table(response: BestResponse) -> None:
    lines = format_changes(response).splitlines()
    assert lines[0] == "| 回合 | 决定 | 原策略 | 改成 | 改之前 → 改之后 | 各选项打出来的结果 |"
    assert lines[2] == (
        "| 1 | 出招 | fast BUBBLE | switch to Medicham | 输 221 → 输 465 | "
        "fast BUBBLE: 输 221; switch to Medicham: 输 465; switch to Registeel: 输 237 |"
    )
    assert lines[3] == "| 11 | 开盾 | shield | no shield | 输 465 → 赢 521 | shield: 输 465; no shield: 赢 521 |"
    unchanged_only = replace(response, tried=tuple(t for t in response.tried if not t.changed))
    assert format_changes(unchanged_only).startswith("一个都没改")


def test_tried_table(response: BestResponse) -> None:
    lines = format_tried(response).splitlines()
    assert lines[0] == "| 回合 | 决定 | 原策略 | 搜索后 | 各选项打出来的结果 |"
    assert lines[2] == (
        "| 1 | 出招 | fast BUBBLE | **switch to Medicham** | "
        "fast BUBBLE: 输 221; switch to Medicham: 输 465; switch to Registeel: 输 237 |"
    )
    assert len(lines) == 2 + response.examined
    assert sum("**" in line for line in lines) == len(response.changes)
    assert any("| 同原策略 |" in line for line in lines)


def test_report(battle: TeamBattle, response: BestResponse) -> None:
    report = format_best_response_report(battle, response, source="x.toml")
    lines = report.splitlines()
    for heading in ("## 队伍", "## 搜索结果", "## 改了哪些决定", "## 试过的全部决定点", "## 搜索后的这一场", "## 每只的情况", "## 换人", "## 时间线"):
        assert heading in lines, heading
    assert (
        "- 策略：Team B（第 1 方）固定用 3v3 策略 TeamPolicy；"
        "Team A（第 0 方）的打法是对它逐步试探搜索出来的（docs/mechanics.md 13.11）"
    ) in lines
    assert "- 策略：逐步试探搜索出来的打法；原策略（起点）是 TeamPolicy，默认参数" in lines
    assert "- 原策略：Team B 赢。评分 221 对 778；剩余 0 只对 3 只；剩余盾 0 对 0；100 回合，对战时间 145 秒（大招每次按 10 秒算）。" in lines
    assert "- 搜索后：Team A 赢。评分 593 对 406；剩余 2 只对 0 只；剩余盾 0 对 0；116 回合，对战时间 192 秒（大招每次按 10 秒算）。" in lines
    assert re.search(r"^- Team A 一共做了 77 个决定，其中 32 个有不止一个选项、都试过；改了 5 个。一共打了 50 场，用时 [\d.]+ 秒。$", report, re.M)
    assert "decides switch -> Medicham  (best response: switch to Medicham (policy would fast BUBBLE: " in report
    assert "## 时间线" not in format_best_response_report(battle, response, include_timeline=False).splitlines()


def test_example_report_is_current() -> None:
    saved = (REPO_ROOT / "docs" / "experiments" / "gl_3v3_best_response.md").read_text(encoding="utf-8")
    assert "| 62 | 0 回合换人 | stay | switch to Registeel | 赢 577 → 赢 588 | stay: 赢 577; switch to Registeel: 赢 588 |" in saved
    assert "| 62 | 0 回合换人 | stay | **switch to Registeel** | stay: 赢 577; switch to Registeel: 赢 588 |" in saved


def test_decision_point_label() -> None:
    point = DecisionPoint(0, 1, "zero_turn", 0, (None, 2), ("stay", "switch to X"), None, 2)
    assert (point.label(None), point.label(2)) == ("stay", "switch to X")
