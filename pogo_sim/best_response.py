"""对固定对手策略的应对（3v3-g）：对手的策略不变，搜索我方一方更好的打法。

方法："逐步试探"（rollout），用户 2026-11-24 选定，见 docs/mechanics.md 13.11。
- 起点：双方都照各自的 TeamPolicy 打一场（"原策略"）。
- 沿着当前最好的那一场，按顺序看我方的每一个决定点。有不止一个选项时，把其余每个选项都试一遍：
  这个决定点之前的决定照当前最好的那一场，这一个换成这个选项，之后双方照各自的策略打完。
  打出来比当前最好的好（比较方法见下），就换成它；然后看下一个决定点，直到最后一个。
- 每一步都只在严格更好时才改，所以结果保证不比原策略差。但不保证全局最优：一次只改一个决定，
  而且试探时假定之后的决定照原策略。
- 对手的策略是确定的，搜索完全知道它会怎么应对（完全信息）。结果是"对这个对手策略"的应对，
  可能利用了它的规则里的弱点，不一定适用于真人对手。

我方可以改的决定（五种，用户选定）：
- 出招（action）：快招、能量够的每个大招（所以攒能量、骗盾的时机也在搜索范围里）、能换人时换上每一只后备；
- 开盾（shield）：开 / 不开；
- 不花回合的换人（zero_turn）：不换 / 换上每一只后备；
- 倒下后换谁上（replacement）：每一只后备。选人的等待不搜，照原策略（TeamPolicy 是 0）。

比较两场（用户选定）：先比胜负（从我方看，赢 > 平 > 输），再比我方的评分（D1）；一样时保留原来的选择，让改动尽量少。

实现：
- 每次试探都从第 1 回合重新打。对战是确定的，前面的决定照抄就能复现同样的局面
  （SteeredPolicy 每次都先问原策略，再按指定换掉，所以原策略内部的状态在每次重打时也一样）。
- 规则里有用随机数的开关时，每次试探用同一个种子（SEED）。
- 对位评估器在全部试探之间共用（缓存键不含是哪一场，结果不变，只是快）。
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.config import format_table
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import Move
from pogo_sim.policy import (
    BattleView,
    ChargedAction,
    Decision,
    FastAction,
    Policy,
    Replacement,
    ShieldDecision,
    SwitchAction,
    SwitchDecision,
)
from pogo_sim.simple_policy import SimplePolicyConfig
from pogo_sim.team import Team
from pogo_sim.team_battle import (
    TeamBattle,
    format_battle_details,
    format_outcome,
    format_settings,
    format_teams,
    make_policies,
    make_teams,
)

SEED = 0  # 规则里用随机数的开关时，每次试探都用这个种子

DECISION_KINDS: dict[str, str] = {
    "action": "出招",
    "shield": "开盾",
    "zero_turn": "0 回合换人",
    "replacement": "倒下后换人",
}
OUTCOME_NAMES = {2: "赢", 1: "平", 0: "输"}

Score = tuple[int, int]  # (胜负：赢 2 / 平 1 / 输 0，我方评分)


# ---- 决定点 ----


@dataclass(frozen=True)
class DecisionPoint:
    """我方的一个决定点（只有一个选项的也记）。"""

    index: int  # 我方第几个决定，从 0 数
    turn: int
    kind: str  # DECISION_KINDS 的键
    active: int  # 做决定时我方在场的是第几只（倒下后选人时是倒下的那只）
    options: tuple[Any, ...]  # 可以选的：action 是 FastAction / ChargedAction / SwitchAction；
    #                           shield 是 True / False；zero_turn 是 None（不换）或第几只；replacement 是第几只
    labels: tuple[str, ...]  # 每个选项的说明（英文，和时间线一致），例如 "switch to Medicham"
    policy_choice: Any  # 原策略在这里会选哪个
    chosen: Any  # 实际选的（没有指定时就是 policy_choice）

    def label(self, option: Any) -> str:
        return self.labels[self.options.index(option)]


def _name(team: Team, slot: int) -> str:
    return team.members[slot].name


def action_options(view: BattleView) -> tuple[tuple[Any, ...], tuple[str, ...]]:
    """出招的选项：快招、能量够的每个大招、能换人时换上每一只后备。"""
    me = view.me
    options: list[Any] = [FastAction()]
    labels = [f"fast {me.fast_move.move_id}"]
    for move in me.charged_moves:
        if me.energy >= move.energy_cost:
            options.append(ChargedAction(move.move_id))
            labels.append(f"charged {move.move_id}")
    if view.can_switch:
        for slot in view.my_team.bench_slots():
            options.append(SwitchAction(slot))
            labels.append(f"switch to {_name(view.my_team, slot)}")
    return tuple(options), tuple(labels)


class SteeredPolicy:
    """包着原策略：每个决定都先问原策略，再按 forced（第几个决定 → 选项）换掉。记下每一个决定点。"""

    def __init__(self, base: Policy, forced: Mapping[int, Any]) -> None:
        self.base = base
        self.forced = dict(forced)
        self.points: list[DecisionPoint] = []

    def _point(
        self, view: BattleView, kind: str, options: tuple[Any, ...], labels: tuple[str, ...], policy_choice: Any
    ) -> DecisionPoint:
        index = len(self.points)
        if policy_choice not in options:
            raise ValueError(f"第 {view.turn} 回合原策略的选择 {policy_choice!r} 不在选项里：{labels}")
        chosen = self.forced.get(index, policy_choice)
        if chosen not in options:
            raise ValueError(f"第 {index} 个决定指定的 {chosen!r} 现在不能选（可选：{', '.join(labels)}）")
        point = DecisionPoint(index, view.turn, kind, view.my_team.active, options, labels, policy_choice, chosen)
        self.points.append(point)
        return point

    @staticmethod
    def _reason(point: DecisionPoint, base_reason: str) -> str:
        """改过的决定，原因写明是搜索的结果，以及原策略本来会怎样。"""
        if point.chosen == point.policy_choice:
            return base_reason
        return (
            f"best response: {point.label(point.chosen)} "
            f"(policy would {point.label(point.policy_choice)}: {base_reason})"
        )

    def decide_action(self, view: BattleView) -> Decision:
        decision = self.base.decide_action(view)
        options, labels = action_options(view)
        point = self._point(view, "action", options, labels, _plain(decision.action))
        if point.chosen == point.policy_choice:
            return decision
        return Decision(point.chosen, self._reason(point, decision.reason))

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        decision = self.base.decide_shield(view, incoming, damage)
        point = self._point(view, "shield", (True, False), ("shield", "no shield"), decision.use_shield)
        return ShieldDecision(point.chosen, self._reason(point, decision.reason))

    def decide_zero_turn_switch(self, view: BattleView) -> SwitchDecision:
        decision = self.base.decide_zero_turn_switch(view)
        bench = view.my_team.bench_slots()
        options = (None, *bench)
        labels = ("stay", *(f"switch to {_name(view.my_team, slot)}" for slot in bench))
        point = self._point(view, "zero_turn", options, labels, decision.to)
        return SwitchDecision(point.chosen, self._reason(point, decision.reason))

    def choose_replacement(self, view: BattleView) -> Replacement:
        decision = self.base.choose_replacement(view)
        bench = view.my_team.bench_slots()
        labels = tuple(f"bring in {_name(view.my_team, slot)}" for slot in bench)
        point = self._point(view, "replacement", tuple(bench), labels, decision.to)
        return Replacement(point.chosen, decision.wait_ms, self._reason(point, decision.reason))


def _plain(action: Any) -> Any:
    """原策略的大招可能带 force_effect（只有剧本策略会指定）；比较选项时不看它。"""
    if isinstance(action, ChargedAction):
        return ChargedAction(action.move_id)
    return action


# ---- 打一场、比较 ----


@dataclass(frozen=True)
class Trial:
    """打一场：指定了哪些决定（其余照原策略），打出来的结果和我方的每个决定点。"""

    forced: tuple[tuple[int, Any], ...]  # (第几个决定, 选项)，按决定的顺序
    result: BattleResult
    points: tuple[DecisionPoint, ...]
    score: Score


def score(result: BattleResult, side: int) -> Score:
    """从第 side 方看：先胜负（赢 2、平 1、输 0），再评分。"""
    if result.winner is None:
        outcome = 1
    else:
        outcome = 2 if result.winner == side else 0
    return outcome, result.ratings[side]


def format_score(value: Score) -> str:
    """例如"输 221"。"""
    return f"{OUTCOME_NAMES[value[0]]} {value[1]}"


def play(
    battle: TeamBattle,
    side: int,
    forced: Mapping[int, Any],
    evaluators: dict[SimplePolicyConfig, MatchupEvaluator] | None = None,
) -> Trial:
    """第 side 方的决定按 forced 指定（其余照原策略），打一场。"""
    policies: list[Policy] = list(make_policies(battle, evaluators))
    steered = SteeredPolicy(policies[side], forced)
    policies[side] = steered
    result = Battle(make_teams(battle), (policies[0], policies[1]), battle.config.rules, seed=SEED).run()
    return Trial(tuple(sorted(forced.items())), result, tuple(steered.points), score(result, side))


# ---- 搜索 ----


@dataclass(frozen=True)
class Tried:
    """搜索时试过的一个决定点（有不止一个选项的），不论改没改。"""

    point: DecisionPoint  # 试的时候当前最好的那一场里的这个决定点（chosen 就是原策略的选择）
    option_scores: tuple[tuple[Any, Score], ...]  # 这个决定点每个选项打出来的结果
    chosen: Any  # 试完以后选的：改了就是更好的那个选项，没改就是原策略的选择
    before: Score  # 试之前（当时最好的那一场）
    after: Score  # 试之后；没改时等于 before

    @property
    def changed(self) -> bool:
        return self.chosen != self.point.policy_choice


@dataclass(frozen=True)
class BestResponse:
    side: int  # 搜索的是哪一方
    baseline: Trial  # 双方都照原策略
    best: Trial  # 搜索后
    tried: tuple[Tried, ...]  # 试过的每个决定点（有不止一个选项的），按搜索的顺序
    trials: int  # 一共打了几场（含起点）
    seconds: float

    @property
    def changes(self) -> tuple[Tried, ...]:
        """改了的决定点。"""
        return tuple(t for t in self.tried if t.changed)

    @property
    def examined(self) -> int:
        """试过几个决定点。"""
        return len(self.tried)


def search_best_response(battle: TeamBattle, side: int) -> BestResponse:
    """对另一方的固定策略，逐步试探第 side 方的打法（方法见模块说明）。"""
    if side not in (0, 1):
        raise ValueError(f"side 要是 0 或 1，得到 {side!r}")
    started = time.perf_counter()
    evaluators: dict[SimplePolicyConfig, MatchupEvaluator] = {}
    baseline = play(battle, side, {}, evaluators)
    best = baseline
    forced: dict[int, Any] = {}  # 只记改过的；没记的照原策略，重打时会做出同样的选择
    tried: list[Tried] = []
    trials = 1

    index = 0
    while index < len(best.points):  # 改了以后，后面的决定点会变，所以每次都看当前最好的那一场
        point = best.points[index]
        index += 1
        if len(point.options) < 2:
            continue
        option_scores = []
        candidate = best
        for option in point.options:
            if option == point.chosen:
                option_scores.append((option, best.score))
                continue
            trial = play(battle, side, {**forced, point.index: option}, evaluators)
            trials += 1
            option_scores.append((option, trial.score))
            if trial.score > candidate.score:
                candidate = trial
        chosen = candidate.points[point.index].chosen
        tried.append(Tried(point, tuple(option_scores), chosen, best.score, candidate.score))
        if candidate is not best:
            forced[point.index] = chosen
            best = candidate

    return BestResponse(
        side=side,
        baseline=baseline,
        best=best,
        tried=tuple(tried),
        trials=trials,
        seconds=time.perf_counter() - started,
    )


# ---- 报告（Markdown） ----


def option_results(tried: Tried) -> str:
    """一个决定点每个选项打出来的结果，例如 "shield: 输 465; no shield: 赢 521"。"""
    point = tried.point
    return "; ".join(f"{point.label(option)}: {format_score(value)}" for option, value in tried.option_scores)


def format_changes(response: BestResponse) -> str:
    """改了哪些决定：一行一个，按搜索的顺序。"""
    if not response.changes:
        return "一个都没改：每个决定点上，原策略的选择已经是试过的选项里最好的。"
    header = ["回合", "决定", "原策略", "改成", "改之前 → 改之后", "各选项打出来的结果"]
    rows = []
    for change in response.changes:
        point = change.point
        options = option_results(change)
        rows.append([
            str(point.turn),
            DECISION_KINDS[point.kind],
            point.label(point.policy_choice),
            point.label(change.chosen),
            f"{format_score(change.before)} → {format_score(change.after)}",
            options,
        ])
    return format_table(header, rows)


def format_tried(response: BestResponse) -> str:
    """试过的全部决定点：一行一个，按搜索的顺序；改了的加粗。"""
    header = ["回合", "决定", "原策略", "搜索后", "各选项打出来的结果"]
    rows = []
    for tried in response.tried:
        point = tried.point
        after = f"**{point.label(tried.chosen)}**" if tried.changed else "同原策略"
        rows.append([str(point.turn), DECISION_KINDS[point.kind], point.label(point.policy_choice), after, option_results(tried)])
    return format_table(header, rows)


def format_best_response_report(
    battle: TeamBattle, response: BestResponse, source: str = "", include_timeline: bool = True
) -> str:
    """完整报告：设置、两队、搜索结果、改了哪些决定、试过的全部决定点、搜索后的这一场。"""
    side = response.side
    me = battle.teams[side].setup.name
    opponent = battle.teams[1 - side].setup.name
    lines = format_settings(
        battle,
        source,
        f"{opponent}（第 {1 - side} 方）固定用 3v3 策略 TeamPolicy；"
        f"{me}（第 {side} 方）的打法是对它逐步试探搜索出来的（docs/mechanics.md 13.11）",
    )
    lines += format_teams(battle, {side: "逐步试探搜索出来的打法；原策略（起点）是 "})

    baseline, best = response.baseline, response.best
    lines += ["", "## 搜索结果", ""]
    lines.append(
        f"方法：先让双方都照原策略打一场；然后沿着当前最好的一场，按顺序把 {me} 每个决定点的其余选项都试一遍"
        "（之前的决定照当前最好的一场，之后双方照各自的策略打完），严格更好就改。"
        "比较时先看胜负，再看评分。结果不比原策略差，但不保证全局最优；"
        f"搜索完全知道 {opponent} 的策略会怎么应对，所以是针对这个策略的打法。"
    )
    lines += [
        "",
        f"- 原策略：{format_outcome(battle, baseline.result)}",
        f"- 搜索后：{format_outcome(battle, best.result)}",
        f"- {me} 一共做了 {len(best.points)} 个决定，其中 {response.examined} 个有不止一个选项、都试过；"
        f"改了 {len(response.changes)} 个。一共打了 {response.trials} 场，用时 {response.seconds:.1f} 秒。",
    ]

    lines += ["", "## 改了哪些决定", ""]
    lines.append(
        "按搜索的顺序。\"改之前 → 改之后\"是当时最好的一场和改了以后的结果（从 "
        f"{me} 看：胜负和评分）；\"各选项\"是这个决定点每个选项打出来的结果"
        "（之前的决定照当时最好的一场，之后照各自的策略）。后面的改动是在前面改过的基础上试的。"
    )
    lines += ["", format_changes(response), ""]

    lines += ["## 试过的全部决定点", ""]
    lines.append(
        f"{me} 每个有不止一个选项的决定点一行，按搜索的顺序；改了的加粗。"
        "\"各选项\"的意思同上：之前的决定照当时最好的一场，之后照各自的策略。"
    )
    lines += ["", format_tried(response), ""]

    lines += ["## 搜索后的这一场", ""]
    lines.append("以下各节都是搜索后的这一场。时间线里，改过的决定的原因写成 best response: …（policy would …）。")
    lines.append("")
    lines += format_battle_details(battle, best.result, include_timeline)
    return "\n".join(lines).rstrip() + "\n"
