"""IV 排名：在联盟 CP 上限下，按能力值乘积给全部 IV 组合排序。

对应 PvPoke src/js/pokemon/Pokemon.js 的 generateIVCombinations
（commit d02018eb6bfc4a041cca69d7bc9de0d5179a8365），说明见 docs/mechanics.md 第 11 节。
验证状态：参考 PvPoke（排名顺序与 PvPoke 逐个核对一致，见 tests/test_iv_ranking.py）。

做法：
1. 每个 IV 组合（每项 iv_floor 到 15）找出 CP 不超过上限的最高等级，
   范围是 level_floor 到 level_cap。在 level_floor 就已经超过上限的组合不参加排名。
2. 在这个等级下算实际攻击、防御、HP。能力值乘积 = HP × 攻击 × 防御（HP 是取整后的整数）。
3. 按能力值乘积从大到小排序。乘积完全相同时，按 HP IV、防御 IV、攻击 IV 从高到低排
   （这是 PvPoke 枚举组合的顺序，它的排序是稳定排序，所以并列时保持这个顺序）。

"排名第 1"只是能力值乘积最大，不代表实战最好：有时更高的攻击能拿到关键的伤害断点。
"""

from dataclasses import dataclass

from pogo_sim.cpm import MIN_LEVEL
from pogo_sim.gamemaster import Species
from pogo_sim.stats import (
    MAX_IV,
    BaseStats,
    BattleStats,
    IVs,
    calculate_battle_stats,
    calculate_cp,
    highest_level_under_cp,
)

# ---- PvPoke 默认的 IV 下限 ----
# PvPoke 按标签假设"一般能拿到的最低 IV"（generateIVCombinations 开头），
# 源码没有写理由。括号里是对应的游戏规则，是我们的推测。验证状态：参考 PvPoke。
DEFAULT_IV_FLOOR: int = 0
LEGENDARY_IV_FLOOR: int = 1  # 传说 / 究极异兽，野外不出现的（好友交换最低 1）
SHADOW_LEGENDARY_IV_FLOOR: int = 6  # 暗影传说 / 暗影究极异兽（暗影 Raid 最低 6）
UNTRADEABLE_IV_FLOOR: int = 10  # 不能交换的（调查和 Raid 最低 10）
# PvPoke 还有一条：当前招式里有 RETURN（报恩）时下限是 2（净化后每项 IV 加 2）。
# 当前 gamemaster 里没有宝可梦能学 RETURN，这条用不上，没有实现。

# PvPoke 在 CP 上限 ≤ 500 时忽略 levelFloor，从 1 级开始找（源码注释说"暂时"如此）。
LITTLE_CUP_MAX_CP: int = 500


@dataclass(frozen=True)
class IVRankEntry:
    """排名里的一个 IV 组合。"""

    rank: int  # 1 是能力值乘积最大的
    ivs: IVs
    level: float  # CP 不超过上限的最高等级
    cp: int
    stats: BattleStats  # 这个等级下的实际攻击、防御、HP
    stat_product: float  # HP × 攻击 × 防御
    percent_of_best: float  # 能力值乘积占第 1 名的百分比，第 1 名是 100

    def describe(self) -> str:
        """一句话说明，例如"IV 4/15/15，14.5 级，CP 1498，第 1 名（100.00%）"。"""
        iv = self.ivs
        return (
            f"IV {iv.atk}/{iv.def_}/{iv.hp}，{self.level:g} 级，CP {self.cp}，"
            f"第 {self.rank} 名（{self.percent_of_best:.2f}%）"
        )


def stat_product(stats: BattleStats) -> float:
    """能力值乘积 = HP × 攻击 × 防御。

    按 PvPoke 的顺序先乘 HP 再乘攻击、防御。浮点乘法换顺序，最后一位可能不同，
    会影响"乘积相同"的判断（比如种族攻击等于种族防御、攻防 IV 互换的两个组合）。
    """
    return stats.hp * stats.atk * stats.def_


