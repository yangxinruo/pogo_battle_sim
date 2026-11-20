"""对位评估（docs/mechanics.md 13.2 D2、13.7）：我方某一只对上对手某一只，打下去大概谁占优。

3v3 的策略（team_policy.py）用它来决定倒下后换谁上、要不要主动换人。

做法照 PvPoke 训练 AI 的 evaluateMatchup / runScenario（TrainingAI.js 第 633、815 行）：
- 从双方当前的状态开始，用本项目的 1v1 引擎打一场：HP、能量、能力等级、概率效果的计数器都照现在的值；
  冷却从 0 开始（PvPoke 用当前冷却，但不带正在进行的快招，两种都不精确，这里取简单的）。
  双方都用简单规则策略（SimplePolicy），配置可以换。
- 双方盾数从 0 到现有的盾数，每种组合各打一场。按盾数给权重 [4, 4, 1]（0、1、2 盾），
  一个组合的权重是双方权重相乘，最后加权平均。
- 每场的评分用 1v1 的对战评分（battle.battle_rating）：对手损失的 HP 比例 × 500 + 自己剩余的 HP 比例 × 500。
  HP 比例按最大 HP 算，所以评估之前已经掉的 HP 也算在里面——评分衡量的是"打完时的局面"，
  不只是这一段谁赢（与 PvPoke 相同）。500 是平手。

和 PvPoke 的不同：
- PvPoke 评估当前对位时平均三种情形（双方骗盾、双方不骗、不骗，后两种其实一样），评估换人候选时只用"不骗"；
  本项目只用一种策略配置（默认是 SimplePolicy 的默认配置，会骗盾）。
- 都不考虑后备、剩余的对战时间。

评估结果按双方的完整状态缓存，同一局面不会重复模拟。
"""

from dataclasses import dataclass, field, replace

from pogo_sim.battle import Battle
from pogo_sim.combatant import Combatant
from pogo_sim.rules import BattleRules
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team

# 按盾数 0、1、2 的权重。来源：TrainingAI.js runScenario 的 shieldWeights。状态：参考 PvPoke。
SHIELD_WEIGHTS = (4, 4, 1)


@dataclass(frozen=True)
class MatchupEvaluation:
    """一次对位评估的结果，站在"我方"这一边。"""

    rating: float  # 加权平均的评分（0–1000，500 是平手）
    by_shields: tuple[tuple[int, int, int], ...]  # 每种盾数组合：(我方盾数, 对方盾数, 评分)

    @property
    def rounded(self) -> int:
        """时间线里显示用的整数评分。"""
        return round(self.rating)


def _fresh_copy(combatant: Combatant, index: int) -> Combatant:
    """模拟用的副本：状态照抄，冷却归零。不改原来的那只。"""
    return replace(
        combatant,
        index=index,
        cooldown=0,
        fainted_by=None,
        chance_meters=dict(combatant.chance_meters),
    )


def _state_key(combatant: Combatant) -> tuple:
    """决定模拟结果的全部状态（缓存用）。同一个 build 在同一份 gamemaster 下数值完全相同。"""
    return (
        combatant.build,
        combatant.hp,
        combatant.energy,
        combatant.atk_stage,
        combatant.def_stage,
        tuple(sorted(combatant.chance_meters.items())),
    )


@dataclass
class MatchupEvaluator:
    """对位评估器。policy_config 是评估时双方使用的简单规则策略配置。"""

    policy_config: SimplePolicyConfig = field(default_factory=SimplePolicyConfig)
    _cache: dict[tuple, MatchupEvaluation] = field(default_factory=dict, init=False, repr=False)

    def evaluate(
        self,
        me: Combatant,
        opponent: Combatant,
        my_shields: int,
        opponent_shields: int,
        rules: BattleRules,
    ) -> MatchupEvaluation:
        """me 对 opponent，我方最多 my_shields 个盾、对方最多 opponent_shields 个盾。"""
        if me.is_fainted or opponent.is_fainted:
            raise ValueError("不能评估已经倒下的宝可梦")
        for shields in (my_shields, opponent_shields):
            if not 0 <= shields < len(SHIELD_WEIGHTS):
                raise ValueError(f"盾数必须是 0 到 {len(SHIELD_WEIGHTS) - 1}，得到 {shields}")

        key = (_state_key(me), _state_key(opponent), my_shields, opponent_shields, rules)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        total = 0.0
        total_weight = 0
        by_shields = []
        for mine in range(my_shields + 1):
            for theirs in range(opponent_shields + 1):
                teams = (Team((_fresh_copy(me, 0),), mine), Team((_fresh_copy(opponent, 1),), theirs))
                policies = (SimplePolicy(self.policy_config), SimplePolicy(self.policy_config))
                rating = Battle(teams, policies, rules).run().ratings[0]
                weight = SHIELD_WEIGHTS[mine] * SHIELD_WEIGHTS[theirs]
                total += rating * weight
                total_weight += weight
                by_shields.append((mine, theirs, rating))

        evaluation = MatchupEvaluation(total / total_weight, tuple(by_shields))
        self._cache[key] = evaluation
        return evaluation
