"""简单规则策略（第 3c 步）：一组写得清清楚楚、可以逐条调整的规则。

出招：每次可以行动时，按下面的顺序判断，第一条成立就照它做，并写出原因。
  1. 没有能量够的大招 → 快招。
  2. 快被打倒了 → 放手上伤害最高的大招（不然能量就浪费了）。
  3. 对手剩余 HP 一个快招就能打掉 → 快招。
  4. 对手没盾、手上有能直接打倒对手的大招 → 放其中最便宜的。
  5. 平时攒能量放"目标招"（怎么选见 SimplePolicyConfig.charged_move_choice）；能量不够 → 快招。
  6. 出招时机（可关）：对手的快招不是"刚好要结束" → 再打一个快招等一等。
  7. 骗盾（可关）：对手有盾 → 先放最便宜的大招，而不是目标招。
  8. 放目标招。

开盾：见 SimplePolicyConfig.shielding。

假设：双方信息完全公开（HP、能量、盾数、冷却），伤害按当前能力等级计算——和 PvPoke 一样。
只看双方在场的那只，不考虑后备（3v3 的策略见 3v3-d）。
这是有意做得简单的基准策略：PvPoke 的 AI 有更细的计算（mechanics.md 第 8 节），
两者结果的差异和原因见 docs/simple_policy_vs_pvpoke.md。
"""

from dataclasses import dataclass, field
from math import gcd
from typing import Literal

from pogo_sim.combatant import Combatant
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import Move
from pogo_sim.policy import BattleView, ChargedAction, Decision, FastAction, ShieldDecision
from pogo_sim.rules import BattleRules


@dataclass(frozen=True)
class SimplePolicyConfig:
    # 平时攒能量放哪个大招（规则 5 的"目标招"）：
    #   "best_dpe"：每点能量造成的伤害最高（PvPoke 选招的主要依据）
    #   "most_damage"：单发伤害最高
    #   "cheapest"：最便宜，也就是能放就放
    charged_move_choice: Literal["best_dpe", "most_damage", "cheapest"] = "best_dpe"

    # 规则 6：放大招前等对手的快招刚好结束，免得对手的快招"漂浮"、白拿时间。
    optimize_timing: bool = True

    # 规则 7：对手有盾时，攒够目标招的能量后先放最便宜的招，骗对手的盾。
    bait_shields: bool = True

    # 开盾：
    #   "always"：有盾就开（PvPoke 1v1 模拟的主要做法）
    #   "never"：从不开
    #   "when_low"：挨这一下后剩余 HP 低于最大 HP 的 shield_hp_fraction 才开（会被打倒时一定开）
    shielding: Literal["always", "never", "when_low"] = "always"
    shield_hp_fraction: float = 0.5


def _damage(attacker: Combatant, defender: Combatant, move: Move, rules: BattleRules) -> int:
    return calculate_damage(move, attacker.damage_side(), defender.damage_side(), rules)


def _fast(reason: str) -> Decision:
    return Decision(FastAction(), reason)


def _charged(move: Move, reason: str) -> Decision:
    return Decision(ChargedAction(move.move_id), reason)


