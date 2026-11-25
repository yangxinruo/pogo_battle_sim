"""对战引擎：按回合结算（docs/mechanics.md 第 5 节；换人见第 13 节）。

双方各是一支队伍（team.Team），每回合由双方在场的那只交手；盾和换人冷却是全队共用的。
1v1 就是每队一只。

每回合的步骤与 PvPoke battle/Battle.js 的 step() 一致：
0. 换人冷却减少：扣掉上一回合花的对战时间（含大招）。换人回合先让倒下的一方选人，
   再扣掉选人的等待（等待发生在换人回合之前）。
1. 冷却减少：双方冷却各减 1 回合。
2. 决定行动：冷却为 0 的一方问自己的策略（快招、大招、主动换人，或者等待——这一回合什么都不做）。
   - 上一回合有大招结算时，本回合只能换人，而且不花回合（"大招后的空回合"，0 回合换人）。
   - 上一回合有在场的倒下时，本回合是"换人回合"：倒下的一方选人上场，存活的一方不出招
     （可以 0 回合换人，见 BattleRules.switch_during_opponent_replacement）。
3. 取出本回合要结算的行动：换人和大招在决定的当回合结算；快招在它的最后一个回合结算；
   上一回合有大招时，更早开始、还没结算的快招都在本回合结算（"漂浮"的快招）。
4. 按优先级排序：换人 20（大招后的空回合 −40，见 BattleRules.zero_turn_switch_floating_fast_hits），
   大招 10（CMP 攻击高的一方再 +1），快招 0；同优先级保持排队顺序。
5. 逐个检查是否仍然有效，然后结算（换人、伤害、能量、盾、能力变化）。
   招式打的是结算时对方在场的那只：对方这一回合先换了人，就由换上来的承受。
6. 回合结束：本回合用过大招则双方冷却都设为 1；记录快照；检查倒下和时限。
   在场的倒下、队伍还有后备时：清空双方排队中的行动，冷却归零，下一回合是换人回合。

引擎从不自己做决定：出招、开盾、换人都问策略（policy.py），原因写进时间线。
状态：参考 PvPoke。1v1 部分已用 PvPoke 源码的对战记录逐回合核对（tests/test_battle_pvpoke.py）；
换人部分照 PvPoke 训练模式的代码写（docs/mechanics.md 13.1），也已逐回合核对（tests/test_switch_pvpoke.py，13.6）。

暂不支持：形态变化、Gulp Missile 之类的特殊招式。
"""

import random
from dataclasses import dataclass, field
from math import floor
from typing import Literal

from pogo_sim.combatant import Combatant
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import Move
from pogo_sim.policy import BattleView, ChargedAction, FastAction, Policy, Replacement, SwitchAction, WaitAction
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.team import Team
from pogo_sim.timeline import (
    CancelledEvent,
    DecisionEvent,
    EffectApplied,
    Event,
    FaintEvent,
    MoveEvent,
    SideSnapshot,
    SwitchEvent,
    SwitchKind,
    TurnSnapshot,
)

# 行动优先级。来源：Battle.js getTurnAction、step()。状态：参考 PvPoke。
FAST_PRIORITY = 0
CHARGED_PRIORITY = 10
CMP_WINNER_BONUS = 1
SWITCH_PRIORITY = 20
# 大招后的空回合，换人排到漂浮快招之后（PvPoke："Resolve floating Fast Attacks before 0 turn swaps"）
AFTER_CHARGED_SWITCH_ADJUST = -40


@dataclass
class _QueuedAction:
    """已经决定、等待结算的行动。"""

    kind: Literal["fast", "charged", "switch"]
    actor: int  # 哪一方
    turn: int  # 决定的回合
    user: Combatant  # 做决定的那只（换人时是换下去的那只）
    user_slot: int  # user 在队伍里是第几只
    priority: int
    move: Move | None = None  # 快招、大招
    force_effect: bool | None = None  # 大招
    charge: float = 1.0  # 大招的威力（蓄力比例）
    switch_to: int | None = None  # 换人：换上第几只
    switch_kind: SwitchKind | None = None
    wait_ms: int = 0  # 倒下后换人：选人等了多久

    @property
    def label(self) -> str:
        """时间线里的名字：招式 ID，换人时是 "switch"。"""
        return self.move.move_id if self.move is not None else "switch"


