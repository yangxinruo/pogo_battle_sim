"""3v3 策略（3v3-d）：在简单规则策略的基础上，加上队伍层面的决定。

每个决定都写原因进时间线；和换人有关的原因里列出对位评分（evaluation.py，0–1000，500 是平手）。

现在完成的部分（3v3-d1）：
- 出招、开盾：照简单规则策略（SimplePolicy，配置是 TeamPolicyConfig.moves）。
- 倒下后换谁上：后备里每一只都和对手在场的那只做对位评估（双方的盾数用两队现有的盾），换上评分最高的；
  评分相同按队伍顺序。对手在场的那只也倒下了（双方同时选人）时，看不到对手会换谁上，
  就和对手剩下的每一只都评估，取平均。选人时不等待。
- 主动换人：不换（docs/mechanics.md 13.2 D3 的基准 (a)）。

还没做（等用户定规则）：按阈值主动换人（D3 的 (b)）、全队一起考虑的开盾和骗盾。
"""

from dataclasses import dataclass, field
from typing import Literal

from pogo_sim.combatant import Combatant
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import Move
from pogo_sim.policy import BattleView, Decision, Replacement, ShieldDecision, SwitchDecision
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig


@dataclass(frozen=True)
class TeamPolicyConfig:
    # 出招和开盾用的简单规则策略配置
    moves: SimplePolicyConfig = field(default_factory=SimplePolicyConfig)
    # 对位评估里双方用的简单规则策略配置
    evaluation: SimplePolicyConfig = field(default_factory=SimplePolicyConfig)
    # 主动换人："never"：不主动换人，只在倒下后换（D3 的基准 (a)）。阈值换人在 3v3-d2 加入。
    switching: Literal["never"] = "never"


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

    # ---- 出招、开盾：照简单规则策略 ----

    def decide_action(self, view: BattleView) -> Decision:
        return self._moves.decide_action(view)

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        return self._moves.decide_shield(view, incoming, damage)

    # ---- 换人 ----

    def decide_zero_turn_switch(self, view: BattleView) -> SwitchDecision:
        return SwitchDecision(None, "switching = never: no switches by choice")

    def choose_replacement(self, view: BattleView) -> Replacement:
        team = view.my_team
        opponents = self._opponents_to_face(view)
        scores = {
            slot: self._average_rating(team.members[slot], opponents, view) for slot in team.bench_slots()
        }
        best = max(scores, key=lambda slot: (scores[slot], -slot))  # 评分相同取队伍里靠前的

        if view.opponent.is_fainted:
            target = "/".join(o.name for o in opponents) + " (opponent also choosing: average)"
        else:
            target = view.opponent.name
        ranking = ", ".join(
            f"{team.members[slot].name} {round(scores[slot])}"
            for slot in sorted(scores, key=lambda slot: (-scores[slot], slot))
        )
        return Replacement(best, 0, f"best matchup vs {target}: {ranking}")

    @staticmethod
    def _opponents_to_face(view: BattleView) -> list[Combatant]:
        """换上来要面对谁：对手在场的那只；它也倒下了，就是对手剩下的每一只。"""
        if not view.opponent.is_fainted:
            return [view.opponent]
        opponent_team = view.opponent_team
        return [opponent_team.members[slot] for slot in opponent_team.bench_slots()]

    def _average_rating(self, member: Combatant, opponents: list[Combatant], view: BattleView) -> float:
        assert self.evaluator is not None
        ratings = [
            self.evaluator.evaluate(
                member, opponent, view.my_team.shields, view.opponent_team.shields, view.rules
            ).rating
            for opponent in opponents
        ]
        return sum(ratings) / len(ratings)
