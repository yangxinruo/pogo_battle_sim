"""手动对战（第 4 步 4c，docs/mechanics.md 14.5）：玩家操作一队，和另一队的 3v3 策略（TeamPolicy）打。

做法——引擎不改结构，每次都从头重打：
- 玩家到现在做过的每个决定按顺序存成一个列表（ManualDecision）。
- 玩家这一方用 ManualPolicy：引擎每问一个决定，就按列表依次回答；问到列表之后的决定时抛出 DecisionNeeded，
  对战停在那里（play_manual 接住），返回当前局面和现在能选什么（ManualQuestion）。
- 对战是确定的，前面的决定照抄就能复现同样的局面。重打一场不到 0.05 秒，所以每做一个决定都从第 1 回合重打；
  不用记状态，撤销上一步就是去掉最后一个决定。

玩家要回答的四种问题（同 policy.Policy 的四个方法）：
- "action"：出招——快招、能量够的大招（威力 BattleRules.min_charge 到 100%）、换人（能换时）、什么都不做；
- "shield"：对方的大招打过来、队伍还有盾时，开不开盾；
- "zero_turn_switch"：不花回合的换人机会（大招后的空回合等），换不换、换谁；
- "replacement"：在场的倒下后换谁上（不等待）。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.gamemaster import Move
from pogo_sim.policy import (
    BattleView,
    ChargedAction,
    Decision,
    FastAction,
    Replacement,
    ShieldDecision,
    SwitchAction,
    SwitchDecision,
    WaitAction,
)
from pogo_sim.team_battle import (
    TeamBattle,
    format_battle_details,
    format_outcome,
    format_settings,
    format_teams,
    make_policies,
    make_teams,
)

QuestionKind = Literal["action", "shield", "zero_turn_switch", "replacement"]
QUESTION_NAMES: dict[str, str] = {
    "action": "出招",
    "shield": "开不开盾",
    "zero_turn_switch": "不花回合的换人",
    "replacement": "倒下后换谁",
}
ACTIONS = ("fast", "charged", "switch", "wait")
PLAYER = "player"  # 时间线里玩家的决定的原因


@dataclass(frozen=True)
class ManualDecision:
    """玩家的一个决定（也用来表示一个可选项）。

    - kind "action"：action 是 "fast" / "charged"（move_id、charge）/ "switch"（to）/ "wait"
    - kind "shield"：shield 是开不开
    - kind "zero_turn_switch"：to 是换上第几只，None 表示不换
    - kind "replacement"：to 是换上第几只
    作为可选项时，大招的 charge 是 1.0，表示威力可以在 min_charge 到 1 之间选。
    """

    kind: QuestionKind
    action: str = ""
    move_id: str = ""
    charge: float = 1.0
    to: int | None = None
    shield: bool = False

    def same_choice(self, other: "ManualDecision") -> bool:
        """是不是同一个选项（不看大招的威力）。"""
        return (self.kind, self.action, self.move_id, self.to, self.shield) == (
            other.kind, other.action, other.move_id, other.to, other.shield,
        )


@dataclass(frozen=True)
class ManualQuestion:
    """对战停下来问玩家的问题。"""

    index: int  # 这是玩家的第几个决定（从 0 数），回答就放在决定列表的这个位置
    turn: int
    kind: QuestionKind
    options: tuple[ManualDecision, ...]


class DecisionNeeded(Exception):
    """问到了玩家还没做的决定：对战停在这里。"""

    def __init__(self, question: ManualQuestion, view: BattleView) -> None:
        super().__init__(f"第 {question.turn} 回合要玩家决定：{QUESTION_NAMES[question.kind]}")
        self.question = question
        self.view = view


class ManualError(ValueError):
    """玩家的决定写错了，或者现在不能选。"""


def question_options(view: BattleView, kind: QuestionKind) -> tuple[ManualDecision, ...]:
    """现在能选什么。出招：快招、什么都不做、能量够的每个大招、能换人时换上每一只后备。"""
    bench = view.my_team.bench_slots()
    if kind == "action":
        options = [ManualDecision("action", "fast"), ManualDecision("action", "wait")]
        options += [
            ManualDecision("action", "charged", move.move_id)
            for move in view.me.charged_moves
            if view.me.energy >= move.energy_cost
        ]
        if view.can_switch:
            options += [ManualDecision("action", "switch", to=slot) for slot in bench]
        return tuple(options)
    if kind == "shield":
        return ManualDecision("shield", shield=True), ManualDecision("shield", shield=False)
    if kind == "zero_turn_switch":
        return (ManualDecision("zero_turn_switch"), *(ManualDecision("zero_turn_switch", to=slot) for slot in bench))
    return tuple(ManualDecision("replacement", to=slot) for slot in bench)


class ManualPolicy:
    """玩家这一方：按决定列表依次回答引擎的问题；列表用完了就抛出 DecisionNeeded。"""

    def __init__(self, decisions: Sequence[ManualDecision]) -> None:
        self.decisions = list(decisions)
        self.asked = 0  # 已经回答了几个

    def _answer(self, view: BattleView, kind: QuestionKind) -> ManualDecision:
        index = self.asked
        options = question_options(view, kind)
        if index >= len(self.decisions):
            raise DecisionNeeded(ManualQuestion(index, view.turn, kind, options), view)
        decision = self.decisions[index]
        where = f"第 {index + 1} 个决定（第 {view.turn} 回合，{QUESTION_NAMES[kind]}）"
        if decision.kind != kind:
            raise ManualError(f"{where}：这里要回答的是{QUESTION_NAMES[kind]}，得到的是{QUESTION_NAMES[decision.kind]}")
        if not any(decision.same_choice(option) for option in options):
            raise ManualError(f"{where}：现在不能选 {decision}")
        if decision.action == "charged" and not view.rules.min_charge <= decision.charge <= 1:
            raise ManualError(f"{where}：威力要在 {view.rules.min_charge:.0%} 到 100% 之间，得到 {decision.charge:.0%}")
        self.asked += 1
        return decision

    def decide_action(self, view: BattleView) -> Decision:
        decision = self._answer(view, "action")
        match decision.action:
            case "fast":
                return Decision(FastAction(), PLAYER)
            case "charged":
                reason = PLAYER if decision.charge == 1 else f"{PLAYER} ({decision.charge:.0%} charge)"
                return Decision(ChargedAction(decision.move_id, charge=decision.charge), reason)
            case "switch":
                assert decision.to is not None
                return Decision(SwitchAction(decision.to), PLAYER)
        return Decision(WaitAction(), PLAYER)

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        return ShieldDecision(self._answer(view, "shield").shield, PLAYER)

    def decide_zero_turn_switch(self, view: BattleView) -> SwitchDecision:
        return SwitchDecision(self._answer(view, "zero_turn_switch").to, PLAYER)

    def choose_replacement(self, view: BattleView) -> Replacement:
        to = self._answer(view, "replacement").to
        assert to is not None
        return Replacement(to, 0, PLAYER)


@dataclass
class ManualGame:
    """重打到下一个要玩家决定的地方（或者打完）。

    battle：引擎（停下来时，battle.teams 是当前的状态，battle.events、battle.snapshots 是到现在为止的记录）；
    question、view：停下来时问的问题和玩家这一方看到的局面；打完了时为 None，result 是结果。
    """

    battle: Battle
    question: ManualQuestion | None
    view: BattleView | None
    result: BattleResult | None


def play_manual(team_battle: TeamBattle, side: int, decisions: Sequence[ManualDecision]) -> ManualGame:
    """第 side 方由玩家操作（按 decisions），另一方用配置里的 TeamPolicy，从第 1 回合打到下一个要玩家决定的地方。"""
    if side not in (0, 1):
        raise ManualError(f"玩家操作的一方要是 0 或 1，得到 {side!r}")
    manual = ManualPolicy(decisions)
    policies = list(make_policies(team_battle))
    policies[side] = manual
    battle = Battle(make_teams(team_battle), (policies[0], policies[1]), team_battle.config.rules)
    try:
        result = battle.run()
    except DecisionNeeded as needed:
        return ManualGame(battle, needed.question, needed.view, None)
    except ValueError as e:  # 引擎检查出来的（ManualPolicy 已经检查过，一般不会到这里）
        raise ManualError(str(e)) from e
    if manual.asked < len(manual.decisions):
        raise ManualError(f"对战已经结束，后面还多了 {len(manual.decisions) - manual.asked} 个决定")
    return ManualGame(battle, None, None, result)


def parse_decisions(raw: Any) -> list[ManualDecision]:
    """网页发来的决定列表（每个是一个表，键同 ManualDecision 的字段）。写错时抛出 ManualError。"""
    if not isinstance(raw, list):
        raise ManualError(f"decisions 要写成列表，得到 {type(raw).__name__}")
    decisions = []
    for i, item in enumerate(raw):
        where = f"第 {i + 1} 个决定"
        if not isinstance(item, dict):
            raise ManualError(f"{where}要写成表，得到 {item!r}")
        unknown = set(item) - {"kind", "action", "move_id", "charge", "to", "shield"}
        if unknown:
            raise ManualError(f"{where}：不认识的字段 {', '.join(sorted(unknown))}")
        kind = item.get("kind")
        if kind not in QUESTION_NAMES:
            raise ManualError(f"{where}：kind 要是 {' / '.join(QUESTION_NAMES)}，得到 {kind!r}")
        action = item.get("action", "")
        if kind == "action" and action not in ACTIONS:
            raise ManualError(f"{where}：action 要是 {' / '.join(ACTIONS)}，得到 {action!r}")
        charge = item.get("charge", 1.0)
        to = item.get("to")
        checks = [
            (isinstance(item.get("move_id", ""), str), "move_id 要写字符串"),
            (isinstance(charge, (int, float)) and not isinstance(charge, bool), "charge 要写数字"),
            (to is None or (isinstance(to, int) and not isinstance(to, bool)), "to 要写整数或 null"),
            (isinstance(item.get("shield", False), bool), "shield 要写 true / false"),
        ]
        for ok, message in checks:
            if not ok:
                raise ManualError(f"{where}：{message}")
        decisions.append(ManualDecision(
            kind, action, item.get("move_id", ""), float(charge), to, item.get("shield", False),
        ))
    return decisions


def format_manual_report(battle: TeamBattle, result: BattleResult, side: int) -> str:
    """手动对战打完以后的报告（Markdown）：和 3v3 报告一样，只是写明哪一方是玩家操作的。"""
    player = battle.teams[side].setup.name
    opponent = battle.teams[1 - side].setup.name
    lines = format_settings(
        battle, "",
        f"{player} 由玩家手动操作（网页的手动对战，docs/mechanics.md 14.5）；{opponent} 是 3v3 策略 TeamPolicy",
    )
    lines += format_teams(battle, {side: "玩家手动操作；配置里的这一项没有用到："})
    lines += ["", "## 结果", "", format_outcome(battle, result), ""]
    lines += format_battle_details(battle, result, include_timeline=True)
    return "\n".join(lines).rstrip() + "\n"