@dataclass
class _TurnClock:
    """本回合对"对战时间"的影响（用于 240 秒时限和换人冷却，见 BattleRules.charged_move_ms）。"""

    extra_ms: int = 0
    charged_used: int = 0
    shield_used: bool = False
    wait_ms: int = 0  # 倒下后选人的等待（双方同时选人时取较长的），发生在换人回合开始之前


@dataclass(frozen=True)
class BattleResult:
    winner: int | None  # 赢的一方；平局为 None（判定见 Battle.result）
    ratings: tuple[int, int]  # 对战评分（0–1000），见 team_rating()
    turns: int  # 一共进行了几个回合
    elapsed_ms: int  # 对战时间（PvPoke 口径，含倒下后选人的等待）
    timed_out: bool  # 时间到结束（双方都还有宝可梦）
    remaining: tuple[int, int]  # 双方还剩几只
    shields_left: tuple[int, int]  # 双方还剩几个盾
    events: list[Event] = field(repr=False)
    snapshots: list[TurnSnapshot] = field(repr=False)


def battle_rating(me: Combatant, opponent: Combatant) -> int:
    """PvPoke 的 1v1 对战评分：对手损失的 HP 比例 × 500 + 自己剩余的 HP 比例 × 500，向下取整。

    这是 PvPoke 的评分方式，不是游戏规则。来源：Pokemon.js getBattleRating。
    """
    lost = (opponent.stats.hp - opponent.hp) / opponent.stats.hp
    remaining = me.hp / me.stats.hp
    return floor((500 * lost) + (500 * remaining))


def team_rating(me: Team, opponent: Team) -> int:
    """队伍的对战评分（docs/mechanics.md 13.2 D1）：把 PvPoke 的 1v1 评分推广到队伍。

    评分 = 对手全队损失的 HP 比例的平均 × 500 + 自己全队剩余的 HP 比例的平均 × 500，向下取整。
    也就是 500 + 500 ×（己方剩余 HP 比例之和 − 对方剩余 HP 比例之和）÷ 每队只数。
    每队一只时与 battle_rating 逐位相同。这是本项目的口径，不是游戏规则。
    """
    lost = sum((m.stats.hp - m.hp) / m.stats.hp for m in opponent.members) / len(opponent.members)
    remaining = sum(m.hp / m.stats.hp for m in me.members) / len(me.members)
    return floor((500 * lost) + (500 * remaining))


def _snapshot(team: Team) -> SideSnapshot:
    active = team.active_member
    return SideSnapshot(
        hp=active.hp,
        energy=active.energy,
        cooldown=active.cooldown,
        atk_stage=active.atk_stage,
        def_stage=active.def_stage,
        shields=team.shields,
        active=team.active,
        switch_timer_ms=team.switch_timer_ms,
        member_hp=tuple(member.hp for member in team.members),
        member_energy=tuple(member.energy for member in team.members),
    )


