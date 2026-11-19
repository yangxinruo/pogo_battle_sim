"""1v1 对战引擎：按回合结算（docs/mechanics.md 第 5 节）。

每回合的步骤与 PvPoke battle/Battle.js 的 step() 一致：
1. 冷却减少：双方冷却各减 1 回合。
2. 决定行动：冷却为 0 的一方问自己的策略。
   上一回合有大招结算时，本回合不接受新行动（"大招后的空回合"）。
3. 取出本回合要结算的行动：大招在决定的当回合结算；快招在它的最后一个回合结算；
   上一回合有大招时，更早开始、还没结算的快招都在本回合结算（"漂浮"的快招）。
4. 按优先级排序：大招 10（CMP 攻击高的一方再 +1），快招 0；同优先级保持排队顺序。
5. 逐个检查是否仍然有效，然后结算（伤害、能量、盾、能力变化）。
6. 回合结束：本回合用过大招则双方冷却都设为 1；记录快照；检查倒下和时限。

引擎从不自己做决定：出招和开盾都问策略（policy.py），原因写进时间线。
状态：参考 PvPoke，已用 PvPoke 源码的对战记录逐回合核对（tests/test_battle_pvpoke.py）。

暂不支持：换人（3v3 才需要）、形态变化、Gulp Missile 之类的特殊招式。
"""

import random
from dataclasses import dataclass, field
from math import floor
from typing import Literal

from pogo_sim.combatant import Combatant
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import Move
from pogo_sim.policy import BattleView, ChargedAction, FastAction, Policy
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.timeline import (
    CancelledEvent,
    DecisionEvent,
    EffectApplied,
    Event,
    FaintEvent,
    MoveEvent,
    SideSnapshot,
    TurnSnapshot,
)

# 行动优先级。来源：Battle.js getTurnAction。状态：参考 PvPoke。
FAST_PRIORITY = 0
CHARGED_PRIORITY = 10
CMP_WINNER_BONUS = 1


@dataclass
class _QueuedAction:
    """已经决定、等待结算的行动。"""

    kind: Literal["fast", "charged"]
    actor: int
    turn: int  # 决定的回合
    move: Move
    priority: int
    force_effect: bool | None = None


@dataclass
class _TurnClock:
    """本回合大招对"对战时间"的影响（只用于 240 秒时限，见 BattleRules.charged_move_ms）。"""

    extra_ms: int = 0
    charged_used: int = 0
    shield_used: bool = False


@dataclass(frozen=True)
class BattleResult:
    winner: int | None  # 对战评分高的一方；评分相同为 None
    ratings: tuple[int, int]  # PvPoke 的对战评分（0–1000），见 battle_rating()
    turns: int  # 一共进行了几个回合
    elapsed_ms: int  # PvPoke 口径的对战时间
    timed_out: bool
    events: list[Event] = field(repr=False)
    snapshots: list[TurnSnapshot] = field(repr=False)


def battle_rating(me: Combatant, opponent: Combatant) -> int:
    """PvPoke 的对战评分：对手损失的 HP 比例 × 500 + 自己剩余的 HP 比例 × 500，向下取整。

    这是 PvPoke 的评分方式，不是游戏规则。来源：Pokemon.js getBattleRating。
    """
    lost = (opponent.stats.hp - opponent.hp) / opponent.stats.hp
    remaining = me.hp / me.stats.hp
    return floor((500 * lost) + (500 * remaining))


def _snapshot(side: Combatant) -> SideSnapshot:
    return SideSnapshot(
        hp=side.hp,
        energy=side.energy,
        cooldown=side.cooldown,
        atk_stage=side.atk_stage,
        def_stage=side.def_stage,
        shields=side.shields,
    )


