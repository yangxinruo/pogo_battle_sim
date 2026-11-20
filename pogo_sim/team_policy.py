"""3v3 策略（3v3-d）：在简单规则策略的基础上，加上队伍层面的决定。

每个决定都写原因进时间线；和换人、开盾有关的原因里列出对位评分（evaluation.py，0–1000，500 是平手）。
规则由用户确认（2026-11-20，docs/mechanics.md 13.7），数字都是 TeamPolicyConfig 里的参数。

出招：照简单规则策略（SimplePolicy，配置是 TeamPolicyConfig.moves）。

倒下后换谁上（3v3-d1）：后备里每一只都和对手在场的那只做对位评估（双方的盾数用两队现有的盾），
换上评分最高的；评分相同按队伍顺序。对手在场的那只也倒下了（双方同时选人）时，看不到对手会换谁上，
就和对手剩下的每一只都评估，取平均。选人时不等待。

主动换人（3v3-d2，switching = "threshold"，D3 的 (b)）：能换的时候（换人冷却为 0、有后备）按顺序判断：
  1. 自己 HP 不超过最大 HP 的 25% → 不换（PvPoke 高难度 AI 的做法：快倒的留在场上）。
  2. 当前对位评分 ≥ 450 → 不换。
  3. 后备里评分最高的那只 ≥ 500、而且比当前高 100 以上 → 换上它；否则不换。
  不花回合的换人机会（大招后的空回合、对手选人的回合）用同样的规则。对手在选人时，"对手"按它剩下的每一只取平均。
  对位评估只在局面明显变化时重算（TeamPolicyConfig.reevaluate）。switching = "never" 时不主动换人（D3 的基准 (a)）。

开盾（3v3-d3）：先照简单规则策略决定；它说要开时，再看"不在必输的对位上开盾"——后备还有、而且开了盾
这一只仍然输（开盾后的对位评分 < 500），就不开，把盾留给后面。开了盾也活不下来（HP 只剩 1）时也不开。
骗盾：照简单规则策略（对手有盾就先放便宜的招），3v3 不另加规则。
"""

from dataclasses import dataclass, field, replace
from typing import Literal

from pogo_sim.combatant import Combatant
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import Move
from pogo_sim.policy import (
    BattleView,
    Decision,
    Replacement,
    ShieldDecision,
    SwitchAction,
    SwitchDecision,
)
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team


@dataclass(frozen=True)
class TeamPolicyConfig:
    # 出招和开盾的基础规则：简单规则策略的配置
    moves: SimplePolicyConfig = field(default_factory=SimplePolicyConfig)
    # 对位评估里双方用的简单规则策略配置
    evaluation: SimplePolicyConfig = field(default_factory=SimplePolicyConfig)

    # ---- 主动换人（3v3-d2）----
    # "threshold"：当前对位不好、后备里有明显更好的就换（D3 的 (b)，默认）
    # "never"：不主动换人，只在倒下后换（D3 的基准 (a)）
    switching: Literal["threshold", "never"] = "threshold"
    # 当前对位评分低于它才考虑换。PvPoke 训练 AI 用 500，对手还剩不止一只时高难度 AI 用 450。
    switch_below: float = 450
    switch_target_min: float = 500  # 换上去的那只评分至少要这么多
    switch_margin: float = 100  # 而且至少比当前高这么多
    # 自己 HP 不超过最大 HP 的这个比例时不主动换（PvPoke 高难度 AI）
    stay_hp_fraction: float = 0.25
    # 对位评估什么时候重算（只影响主动换人）：
    #   "on_change"：局面明显变化时才重算——任一方换了人（含倒下后换人）、任一方放了大招（在场的能量变少，
    #                或盾数变了）、自己的换人冷却刚走完；其余回合沿用上次的结论（PvPoke 训练 AI 的做法）
    #   "every_decision"：每次决定都重算（更准，慢很多）
    reevaluate: Literal["on_change", "every_decision"] = "on_change"

    # ---- 开盾（3v3-d3）----
    # 不在必输的对位上开盾：后备还有、开了盾仍然输（开盾后的对位评分 < save_shield_below）就不开
    save_shields_for_bench: bool = True
    save_shield_below: float = 500