class Battle:
    """一场对战。用 run() 一次跑完，或者反复调用 play_turn() 逐回合推进。

    teams 依次是第 0 方和第 1 方的队伍；policies 是双方的策略，顺序相同。
    """

    def __init__(
        self,
        teams: tuple[Team, Team],
        policies: tuple[Policy, Policy],
        rules: BattleRules = PVPOKE_COMPAT,
        seed: int | None = None,
    ) -> None:
        if teams[0].index != 0 or teams[1].index != 1:
            raise ValueError("teams 的成员必须依次属于第 0 方和第 1 方（Combatant.index）")
        for team in teams:
            if not 0 <= team.shields <= rules.max_shields:
                raise ValueError(f"盾数必须是 0 到 {rules.max_shields}，得到 {team.shields}")
            if len(team.members) > rules.max_team_size:
                raise ValueError(f"每队最多 {rules.max_team_size} 只，得到 {len(team.members)} 只")
        self.teams = teams
        self.policies = policies
        self.rules = rules
        self.rng = random.Random(seed)  # 只有开关设成 "random" 时才会用到

        self.turn = 1  # 下一个要结算的回合（PvPoke 也从 1 开始数）
        self.elapsed_ms = 0
        self.charged_last_turn = False
        self.replacement_turn = False  # 本回合是不是倒下后的换人回合
        self.queue: list[_QueuedAction] = []
        self.events: list[Event] = []
        self.snapshots: list[TurnSnapshot] = []
        self._last_turn_ms = 0  # 上一回合花的对战时间（下一回合开头从换人冷却里扣）
        self._fainted_reported: set[tuple[int, int]] = set()  # 已经记过 FaintEvent 的（方, 第几只）

    # ---- 对外接口 ----

    def run(self) -> BattleResult:
        while not self.is_over():
            self.play_turn()
        return self.result()

    def active(self, index: int) -> Combatant:
        """第 index 方在场的那只。"""
        return self.teams[index].active_member

    def is_over(self) -> bool:
        if any(team.is_defeated for team in self.teams):
            return True
        return self.elapsed_ms > self.rules.time_limit_ms

    def result(self) -> BattleResult:
        """对战结束后的结果。谁赢：

        - 一方全队倒下：另一方赢；双方在同一回合全队倒下：平局（Q18）。
        - 时间到、双方都还有宝可梦：按 BattleRules.timeout_result（默认平局，Q19）。
        """
        team_a, team_b = self.teams
        ratings = (team_rating(team_a, team_b), team_rating(team_b, team_a))
        remaining = (team_a.remaining, team_b.remaining)
        timed_out = not any(team.is_defeated for team in self.teams)

        if not timed_out:
            winner = None if all(team.is_defeated for team in self.teams) else (0 if remaining[0] else 1)
        elif self.rules.timeout_result == "more_remaining":
            winner = _higher(remaining)
        elif self.rules.timeout_result == "rating":
            winner = _higher(ratings)
        else:
            winner = None

        return BattleResult(
            winner=winner,
            ratings=ratings,
            turns=self.turn - 1,
            elapsed_ms=self.elapsed_ms,
            timed_out=timed_out,
            remaining=remaining,
            shields_left=(team_a.shields, team_b.shields),
            events=self.events,
            snapshots=self.snapshots,
        )

    def play_turn(self) -> None:
        """结算一个回合（步骤见模块说明）。"""
        turn = self.turn
        clock = _TurnClock()

        # 0. 换人冷却减少：扣掉上一回合花的对战时间。PvPoke 在 step() 开头扣，大招的暂停期间也照扣（Q13、Q14）。
        self._tick_switch_timers(self._last_turn_ms)

        # 倒下后的换人回合：倒下的一方先选人（换谁、等多久）。选人的等待发生在换人回合之前，
        # 等待期间双方的换人冷却照走——存活的一方这一回合能不能换，看的是等完之后的冷却
        # （PvPoke 训练模式相同：选人期间 step() 照常每 500 毫秒扣一次换人计时）。
        replacements: dict[int, Replacement] = {}
        if self.replacement_turn:
            replacements = self._choose_replacements(turn)
            clock.wait_ms = max(choice.wait_ms for choice in replacements.values())
            self._tick_switch_timers(clock.wait_ms)

        # 1. 冷却减少
        for team in self.teams:
            team.active_member.cooldown = max(0, team.active_member.cooldown - 1)

        # 2. 决定行动
        self._decide_actions(turn, replacements)

        # 3. 取出本回合要结算的行动；4. 排序
        due = self._take_due_actions(turn)
        self._sort_by_priority(due)

        # 5. 逐个结算
        for action in due:
            self._resolve(action, turn, clock)

        # 6. 回合结束
        self.charged_last_turn = any(action.kind == "charged" for action in due)
        turn_ms = clock.extra_ms + self._end_of_turn_ms(clock)
        self.elapsed_ms += clock.wait_ms + turn_ms
        self._last_turn_ms = turn_ms  # 选人的等待已经在本回合开头扣过了
        if clock.charged_used > 0:
            # 大招之后双方冷却都设为 1：下一回合是空回合，再下一回合双方同时恢复行动。
            # 来源：Battle.js step() 末尾 poke.cooldown = 500。
            for team in self.teams:
                team.active_member.cooldown = 1
        self._record_faints(turn)
        self._prepare_replacement(turn)
        self.snapshots.append(
            TurnSnapshot(turn, (_snapshot(self.teams[0]), _snapshot(self.teams[1])), self.elapsed_ms)
        )
        self.turn += 1

    # ---- 第 2 步：决定行动 ----

    def _tick_switch_timers(self, elapsed_ms: int) -> None:
        for team in self.teams:
            team.switch_timer_ms = max(0, team.switch_timer_ms - elapsed_ms)

    def _decide_actions(self, turn: int, replacements: dict[int, Replacement]) -> None:
        """replacements：换人回合里倒下的一方已经选好的人（见 _choose_replacements），按方排队。"""
        # 先记下新的冷却，等双方都决定完再一起设置：后决定的一方看到的仍是回合开始时的状态。
        sides = (self.active(0), self.active(1))
        new_cooldowns = [side.cooldown for side in sides]

        for side in sides:
            team = self.teams[side.index]
            view = BattleView(turn, team, self.teams[1 - side.index], self.rules)

            if self.replacement_turn:
                # 倒下后的换人回合：倒下的一方换上选好的那只；存活的一方不出招，只可能 0 回合换人。
                # 两边的换人按方的顺序排队（同优先级先结算第 0 方，与 PvPoke 相同）。
                if side.is_fainted:
                    choice = replacements[side.index]
                    self._queue_switch(view, choice.to, "replacement", choice.reason, choice.wait_ms)
                elif self.charged_last_turn or self.rules.switch_during_opponent_replacement:
                    self._decide_zero_turn_switch(view)
                continue
            if side.cooldown != 0:
                continue
            if self.charged_last_turn:
                # 大招后的空回合：只能换人，而且不花回合（Q15：双方都可以）。
                self._decide_zero_turn_switch(view)
                continue

            decision = self.policies[side.index].decide_action(view)
            action = decision.action
            if isinstance(action, FastAction):
                move = side.fast_move
                new_cooldowns[side.index] += move.turns
                self.queue.append(
                    _QueuedAction("fast", side.index, turn, side, team.active, FAST_PRIORITY, move=move)
                )
                self.events.append(
                    DecisionEvent(turn, side.index, "fast", move.move_id, decision.reason, team.active)
                )
            elif isinstance(action, ChargedAction):
                move = self._find_charged_move(side, action.move_id)
                if side.energy < move.energy_cost:
                    raise ValueError(
                        f"第 {turn} 回合 {side.name} 的策略要放 {move.move_id}，但能量只有 {side.energy}"
                    )
                if not self.rules.min_charge <= action.charge <= 1:
                    raise ValueError(
                        f"第 {turn} 回合 {side.name} 的 {move.move_id} 威力要在 "
                        f"{self.rules.min_charge:.0%} 到 100% 之间，得到 {action.charge:.0%}"
                    )
                new_cooldowns[side.index] += 1
                priority = CHARGED_PRIORITY
                if side.cmp_attack(self.rules) > view.opponent.cmp_attack(self.rules):
                    priority += CMP_WINNER_BONUS
                self.queue.append(
                    _QueuedAction(
                        "charged", side.index, turn, side, team.active, priority,
                        move=move, force_effect=action.force_effect, charge=action.charge,
                    )
                )
                self.events.append(
                    DecisionEvent(turn, side.index, "charged", move.move_id, decision.reason, team.active)
                )
            elif isinstance(action, SwitchAction):
                # 主动换人：占用这一回合的行动，但不加冷却——换上来的下一回合就能行动（PvPoke）。
                if not view.can_switch:
                    raise ValueError(
                        f"第 {turn} 回合 {side.name} 的策略要换人，但现在不能换"
                        f"（换人冷却还剩 {team.switch_timer_ms} 毫秒，或后备都倒下了）"
                    )
                self._queue_switch(view, action.to, "switch", decision.reason)
            elif isinstance(action, WaitAction):
                # 什么都不做：不排行动，冷却保持 0，下一回合再问。
                self.events.append(DecisionEvent(turn, side.index, "wait", "", decision.reason, team.active))
            else:
                raise TypeError(f"不认识的行动：{action!r}")

        for side, cooldown in zip(sides, new_cooldowns):
            side.cooldown = cooldown

    def _decide_zero_turn_switch(self, view: BattleView) -> None:
        """不花回合的换人机会：能换（冷却为 0、有后备）才问策略。"""
        if not view.can_switch:
            return
        team = view.my_team
        decision = self.policies[team.index].decide_zero_turn_switch(view)
        if decision.to is None:
            self.events.append(DecisionEvent(view.turn, team.index, "stay", "", decision.reason, team.active))
            return
        self._queue_switch(view, decision.to, "zero_turn", decision.reason)

    def _choose_replacements(self, turn: int) -> dict[int, Replacement]:
        """在场的倒下了：问倒下的一方（双方同时倒下就是双方）换谁上、选人时等多久。"""
        choices = {}
        for team in self.teams:
            if not team.active_member.is_fainted:
                continue
            view = BattleView(turn, team, self.teams[1 - team.index], self.rules)
            choice = self.policies[team.index].choose_replacement(view)
            if not 0 <= choice.wait_ms <= self.rules.max_replacement_wait_ms:
                raise ValueError(
                    f"选人等待必须是 0 到 {self.rules.max_replacement_wait_ms} 毫秒，得到 {choice.wait_ms}"
                )
            choices[team.index] = choice
        return choices

    def _queue_switch(
        self, view: BattleView, to: int, kind: SwitchKind, reason: str, wait_ms: int = 0
    ) -> None:
        team = view.my_team
        if to not in team.bench_slots():
            raise ValueError(
                f"第 {view.turn} 回合第 {team.index} 方要换上第 {to} 只，"
                f"但它不在后备里或已经倒下（可以换的：{list(team.bench_slots())}）"
            )
        priority = SWITCH_PRIORITY
        if self.charged_last_turn and self.rules.zero_turn_switch_floating_fast_hits == "outgoing":
            priority += AFTER_CHARGED_SWITCH_ADJUST
        self.queue.append(
            _QueuedAction(
                "switch", team.index, view.turn, view.me, team.active, priority,
                switch_to=to, switch_kind=kind, wait_ms=wait_ms,
            )
        )
        action = {"switch": "switch", "zero_turn": "zero_turn_switch", "replacement": "replacement"}[kind]
        self.events.append(DecisionEvent(view.turn, team.index, action, "", reason, team.active, switch_to=to))

    @staticmethod
    def _find_charged_move(side: Combatant, move_id: str) -> Move:
        for move in side.charged_moves:
            if move.move_id == move_id:
                return move
        raise ValueError(f"{side.name} 没有大招 {move_id}")

    # ---- 第 3、4 步：取出并排序 ----

    def _take_due_actions(self, turn: int) -> list[_QueuedAction]:
        due: list[_QueuedAction] = []
        waiting: list[_QueuedAction] = []
        for action in self.queue:
            if action.kind != "fast":
                is_due = True  # 换人和大招在决定的当回合结算
            else:
                assert action.move is not None
                # N 回合的快招在第 T 回合开始，就在第 T+N−1 回合结算。
                finished = turn - action.turn >= action.move.turns - 1
                # 上一回合有大招：更早开始的快招不再等，本回合直接结算，剩余时长作废（Q12）。
                floating = self.charged_last_turn and action.turn < turn
                is_due = finished or floating
            (due if is_due else waiting).append(action)
        self.queue = waiting
        return due

    def _sort_by_priority(self, due: list[_QueuedAction]) -> None:
        # Python 的排序是稳定的（reverse=True 也一样）：同优先级保持排队顺序，与 PvPoke 相同。
        due.sort(key=lambda action: action.priority, reverse=True)

        if self.rules.cmp_tie == "random":
            charged = [i for i, action in enumerate(due) if action.kind == "charged"]
            if (
                len(charged) == 2
                and due[charged[0]].priority == due[charged[1]].priority
                and self.rng.random() < 0.5
            ):
                first, second = charged
                due[first], due[second] = due[second], due[first]

    def _cmp_decides_order(self) -> bool:
        """同回合的两个大招是否有先后（有先后时，后手被先手打倒就不能出招）。

        PvPoke：双方 CMP 攻击不同才有先后；相同则双方都生效（usePriority = false）。
        按当前在场的两只判断（Q20；PvPoke 训练模式只在开局按首发判断一次）。
        """
        attack_0, attack_1 = (self.active(index).cmp_attack(self.rules) for index in (0, 1))
        return attack_0 != attack_1 or self.rules.cmp_tie == "random"

    # ---- 第 5 步：结算 ----

    def _resolve(self, action: _QueuedAction, turn: int, clock: _TurnClock) -> None:
        if action.kind == "switch":
            self._switch(action, turn)
            return

        # 出招的是做决定的那只；挨打的是结算时对方在场的那只（对方先换了人，就由换上来的承受）。
        me = action.user
        opponent = self.active(1 - action.actor)
        move = action.move
        assert move is not None

        # 有效性检查。来源：Battle.js step() 里 switch(action.type) 的部分。
        cancel_reason = None
        if action.kind == "fast":
            if opponent.is_fainted:
                cancel_reason = "opponent already fainted"
            elif me.is_fainted and me.fainted_by == "charged":
                cancel_reason = "knocked out by a charged move this turn"
        else:
            if me.energy < move.energy_cost:
                cancel_reason = "not enough energy"
            elif self._cmp_decides_order() and me.is_fainted and me.fainted_by == "charged":
                cancel_reason = "knocked out by the opponent's charged move first (lost CMP)"

        if cancel_reason is not None:
            self.events.append(CancelledEvent(turn, me.index, move.move_id, cancel_reason, action.user_slot))
            return

        target_slot = self.teams[opponent.index].active
        if action.kind == "fast":
            self._use_fast_move(me, opponent, move, turn, action.user_slot, target_slot)
        else:
            self._use_charged_move(
                me, opponent, move, action.force_effect, turn, clock, action.user_slot, target_slot, action.charge
            )

    def _switch(self, action: _QueuedAction, turn: int) -> None:
        """换人。来源：Battle.js processAction 的 switch 部分。状态：参考 PvPoke。"""
        assert action.switch_to is not None and action.switch_kind is not None
        team = self.teams[action.actor]
        from_slot = team.active
        outgoing = team.active_member
        incoming = team.members[action.switch_to]

        if outgoing.is_fainted:
            # 换下去的已经倒下（倒下后换人；或者 0 回合换人前先被漂浮快招打倒）：
            # 不开始换人冷却；对手在场的那只冷却设为 1 回合，下一回合双方同时行动。
            self.active(1 - team.index).cooldown = 1
        else:
            # 换下去的保留 HP 和能量，能力等级清零；开始换人冷却。
            outgoing.atk_stage = 0
            outgoing.def_stage = 0
            team.switch_timer_ms = self.rules.switch_cooldown_ms
        team.active = action.switch_to
        incoming.cooldown = 0

        self.events.append(
            SwitchEvent(
                turn=turn,
                actor=team.index,
                from_slot=from_slot,
                to_slot=action.switch_to,
                kind=action.switch_kind,
                switch_timer_ms=team.switch_timer_ms,
                wait_ms=action.wait_ms,
            )
        )

    def _use_fast_move(
        self, me: Combatant, opponent: Combatant, move: Move, turn: int, my_slot: int, target_slot: int
    ) -> None:
        damage = calculate_damage(move, me.damage_side(), opponent.damage_side(), self.rules)
        me.energy = min(self.rules.max_energy, me.energy + move.energy_gain)
        opponent.hp = max(0, opponent.hp - damage)
        effects = self._apply_effects(move, me, opponent, shielded=False, force=None)
        if opponent.is_fainted:
            opponent.fainted_by = "fast"
        self.events.append(
            MoveEvent(
                turn=turn,
                actor=me.index,
                move_id=move.move_id,
                is_charged=False,
                damage=damage,
                shielded=False,
                shield_reason=None,
                energy_after=me.energy,
                defender_hp_after=opponent.hp,
                effects=effects,
                actor_slot=my_slot,
                target_slot=target_slot,
            )
        )

    def _use_charged_move(
        self,
        me: Combatant,
        opponent: Combatant,
        move: Move,
        force_effect: bool | None,
        turn: int,
        clock: _TurnClock,
        my_slot: int,
        target_slot: int,
        charge: float = 1.0,
    ) -> None:
        # 守方开盾时看不到攻方蓄了多少，所以问开盾时用满蓄力的伤害（用户 2026-11-24；PvPoke 的 AI 也这样）
        full_damage = calculate_damage(move, me.damage_side(), opponent.damage_side(), self.rules)
        damage = full_damage
        if charge < 1:
            damage = calculate_damage(move, me.damage_side(), opponent.damage_side(), self.rules, charge)
        me.energy -= move.energy_cost

        # 同回合的第二个大招额外计 10 秒（PvPoke 的计时方式，影响 240 秒时限和换人冷却）
        if self._cmp_decides_order() and clock.charged_used > 0 and not clock.shield_used:
            clock.extra_ms += self.rules.charged_move_ms

        shielded = False
        shield_reason = None
        defender_team = self.teams[opponent.index]
        if defender_team.shields > 0 and "instant" not in move.tags:
            view = BattleView(turn, defender_team, self.teams[me.index], self.rules)
            decision = self.policies[opponent.index].decide_shield(view, move, full_damage)
            shield_reason = decision.reason
            if decision.use_shield:
                shielded = True
                damage = self.rules.shielded_damage
                defender_team.shields -= 1
                if clock.charged_used == 0:
                    clock.extra_ms += self.rules.charged_move_ms
                clock.shield_used = True

        opponent.hp = max(0, opponent.hp - damage)
        effects = self._apply_effects(move, me, opponent, shielded, force_effect)
        if opponent.is_fainted:
            opponent.fainted_by = "charged"
        clock.charged_used += 1

        self.events.append(
            MoveEvent(
                turn=turn,
                actor=me.index,
                move_id=move.move_id,
                is_charged=True,
                damage=damage,
                shielded=shielded,
                shield_reason=shield_reason,
                energy_after=me.energy,
                defender_hp_after=opponent.hp,
                effects=effects,
                actor_slot=my_slot,
                target_slot=target_slot,
                charge=charge,
            )
        )

    def _apply_effects(
        self,
        move: Move,
        me: Combatant,
        opponent: Combatant,
        shielded: bool,
        force: bool | None,
    ) -> tuple[EffectApplied, ...]:
        """招式的能力变化。PvPoke 先改对手、再改自己，这里同样顺序（两者互不影响）。"""
        effect = move.effect
        if effect is None or not self._effect_triggers(move, me, force):
            return ()

        applied: list[EffectApplied] = []
        if effect.on_opponent is not None and (
            not shielded or self.rules.opponent_effects_apply_when_shielded
        ):
            opponent.apply_stat_change(effect.on_opponent, self.rules)
            applied.append(EffectApplied(opponent.index, effect.on_opponent))
        if effect.on_self is not None:
            me.apply_stat_change(effect.on_self, self.rules)
            applied.append(EffectApplied(me.index, effect.on_self))
        return tuple(applied)

    def _effect_triggers(self, move: Move, me: Combatant, force: bool | None) -> bool:
        assert move.effect is not None
        chance = move.effect.chance
        if chance >= 1:
            return True
        if force is not None:
            return force
        if self.rules.chance_effects == "pvpoke_counter":
            # 每用一次加上概率，计数器跨过一个整数就触发。PvPoke 只给大招建计数器，
            # 所以快招的概率效果在这个模式下从不触发（目前数据里也没有带效果的快招）。
            # 计数器记在每只宝可梦身上，换下场不清零（Q17）。
            # 来源：Battle.js useMove 里 buffApplyMeter 的部分。
            if move.move_id not in me.chance_meters:
                return False
            before = floor(me.chance_meters[move.move_id])
            me.chance_meters[move.move_id] += chance
            return floor(me.chance_meters[move.move_id]) > before
        return self.rng.random() < chance

    # ---- 第 6 步：倒下、换人回合、计时 ----

    def _record_faints(self, turn: int) -> None:
        """这一回合新倒下的，每只记一次（包括 0 回合换人前先被打倒、已经换下去的那只）。"""
        for team in self.teams:
            for slot, member in enumerate(team.members):
                if member.is_fainted and (team.index, slot) not in self._fainted_reported:
                    self._fainted_reported.add((team.index, slot))
                    self.events.append(FaintEvent(turn, team.index, slot))

    def _prepare_replacement(self, turn: int) -> None:
        """在场的倒下、队伍还有后备：下一回合是换人回合。

        PvPoke（训练模式倒下的处理，Battle.js step() 末尾）：清空双方排队中的行动，在场的冷却归零。
        换人回合里存活的一方不出招，换上来以后双方同时行动——等于倒下后换人不花回合（官方说明）。
        """
        self.replacement_turn = False
        if any(team.is_defeated for team in self.teams):
            return
        if not any(team.active_member.is_fainted for team in self.teams):
            return
        self.replacement_turn = True
        for action in self.queue:
            self.events.append(
                CancelledEvent(turn, action.actor, action.label, "cleared after a faint", action.user_slot)
            )
        self.queue = []
        for team in self.teams:
            team.active_member.cooldown = 0

    def _end_of_turn_ms(self, clock: _TurnClock) -> int:
        """回合末计入的对战时间（不含选人的等待）。来源：Battle.js step() 里 roundChargedMoveUsed 的部分。"""
        if clock.charged_used == 0:
            return self.rules.turn_ms
        if clock.shield_used:
            return self.rules.charged_move_ms * (clock.charged_used - 1)
        return self.rules.charged_move_ms


def _higher(values: tuple[int, int]) -> int | None:
    """较大的一方；相等为 None。"""
    if values[0] > values[1]:
        return 0
    if values[1] > values[0]:
        return 1
    return None