class Battle:
    """一场 1v1。用 run() 一次跑完，或者反复调用 play_turn() 逐回合推进。"""

    def __init__(
        self,
        combatants: tuple[Combatant, Combatant],
        policies: tuple[Policy, Policy],
        rules: BattleRules = PVPOKE_COMPAT,
        seed: int | None = None,
    ) -> None:
        if combatants[0].index != 0 or combatants[1].index != 1:
            raise ValueError("combatants 的 index 必须依次是 0 和 1")
        self.sides = combatants
        self.policies = policies
        self.rules = rules
        self.rng = random.Random(seed)  # 只有开关设成 "random" 时才会用到

        self.turn = 1  # 下一个要结算的回合（PvPoke 也从 1 开始数）
        self.elapsed_ms = 0
        self.charged_last_turn = False
        self.queue: list[_QueuedAction] = []
        self.events: list[Event] = []
        self.snapshots: list[TurnSnapshot] = []

    # ---- 对外接口 ----

    def run(self) -> BattleResult:
        while not self.is_over():
            self.play_turn()
        return self.result()

    def is_over(self) -> bool:
        if any(side.is_fainted for side in self.sides):
            return True
        return self.elapsed_ms > self.rules.time_limit_ms

    def result(self) -> BattleResult:
        a, b = self.sides
        ratings = (battle_rating(a, b), battle_rating(b, a))
        if ratings[0] > ratings[1]:
            winner = 0
        elif ratings[1] > ratings[0]:
            winner = 1
        else:
            winner = None
        return BattleResult(
            winner=winner,
            ratings=ratings,
            turns=self.turn - 1,
            elapsed_ms=self.elapsed_ms,
            timed_out=not any(side.is_fainted for side in self.sides),
            events=self.events,
            snapshots=self.snapshots,
        )

    def play_turn(self) -> None:
        """结算一个回合（步骤见模块说明）。"""
        turn = self.turn

        # 1. 冷却减少
        for side in self.sides:
            side.cooldown = max(0, side.cooldown - 1)

        # 2. 决定行动
        self._decide_actions(turn)

        # 3. 取出本回合要结算的行动；4. 排序
        due = self._take_due_actions(turn)
        self._sort_by_priority(due)

        # 5. 逐个结算
        clock = _TurnClock()
        for action in due:
            self._resolve(action, turn, clock)

        # 6. 回合结束
        self.charged_last_turn = any(action.kind == "charged" for action in due)
        self.elapsed_ms += clock.extra_ms + self._end_of_turn_ms(clock)
        if clock.charged_used > 0:
            # 大招之后双方冷却都设为 1：下一回合是空回合，再下一回合双方同时恢复行动。
            # 来源：Battle.js step() 末尾 poke.cooldown = 500。
            for side in self.sides:
                side.cooldown = 1
        for side in self.sides:
            if side.is_fainted:
                self.events.append(FaintEvent(turn, side.index))
        self.snapshots.append(TurnSnapshot(turn, (_snapshot(self.sides[0]), _snapshot(self.sides[1]))))
        self.turn += 1

    # ---- 第 2 步：决定行动 ----

    def _decide_actions(self, turn: int) -> None:
        # 先记下新的冷却，等双方都决定完再一起设置：后决定的一方看到的仍是回合开始时的状态。
        new_cooldowns = [side.cooldown for side in self.sides]

        for side in self.sides:
            if side.cooldown != 0:
                continue
            if self.charged_last_turn:
                # 大招后的空回合：只允许换人（1v1 没有换人），所以不问策略。
                continue

            opponent = self.sides[1 - side.index]
            decision = self.policies[side.index].decide_action(BattleView(turn, side, opponent, self.rules))

            if isinstance(decision.action, FastAction):
                move = side.fast_move
                new_cooldowns[side.index] += move.turns
                self.queue.append(_QueuedAction("fast", side.index, turn, move, FAST_PRIORITY))
                self.events.append(DecisionEvent(turn, side.index, "fast", move.move_id, decision.reason))
            elif isinstance(decision.action, ChargedAction):
                move = self._find_charged_move(side, decision.action.move_id)
                if side.energy < move.energy_cost:
                    raise ValueError(
                        f"第 {turn} 回合 {side.name} 的策略要放 {move.move_id}，但能量只有 {side.energy}"
                    )
                new_cooldowns[side.index] += 1
                priority = CHARGED_PRIORITY
                if side.cmp_attack(self.rules) > opponent.cmp_attack(self.rules):
                    priority += CMP_WINNER_BONUS
                self.queue.append(
                    _QueuedAction(
                        "charged", side.index, turn, move, priority, decision.action.force_effect
                    )
                )
                self.events.append(DecisionEvent(turn, side.index, "charged", move.move_id, decision.reason))
            else:
                raise TypeError(f"不认识的行动：{decision.action!r}")

        for side, cooldown in zip(self.sides, new_cooldowns):
            side.cooldown = cooldown

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
            if action.kind == "charged":
                is_due = True
            else:
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
        """
        attack_0, attack_1 = (side.cmp_attack(self.rules) for side in self.sides)
        return attack_0 != attack_1 or self.rules.cmp_tie == "random"

    # ---- 第 5 步：结算 ----

    def _resolve(self, action: _QueuedAction, turn: int, clock: _TurnClock) -> None:
        me = self.sides[action.actor]
        opponent = self.sides[1 - action.actor]

        # 有效性检查。来源：Battle.js step() 里 switch(action.type) 的部分。
        cancel_reason = None
        if action.kind == "fast":
            if opponent.is_fainted:
                cancel_reason = "opponent already fainted"
            elif me.is_fainted and me.fainted_by == "charged":
                cancel_reason = "knocked out by a charged move this turn"
        else:
            if me.energy < action.move.energy_cost:
                cancel_reason = "not enough energy"
            elif self._cmp_decides_order() and me.is_fainted and me.fainted_by == "charged":
                cancel_reason = "knocked out by the opponent's charged move first (lost CMP)"

        if cancel_reason is not None:
            self.events.append(CancelledEvent(turn, me.index, action.move.move_id, cancel_reason))
            return

        if action.kind == "fast":
            self._use_fast_move(me, opponent, action.move, turn)
        else:
            self._use_charged_move(me, opponent, action.move, action.force_effect, turn, clock)

    def _use_fast_move(self, me: Combatant, opponent: Combatant, move: Move, turn: int) -> None:
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
    ) -> None:
        damage = calculate_damage(move, me.damage_side(), opponent.damage_side(), self.rules)
        me.energy -= move.energy_cost

        # 同回合的第二个大招额外计 10 秒（PvPoke 的计时方式，只影响 240 秒时限）
        if self._cmp_decides_order() and clock.charged_used > 0 and not clock.shield_used:
            clock.extra_ms += self.rules.charged_move_ms

        shielded = False
        shield_reason = None
        if opponent.shields > 0 and "instant" not in move.tags:
            view = BattleView(turn, me=opponent, opponent=me, rules=self.rules)
            decision = self.policies[opponent.index].decide_shield(view, move, damage)
            shield_reason = decision.reason
            if decision.use_shield:
                shielded = True
                damage = self.rules.shielded_damage
                opponent.shields -= 1
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
            # 来源：Battle.js useMove 里 buffApplyMeter 的部分。
            if move.move_id not in me.chance_meters:
                return False
            before = floor(me.chance_meters[move.move_id])
            me.chance_meters[move.move_id] += chance
            return floor(me.chance_meters[move.move_id]) > before
        return self.rng.random() < chance

    # ---- 第 6 步：计时 ----

    def _end_of_turn_ms(self, clock: _TurnClock) -> int:
        """回合末计入的对战时间。来源：Battle.js step() 里 roundChargedMoveUsed 的部分。"""
        if clock.charged_used == 0:
            return self.rules.turn_ms
        if clock.shield_used:
            return self.rules.charged_move_ms * (clock.charged_used - 1)
        return self.rules.charged_move_ms