@dataclass
class SimplePolicy:
    config: SimplePolicyConfig = field(default_factory=SimplePolicyConfig)

    # ---- 出招 ----

    def decide_action(self, view: BattleView) -> Decision:
        me, opponent, rules = view.me, view.opponent, view.rules
        damage = {move.move_id: _damage(me, opponent, move, rules) for move in me.charged_moves}
        affordable = [move for move in me.charged_moves if me.energy >= move.energy_cost]

        # 规则 1
        if not affordable:
            cheapest = min(me.charged_moves, key=lambda m: m.energy_cost)
            return _fast(f"energy {me.energy} < {cheapest.energy_cost} needed for {cheapest.move_id}")

        # 规则 2
        danger = self._danger(view)
        if danger is not None:
            move = max(affordable, key=lambda m: (damage[m.move_id], -m.energy_cost))
            return _charged(move, f"about to faint ({danger}): use highest-damage available move")

        # 规则 3
        fast_damage = _damage(me, opponent, me.fast_move, rules)
        if opponent.hp <= fast_damage:
            return _fast(f"opponent HP {opponent.hp} <= fast move damage {fast_damage}")

        # 规则 4
        if view.opponent_team.shields == 0:
            lethal = [m for m in affordable if damage[m.move_id] >= opponent.hp]
            if lethal:
                move = min(lethal, key=lambda m: (m.energy_cost, -damage[m.move_id]))
                return _charged(
                    move,
                    f"{move.move_id} deals {damage[move.move_id]} >= opponent HP {opponent.hp}, no shields",
                )

        # 规则 5
        target = self._target_move(me, damage)
        if me.energy < target.energy_cost:
            return _fast(
                f"saving for {target.move_id} ({me.energy}/{target.energy_cost} energy, "
                f"target by {self.config.charged_move_choice})"
            )

        # 规则 6
        wait = self._timing_wait(view)
        if wait is not None:
            return _fast(f"timing: {wait}")

        # 规则 7
        opponent_shields = view.opponent_team.shields
        if self.config.bait_shields and opponent_shields > 0:
            cheapest = min(me.charged_moves, key=lambda m: (m.energy_cost, -damage[m.move_id]))
            if cheapest.energy_cost < target.energy_cost:
                return _charged(
                    cheapest,
                    f"bait: opponent has {opponent_shields} shield(s), "
                    f"throw {cheapest.move_id} ({cheapest.energy_cost}) instead of {target.move_id}",
                )

        # 规则 8
        return _charged(
            target,
            f"{target.move_id} ready ({damage[target.move_id]} dmg, target by {self.config.charged_move_choice})",
        )

    def _danger(self, view: BattleView) -> str | None:
        """规则 2：是否"快被打倒了"。返回原因；不危险返回 None。

        简化：只看对手的下一个快招，或者（自己没盾时）对手现在就能放的大招。
        不像 PvPoke 那样精确推算还能活几回合，所以有时会比必要的早一点出招。
        """
        me, opponent, rules = view.me, view.opponent, view.rules
        opponent_fast = _damage(opponent, me, opponent.fast_move, rules)
        if opponent_fast >= me.hp:
            return f"opponent's fast move deals {opponent_fast} >= my HP {me.hp}"
        if view.my_team.shields == 0:
            for move in opponent.charged_moves:
                if opponent.energy >= move.energy_cost:
                    hit = _damage(opponent, me, move, rules)
                    if hit >= me.hp:
                        return f"opponent can use {move.move_id} for {hit} >= my HP {me.hp}, I have no shields"
        return None

    def _target_move(self, me: Combatant, damage: dict[str, int]) -> Move:
        """规则 5 的目标招。平手时选便宜的。"""
        choice = self.config.charged_move_choice
        moves = me.charged_moves
        if choice == "best_dpe":
            return max(moves, key=lambda m: (damage[m.move_id] / m.energy_cost, -m.energy_cost))
        if choice == "most_damage":
            return max(moves, key=lambda m: (damage[m.move_id], -m.energy_cost))
        return min(moves, key=lambda m: (m.energy_cost, -damage[m.move_id]))

    def _timing_wait(self, view: BattleView) -> str | None:
        """规则 6：要不要再打一个快招等时机。返回等待的原因；不等返回 None。

        对手的冷却（本回合还剩几回合）是 1，说明它的快招本回合结束——这时放大招，对手什么都不白拿。
        冷却是 0（它这回合也在做决定）或者更大，它的快招会在大招后的空回合"漂浮"结算，等于白拿时间。
        双方快招长度的最大公约数 g > 1 时，冷却 1 可能永远等不到，所以把"好时机"放宽到 1 到 g。
        """
        if not self.config.optimize_timing:
            return None
        me, opponent, rules = view.me, view.opponent, view.rules
        my_turns = me.fast_move.turns
        their_turns = opponent.fast_move.turns

        # 等了也对不齐的情况：对手快招只有 1 回合，或我的快招长度是对手的整数倍
        if their_turns == 1 or my_turns % their_turns == 0:
            return None
        if 1 <= opponent.cooldown <= gcd(my_turns, their_turns):
            return None  # 正是时候

        # 安全检查：这些情况下不等
        if me.energy + me.fast_move.energy_gain > rules.max_energy:
            return None  # 再打快招能量会溢出
        hits_while_waiting = max(1, (my_turns + 1) // their_turns)
        if _damage(opponent, me, opponent.fast_move, rules) * hits_while_waiting >= me.hp:
            return None  # 等的时候可能被快招打倒

        return f"opponent's fast move is not about to finish (its cooldown {opponent.cooldown})"

    # ---- 开盾 ----

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        me = view.me
        shielding = self.config.shielding
        if shielding == "always":
            return ShieldDecision(True, f"always shield ({view.my_team.shields} left)")
        if shielding == "never":
            return ShieldDecision(False, "never shield")

        remaining = me.hp - damage
        if remaining <= 0:
            return ShieldDecision(True, f"{incoming.move_id} ({damage}) would faint me")
        fraction = remaining / me.stats.hp
        threshold = self.config.shield_hp_fraction
        if fraction < threshold:
            return ShieldDecision(True, f"HP would drop to {fraction:.0%} < {threshold:.0%}")
        return ShieldDecision(False, f"HP would stay at {fraction:.0%} >= {threshold:.0%}")
