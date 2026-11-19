"""把正作（主系列游戏）的六项能力值换算成 GO 的种族值。

用于未发布的宝可梦。公式来自 CLAUDE.md 的"数值换算"一节，
对应 docs/mechanics.md 2.5。
"""

from dataclasses import dataclass
from math import floor

from pogo_sim.stats import BaseStats, IVs, calculate_cp

# 较高和较低的一项在攻击里的权重（物攻与特攻）。
ATK_WEIGHT_HIGHER: float = 7 / 8
ATK_WEIGHT_LOWER: float = 1 / 8

# 较高和较低的一项在防御里的权重（物防与特防）。
DEF_WEIGHT_HIGHER: float = 5 / 8
DEF_WEIGHT_LOWER: float = 3 / 8

# 速度修正 = 1 + (速度 − SPEED_BASELINE) / SPEED_DIVISOR
SPEED_BASELINE: int = 75
SPEED_DIVISOR: int = 500

# 削弱规则：按公式换算出的种族值在 15/15/15、40 级时 CP ≥ 门槛，三项各乘一个倍率。
# 倍率乘在最后一次取整之前（见 apply_conversion_formula）。
NERF_CHECK_LEVEL: float = 40.0


@dataclass(frozen=True)
class NerfRule:
    """一条削弱规则：40 级满 IV CP ≥ cp_threshold 时，三项种族值乘 multiplier。"""

    cp_threshold: int
    multiplier: float


# 非 Mega：CP ≥ 4000 乘 0.91。
# 验证状态：已验证（超梦 300/182/214 等 5 只与游戏一致）。
STANDARD_NERF = NerfRule(cp_threshold=4000, multiplier=0.91)

# Mega / 原始回归：不受 0.91 削弱；CP 很高的乘 0.97。
# 验证状态：倍率已验证（用户确认 Mega 超梦X/Y、Mega 烈空坐、原始固拉多/盖欧卡是 0.97 倍；
#           gamemaster 里 50 只 Mega 全部符合）。
#           门槛待确认：PvPoke 数据只能确定它在 (5424, 6039] 之间——
#           Mega 烈咬陆鲨 5424 不削弱，Mega 烈空坐 6039 削弱。6000 是在区间里取的整数。
MEGA_NERF = NerfRule(cp_threshold=6000, multiplier=0.97)


@dataclass(frozen=True)
class MainSeriesStats:
    """正作的六项种族值。"""

    hp: int
    attack: int
    defense: int
    sp_attack: int
    sp_defense: int
    speed: int


def round_half_up(value: float) -> int:
    """四舍五入，0.5 一律进位。

    不用 Python 内置的 round()：它是"银行家舍入"，round(202.5) 得 202 而不是 203。
    这里的输入都是正数。
    """
    return floor(value + 0.5)


def _speed_modifier(speed: int) -> float:
    return 1 + (speed - SPEED_BASELINE) / SPEED_DIVISOR


def apply_conversion_formula(main: MainSeriesStats, multiplier: float = 1.0) -> BaseStats:
    """按公式换算，并在最后一次取整之前乘上 multiplier（不削弱时用默认的 1）。

    这个函数只是公式本身，不判断该不该削弱；判断在 convert_main_series_stats 里。

    削弱倍率要乘在最后取整之前，而不是对取整后的结果再乘再取整。
    两种做法大多数时候结果一样，但请假王的防御能区分出来：
    前者得到 166（与游戏一致），后者得到 167。
    HP 同理，倍率乘在 1.75 × HP + 50 上（雷吉奇卡斯：前者 221，后者 220）。
    """
    speed_modifier = _speed_modifier(main.speed)

    atk_higher = max(main.attack, main.sp_attack)
    atk_lower = min(main.attack, main.sp_attack)
    scaled_atk = round_half_up(
        2 * (ATK_WEIGHT_HIGHER * atk_higher + ATK_WEIGHT_LOWER * atk_lower)
    )
    atk = round_half_up(scaled_atk * speed_modifier * multiplier)

    def_higher = max(main.defense, main.sp_defense)
    def_lower = min(main.defense, main.sp_defense)
    scaled_def = round_half_up(
        2 * (DEF_WEIGHT_HIGHER * def_higher + DEF_WEIGHT_LOWER * def_lower)
    )
    def_ = round_half_up(scaled_def * speed_modifier * multiplier)

    raw_hp = 1.75 * main.hp + 50
    if multiplier == 1:
        hp = floor(raw_hp)
    else:
        hp = round_half_up(raw_hp * multiplier)

    return BaseStats(atk=atk, def_=def_, hp=hp)