def rank_ivs(
    base: BaseStats,
    cp_limit: int,
    *,
    level_cap: float = 50.0,
    level_floor: float = MIN_LEVEL,
    iv_floor: int = DEFAULT_IV_FLOOR,
) -> list[IVRankEntry]:
    """给全部 IV 组合排名，返回按名次排好的列表（第 1 名在最前）。

    cp_limit：联盟的 CP 上限；没有上限的联盟传 10000（全部组合都在 level_cap）。
    level_cap：最高等级，例如 50、51（最佳伙伴），或者 Mega 的特殊上限。
    level_floor：最低等级；在这个等级就超过 CP 上限的组合不参加排名。
    iv_floor：每项 IV 的最低值。
    没有任何组合合法时返回空列表。
    """
    if not 0 <= iv_floor <= MAX_IV:
        raise ValueError(f"IV 下限 {iv_floor} 超出范围 0–{MAX_IV}")

    # 枚举顺序和 PvPoke 相同：HP IV 在最外层，从 15 往下；然后防御 IV、攻击 IV。
    candidates: list[tuple[IVs, float, int, BattleStats, float]] = []
    for hp_iv in range(MAX_IV, iv_floor - 1, -1):
        for def_iv in range(MAX_IV, iv_floor - 1, -1):
            for atk_iv in range(MAX_IV, iv_floor - 1, -1):
                ivs = IVs(atk=atk_iv, def_=def_iv, hp=hp_iv)
                level = highest_level_under_cp(base, ivs, cp_limit, level_cap, level_floor)
                if level is None:
                    continue
                cp = calculate_cp(base, ivs, level)
                stats = calculate_battle_stats(base, ivs, level)
                candidates.append((ivs, level, cp, stats, stat_product(stats)))

    # 稳定排序：乘积相同的保持上面的枚举顺序（reverse=True 也保持稳定）。
    candidates.sort(key=lambda c: c[4], reverse=True)

    if not candidates:
        return []
    best_product = candidates[0][4]
    return [
        IVRankEntry(
            rank=i + 1,
            ivs=ivs,
            level=level,
            cp=cp,
            stats=stats,
            stat_product=product,
            percent_of_best=100 * product / best_product,
        )
        for i, (ivs, level, cp, stats, product) in enumerate(candidates)
    ]


def find_rank(ranking: list[IVRankEntry], ivs: IVs) -> IVRankEntry | None:
    """在排名里找某个 IV 组合；不在排名里（低于 IV 下限，或在最低等级就超过上限）时返回 None。"""
    for entry in ranking:
        if entry.ivs == ivs:
            return entry
    return None


def pvpoke_iv_floor(species: Species) -> int:
    """PvPoke 给这只宝可梦默认的 IV 下限（按标签，见上面的常数）。

    判断顺序照 PvPoke：后面的条件成立时覆盖前面的结果。
    """
    floor = DEFAULT_IV_FLOOR
    is_legendary = "legendary" in species.tags or "ultrabeast" in species.tags
    if is_legendary and "wildlegendary" not in species.tags:
        floor = LEGENDARY_IV_FLOOR
    if is_legendary and species.is_shadow:
        floor = SHADOW_LEGENDARY_IV_FLOOR
    if "untradeable" in species.tags:
        floor = UNTRADEABLE_IV_FLOOR
    return floor


def pvpoke_level_floor(species: Species, cp_limit: int) -> float:
    """PvPoke 排名时用的最低等级：gamemaster 的 levelFloor，CP 上限 ≤ 500 时是 1 级。"""
    if cp_limit <= LITTLE_CUP_MAX_CP:
        return MIN_LEVEL
    return species.level_floor


def rank_species_ivs(
    species: Species,
    cp_limit: int,
    *,
    level_cap: float = 50.0,
    iv_floor: int | None = None,
    level_floor: float | None = None,
) -> list[IVRankEntry]:
    """给一种宝可梦排名。iv_floor / level_floor 不传时用 PvPoke 的默认值。"""
    if iv_floor is None:
        iv_floor = pvpoke_iv_floor(species)
    if level_floor is None:
        level_floor = pvpoke_level_floor(species, cp_limit)
    return rank_ivs(
        species.base_stats,
        cp_limit,
        level_cap=level_cap,
        level_floor=level_floor,
        iv_floor=iv_floor,
    )
