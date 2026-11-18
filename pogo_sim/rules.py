"""对战机制的可配置参数。

所有会影响结算的数值和开关都集中在 BattleRules 里，引擎各处只从这里取值。
每一项都注明来源和验证状态（含义见 docs/mechanics.md 开头）。

目前只有伤害层（第 3a 步）用到的参数；回合时序的开关（docs/mechanics.md 9.3）在 3b 加入。
"""

from dataclasses import dataclass


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


# 与 PvPoke 行为一致的默认规则。回归测试都用它。
PVPOKE_COMPAT = BattleRules()