@dataclass(frozen=True)
class ConversionResult:
    """一次换算的结果和过程，方便在日志里说明"为什么是这个数"。"""

    stats: BaseStats  # 最终的 GO 种族值
    formula_stats: BaseStats  # 只套公式、不削弱的结果
    check_cp: int  # formula_stats 在 15/15/15、40 级的 CP，用来判断要不要削弱
    nerf_rule: NerfRule  # 用的是哪条削弱规则
    nerfed: bool  # check_cp ≥ 门槛，乘了削弱倍率

    def describe(self) -> str:
        """一句话说明换算过程，例如"只套公式 412/222/235，40 级满 IV CP 6491 ≥ 6000，乘 0.97"。"""
        f = self.formula_stats
        rule = self.nerf_rule
        text = f"只套公式 {f.atk}/{f.def_}/{f.hp}，40 级满 IV CP {self.check_cp}"
        if self.nerfed:
            return f"{text} ≥ {rule.cp_threshold}，乘 {rule.multiplier}"
        return f"{text} < {rule.cp_threshold}，不削弱"


def convert_with_details(
    main: MainSeriesStats,
    is_mega: bool = False,
    nerf_rule: NerfRule | None = None,
) -> ConversionResult:
    """把正作种族值换算成 GO 种族值，并保留换算过程。公式见 convert_main_series_stats。"""
    if nerf_rule is None:
        nerf_rule = MEGA_NERF if is_mega else STANDARD_NERF

    formula_stats = apply_conversion_formula(main)
    max_ivs = IVs(atk=15, def_=15, hp=15)
    check_cp = calculate_cp(formula_stats, max_ivs, NERF_CHECK_LEVEL)
    nerfed = check_cp >= nerf_rule.cp_threshold

    if nerfed:
        stats = apply_conversion_formula(main, multiplier=nerf_rule.multiplier)
    else:
        stats = formula_stats

    return ConversionResult(
        stats=stats,
        formula_stats=formula_stats,
        check_cp=check_cp,
        nerf_rule=nerf_rule,
        nerfed=nerfed,
    )


def convert_main_series_stats(
    main: MainSeriesStats,
    is_mega: bool = False,
    nerf_rule: NerfRule | None = None,
) -> BaseStats:
    """把正作种族值换算成 GO 种族值。

    攻击 = round(round(2 × (7/8 × 较高 + 1/8 × 较低)) × 速度修正)   较高/较低指物攻与特攻
    防御 = round(round(2 × (5/8 × 较高 + 3/8 × 较低)) × 速度修正)   较高/较低指物防与特防
    HP   = floor(1.75 × 正作HP + 50)
    速度修正 = 1 + (速度 − 75) / 500

    然后按削弱规则判断：用上面的结果算 15/15/15、40 级的 CP，达到门槛就按倍率重新换算。
    nerf_rule 不传时，Mega 用 MEGA_NERF，其他用 STANDARD_NERF。
    想试别的门槛（比如 Mega 门槛的不同假设）时可以传自己的 NerfRule。
    想知道换算过程（有没有削弱、CP 是多少）时用 convert_with_details。
    """
    return convert_with_details(main, is_mega, nerf_rule).stats