@dataclass(frozen=True)
class _SwitchVerdict:
    """一次换人判断的结论，局面没明显变化时沿用。"""

    situation: tuple  # 判断时的局面（哪两只在场、双方盾数），变了就重算
    my_energy: int  # 上次看到的双方在场那只的能量：变少了说明有人放了大招，也要重算
    opponent_energy: int
    turn: int  # 判断是哪一回合做的
    to: int | None  # 换上第几只；None 是不换
    reason: str


@dataclass
class TeamPolicy:
    """config 见 TeamPolicyConfig。evaluator 可以在多场对战之间共用（共用评估的缓存）。"""

    config: TeamPolicyConfig = field(default_factory=TeamPolicyConfig)
    evaluator: MatchupEvaluator | None = None

    def __post_init__(self) -> None:
        if self.evaluator is None:
            self.evaluator = MatchupEvaluator(self.config.evaluation)
        elif self.evaluator.policy_config != self.config.evaluation:
            raise ValueError("evaluator 的策略配置必须和 config.evaluation 相同")
        self._moves = SimplePolicy(self.config.moves)
        self._verdict: _SwitchVerdict | None = None

    # ---- 出招（可能先换人）----

    def decide_action(self, view: BattleView) -> Decision:
        if view.can_switch and self.config.switching == "threshold":
            verdict, fresh = self._switch_verdict(view)
            if verdict.to is not None:
                return Decision(SwitchAction(verdict.to), verdict.reason)
            decision = self._moves.decide_action(view)
            if fresh:  # 刚重算过，把"为什么不换"也写进这一回合的原因
                return Decision(decision.action, f"{verdict.reason}; {decision.reason}")
            return decision
        self._verdict = None  # 现在换不了；冷却走完后的第一次决定会重算
        return self._moves.decide_action(view)

    # ---- 换人 ----

    def decide_zero_turn_switch(self, view: BattleView) -> SwitchDecision:
        if self.config.switching == "never":
            return SwitchDecision(None, "switching = never: no switches by choice")
        verdict, fresh = self._switch_verdict(view)
        reason = verdict.reason if fresh else f"{verdict.reason} (evaluated on turn {verdict.turn})"
        return SwitchDecision(verdict.to, reason)

    def choose_replacement(self, view: BattleView) -> Replacement:
        team = view.my_team
        opponents = self._opponents_to_face(view)
        scores = self._bench_scores(view, opponents)
        best = self._best(scores)
        return Replacement(best, 0, f"best matchup vs {self._describe(view, opponents)}: {self._ranking(team, scores)}")

    def _switch_verdict(self, view: BattleView) -> tuple[_SwitchVerdict, bool]:
        """主动换人的判断（规则见模块说明）。返回结论，以及是不是这次新算的。"""
        me, opponent = view.me, view.opponent
        situation = (id(view.my_team), view.my_team.active, view.opponent_team.active,
                     view.my_team.shields, view.opponent_team.shields)
        old = self._verdict
        if (
            self.config.reevaluate == "on_change"
            and old is not None
            and old.situation == situation
            and old.turn < view.turn
            and me.energy >= old.my_energy
            and opponent.energy >= old.opponent_energy
        ):
            # 沿用结论，但记下这次看到的能量：下次能量比这次少，就说明中间有人放了大招
            self._verdict = replace(old, my_energy=me.energy, opponent_energy=opponent.energy)
            return self._verdict, False

        to, reason = self._judge_switch(view)
        self._verdict = _SwitchVerdict(situation, me.energy, opponent.energy, view.turn, to, reason)
        return self._verdict, True

    def _judge_switch(self, view: BattleView) -> tuple[int | None, str]:
        config = self.config
        me = view.me
        hp_fraction = me.hp / me.stats.hp
        if hp_fraction <= config.stay_hp_fraction:
            return None, f"stay: HP {hp_fraction:.0%} <= {config.stay_hp_fraction:.0%}"

        opponents = self._opponents_to_face(view)
        target = self._describe(view, opponents)
        current = self._average_rating(me, opponents, view)
        if current >= config.switch_below:
            return None, f"stay: matchup vs {target} {round(current)} >= {round(config.switch_below)}"

        scores = self._bench_scores(view, opponents)
        best = self._best(scores)
        ranking = self._ranking(view.my_team, scores)
        needed = max(config.switch_target_min, current + config.switch_margin)
        situation = f"matchup vs {target} {round(current)} < {round(config.switch_below)}"
        if scores[best] < needed:
            return None, f"stay: {situation}, no bench option >= {round(needed)} ({ranking})"
        name = view.my_team.members[best].name
        return best, f"switch: {situation}, {name} {round(scores[best])} >= {round(needed)} ({ranking})"

    # ---- 开盾 ----

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        base = self._moves.decide_shield(view, incoming, damage)
        team = view.my_team
        if not base.use_shield or not self.config.save_shields_for_bench or not team.bench_slots():
            return base

        me, opponent, rules = view.me, view.opponent, view.rules
        if me.hp <= rules.shielded_damage:
            return ShieldDecision(False, f"save shield for the bench: a shield would not save me (HP {me.hp})")
        assert self.evaluator is not None
        shielded = replace(me, hp=me.hp - rules.shielded_damage)
        rating = self.evaluator.evaluate(shielded, opponent, team.shields - 1, view.opponent_team.shields, rules)
        threshold = round(self.config.save_shield_below)
        if rating.rating < self.config.save_shield_below:
            return ShieldDecision(
                False,
                f"save shield for the bench: even with a shield, matchup vs {opponent.name} "
                f"{rating.rounded} < {threshold}",
            )
        return ShieldDecision(True, f"{base.reason}; with a shield, matchup vs {opponent.name} {rating.rounded}")

    # ---- 评估的辅助 ----

    @staticmethod
    def _opponents_to_face(view: BattleView) -> list[Combatant]:
        """要面对谁：对手在场的那只；它倒下了（对手正在选人），就是对手剩下的每一只。"""
        if not view.opponent.is_fainted:
            return [view.opponent]
        opponent_team = view.opponent_team
        return [opponent_team.members[slot] for slot in opponent_team.bench_slots()]

    @staticmethod
    def _describe(view: BattleView, opponents: list[Combatant]) -> str:
        if view.opponent.is_fainted:
            return "/".join(o.name for o in opponents) + " (opponent also choosing: average)"
        return view.opponent.name

    def _average_rating(self, member: Combatant, opponents: list[Combatant], view: BattleView) -> float:
        assert self.evaluator is not None
        ratings = [
            self.evaluator.evaluate(
                member, opponent, view.my_team.shields, view.opponent_team.shields, view.rules
            ).rating
            for opponent in opponents
        ]
        return sum(ratings) / len(ratings)

    def _bench_scores(self, view: BattleView, opponents: list[Combatant]) -> dict[int, float]:
        team = view.my_team
        return {slot: self._average_rating(team.members[slot], opponents, view) for slot in team.bench_slots()}

    @staticmethod
    def _best(scores: dict[int, float]) -> int:
        return max(scores, key=lambda slot: (scores[slot], -slot))  # 评分相同取队伍里靠前的

    @staticmethod
    def _ranking(team: Team, scores: dict[int, float]) -> str:
        return ", ".join(
            f"{team.members[slot].name} {round(scores[slot])}"
            for slot in sorted(scores, key=lambda slot: (-scores[slot], slot))
        )
