"""对战机制的可配置参数。

所有会影响结算的数值和开关都集中在 BattleRules 里，引擎各处只从这里取值。
每一项都注明来源和验证状态（含义见 docs/mechanics.md 开头）。
开关的默认值都是"与 PvPoke 一致"，其他选项对应 docs/mechanics.md 9.3。
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BattleRules:
    """一套机制规则。frozen：创建后不能改，想换规则就新建一个（可以用 dataclasses.replace）。"""

    # ---- 伤害倍率（docs/mechanics.md 3.2）----
    # 来源：PvPoke battle/DamageCalculator.js 的 DamageMultiplier。状态：参考 PvPoke。
    # PvPoke 特意用 float32 精度的值（例如 1.3 写成 1.2999999523162842），
    # 会影响少数边界情况下的取整，这里原样照搬。
    pvp_bonus: float = 1.2999999523162841796875  # 所有招式的 PvP 加成，名义值 1.3
    stab: float = 1.2000000476837158203125  # 本系加成，名义值 1.2
    super_effective: float = 1.60000002384185791015625  # 效果绝佳，名义值 1.6
    resisted: float = 0.625  # 效果不好
    double_resisted: float = 0.390625  # "免疫"在 GO 里是 0.390625 倍
    shadow_attack: float = 1.2  # 暗影宝可梦的攻击倍率
    shadow_defense: float = 0.83333331  # 暗影宝可梦的防御倍率

    # Mega 专属招式（gamemaster 里 isMegaMove 的招式）按 Mega 等级 1–4 的伤害倍率。
    # 来源：DamageCalculator.js DamageMultiplier.MEGA_BONUS。状态：已验证（用户确认是游戏正式机制），数值参考 PvPoke。
    mega_move_bonus: tuple[float, float, float, float] = (
        1.0,
        1.10000002384185791015625,
        1.2000000476837158203125,
        1.2999999523162841796875,
    )

    # ---- 能力等级（docs/mechanics.md 6.3）----
    # 来源：gamemaster settings.maxBuffStages / buffDivisor。状态：参考 PvPoke，与 CLAUDE.md 一致。
    max_stat_stage: int = 4  # 攻击和防御各自 −4 到 +4 级
    stat_stage_divisor: int = 4  # 倍率：s > 0 时 (4 + s) / 4；s ≤ 0 时 4 / (4 − s)

    # ---- 能量与盾（docs/mechanics.md 4、6.1）----
    # 来源：PvPoke Battle.js useMove、Player.js。状态：参考 PvPoke。
    max_energy: int = 100
    max_shields: int = 2
    shielded_damage: int = 1  # 被盾挡下的大招造成的伤害

    # ---- 时间（docs/mechanics.md 5.1、6.5）----
    # 引擎以回合为单位（1 回合 = 0.5 秒）。下面两项只用于判断 240 秒时限。
    # PvPoke 把每次大招折算成 10 秒（大招小游戏的时长）计入对战时间，同回合的第二个大招再加 10 秒。
    # 来源：Battle.js step() 末尾和 useMove() 里对 time 的累加。
    # 状态：大招期间计时继续走——已验证（用户实战经验）；每次计 10 秒——参考 PvPoke。
    turn_ms: int = 500
    charged_move_ms: int = 10000
    time_limit_ms: int = 240000  # 对战时间超过这个值就结束（PvPoke：time > 240000）

    # ---- 机制开关（docs/mechanics.md 9.3）----
    # 同回合双方都放大招、且比较用的攻击相等时怎么办。
    #   "both_fire"：没有先后，双方大招都生效，即使被打倒（PvPoke）
    #   "random"：随机决定先后，后手被打倒则不生效（用户印象中的游戏行为，Q8，待确认）
    cmp_tie: Literal["both_fire", "random"] = "both_fire"

    # CMP 比较哪个攻击。
    #   True：不含暗影加成、不含能力等级的攻击，即 CPM × (种族值 + IV)（PvPoke）
    #   False：含暗影和能力等级的有效攻击（Q8，待确认）
    cmp_uses_raw_attack: bool = True

    # 被盾挡下的大招，对对手的能力变化是否仍然生效（Q6，待确认）。
    # PvPoke：生效。对自己的能力变化（如 Close Combat 降自己防御）不受影响，总是生效。
    opponent_effects_apply_when_shielded: bool = True

    # 概率性能力变化（如 Night Slash 12.5% 提升攻击）怎么决定是否触发（Q7）。
    #   "pvpoke_counter"：PvPoke 的确定性计数器，每用一次累加概率，跨过整数时触发
    #   "random"：按概率随机（需要给对战一个随机种子才能复现）
    # 剧本策略可以逐次指定是否触发，此时不看这个开关。
    chance_effects: Literal["pvpoke_counter", "random"] = "pvpoke_counter"


# 与 PvPoke 行为一致的默认规则。回归测试都用它。
PVPOKE_COMPAT = BattleRules()
