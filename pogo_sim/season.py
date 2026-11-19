"""赛季规则：等级上限（含 Mega 的特殊上限）、CP 超上限的 Mega 怎么处理、每队几只 Mega。

按赛季规则建立配置（等级、IV）用 season_build；它会把"为什么是这个等级和 IV"写进 build.notes。
说明见 docs/mechanics.md 第 7 节和 9.1。

几种规则（都可以自己组合新的 SeasonRules）：
- PVPOKE_SEASON（默认）：PvPoke 当前的做法。只有 Mega 等级 4 的上限是 52，大师联盟仍是 50。
- MEGA_CAP_52：Mega 等级上限固定 52。
- MEGA_CAP_55：Mega 进化后等级提到 55。
- MEGA_PLUS_2：Mega 比普通上限多 2 级（加上挚友加成最高 53）。
后三种是用户描述过的赛季规则，对所有 Mega 等级生效，大师联盟也适用（用户确认，2026-11-18）。

这里只管"上限"。不指定等级时，配置默认取上限内 CP 合法的最高等级，
所以"等级上限 55"和"自动提到 55"在默认设置下结果一样。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pogo_sim.combatant import UNCAPPED_CP, PokemonBuild, resolve_mega_level
from pogo_sim.cpm import MAX_LEVEL, MIN_LEVEL, is_valid_level
from pogo_sim.gamemaster import GameMaster, Species
from pogo_sim.iv_ranking import (
    find_rank,
    pvpoke_iv_floor,
    pvpoke_level_floor,
    rank_ivs,
)
from pogo_sim.stats import IVs, calculate_cp, highest_level_under_cp

# 联盟名称，只用于说明文字。
LEAGUE_NAMES: dict[int, str] = {
    500: "小小杯",
    1500: "超级联盟",
    2500: "高级联盟",
    UNCAPPED_CP: "大师联盟",
}


def league_name(cp_limit: int) -> str:
    return LEAGUE_NAMES.get(cp_limit, f"CP {cp_limit} 联盟")


@dataclass(frozen=True)
class MegaLevelCap:
    """Mega 的等级上限规则。

    fixed 不是 None 时，上限就是 fixed（挚友加成不再另加）；
    否则上限 = 普通上限 + 挚友加成 + extra_levels。
    只对 Mega 等级 ≥ min_mega_level 的 Mega 生效；in_master_league 为 False 时大师联盟不生效。
    不生效时 Mega 和普通宝可梦一样。
    """

    fixed: float | None = None
    extra_levels: float = 0.0
    min_mega_level: int = 1
    in_master_league: bool = True

    def conditions(self) -> str:
        """适用条件，例如"只限 Mega 等级 ≥ 4，大师联盟除外"；没有限制时为空字符串。"""
        parts = []
        if self.min_mega_level > 1:
            parts.append(f"只限 Mega 等级 ≥ {self.min_mega_level}")
        if not self.in_master_league:
            parts.append("大师联盟除外")
        return "，".join(parts)


@dataclass(frozen=True)
class SeasonRules:
    """一个赛季的规则。"""

    name: str
    level_cap: float = 50.0  # 普通宝可梦的等级上限
    best_buddy_bonus: float = 1.0  # 挚友加成的等级
    mega_level_cap: MegaLevelCap = field(default_factory=MegaLevelCap)
    # CP 超过联盟上限的 Mega 在对战中自动降到合法等级。验证状态：用户确认（CLAUDE.md；具体规则未公开）。
    # 降等级是对战时的临时调整，所以不看 levelFloor（能获得的最低等级），从 1 级起找（用户确认，2026-11-19）。
    # False 时 Mega 和普通宝可梦一样：本身的等级就要符合 CP 上限，也看 levelFloor。
    mega_auto_downlevel: bool = True
    # 每队最多几只 Mega；None 表示不限。验证状态：用户确认每队 1 只（2026-11-18）。
    max_megas_per_team: int | None = 1


# PvPoke 当前的做法：Mega 等级 4 在有 CP 上限的联盟提到 52（Pokemon.js 第 294 行）。
PVPOKE_SEASON = SeasonRules(
    name="PvPoke 兼容",
    mega_level_cap=MegaLevelCap(fixed=52, min_mega_level=4, in_master_league=False),
)
MEGA_CAP_52 = SeasonRules(name="Mega 上限 52", mega_level_cap=MegaLevelCap(fixed=52))
MEGA_CAP_55 = SeasonRules(name="Mega 提到 55", mega_level_cap=MegaLevelCap(fixed=55))
MEGA_PLUS_2 = SeasonRules(name="Mega 多 2 级", mega_level_cap=MegaLevelCap(extra_levels=2))


def level_cap_for(
    species: Species,
    cp_limit: int,
    season: SeasonRules,
    *,
    best_buddy: bool = False,
    mega_level: int | None = None,
) -> tuple[float, str]:
    """这只宝可梦在这个联盟、这个赛季的等级上限，以及一句说明。

    mega_level 不传时用默认值（见 combatant.resolve_mega_level）。
    """
    normal_cap = season.level_cap + (season.best_buddy_bonus if best_buddy else 0)
    buddy_text = f"（含挚友 +{season.best_buddy_bonus:g}）" if best_buddy else ""
    normal_text = f"等级上限 {normal_cap:g}{buddy_text}"

    level = resolve_mega_level(species, mega_level)
    if level is None:
        cap, text = normal_cap, normal_text
    else:
        rule = season.mega_level_cap
        is_master = cp_limit >= UNCAPPED_CP
        if level < rule.min_mega_level:
            cap = normal_cap
            text = f"{normal_text}（Mega 等级 {level} 低于 {rule.min_mega_level}，不适用 Mega 上限）"
        elif is_master and not rule.in_master_league:
            cap = normal_cap
            text = f"{normal_text}（大师联盟不适用 Mega 上限）"
        else:
            if rule.fixed is not None:
                cap = rule.fixed
                text = f"Mega 等级上限 {cap:g}"
            else:
                cap = normal_cap + rule.extra_levels
                text = f"Mega 等级上限 {cap:g} = 普通上限 {normal_cap:g}{buddy_text} + {rule.extra_levels:g}"
            if rule.conditions():
                text += f"（适用条件：{rule.conditions()}）"

    if not (is_valid_level(cap) and cap <= MAX_LEVEL):
        raise ValueError(f"算出的等级上限 {cap} 不合法（应为 1 到 {MAX_LEVEL:g}，步长 0.5）")
    return cap, text


def season_build(
    gm: GameMaster,
    species_id: str,
    cp_limit: int,
    fast_move_id: str,
    charged_move_ids: Sequence[str],
    *,
    season: SeasonRules = PVPOKE_SEASON,
    ivs: IVs | None = None,
    level: float | None = None,
    best_buddy: bool = False,
    mega_level: int | None = None,
) -> PokemonBuild:
    """按赛季规则建立配置。选择过程写在返回值的 notes 里。

    ivs 不传：用这个联盟 IV 排名第 1 的组合（IV 下限用 PvPoke 的默认值，见 iv_ranking.py）。
    level 不传：等级上限内 CP 不超过联盟上限的最高等级。
    level 传了：不能超过等级上限。CP 超过联盟上限时，Mega 按赛季规则自动降等级，普通宝可梦报错。
    招式和大招数量在 make_combatant 里检查。
    """
    species = gm.get_species(species_id)
    resolved_mega_level = resolve_mega_level(species, mega_level)
    is_mega = resolved_mega_level is not None
    downlevel = is_mega and season.mega_auto_downlevel

    cap, cap_text = level_cap_for(
        species, cp_limit, season, best_buddy=best_buddy, mega_level=mega_level
    )
    notes = [f"赛季规则：{season.name}；{league_name(cp_limit)}"]
    if is_mega:
        source = "指定" if mega_level is not None else "默认"
        notes.append(f"Mega 等级 {resolved_mega_level}（{source}）")
    notes.append(cap_text)

    # 最低等级：Mega 自动降等级时从 1 级起；其他情况用 PvPoke 的默认（levelFloor）。
    if downlevel:
        level_floor = MIN_LEVEL
    else:
        level_floor = pvpoke_level_floor(species, cp_limit)
    iv_floor = pvpoke_iv_floor(species)
    ranking = rank_ivs(
        species.base_stats, cp_limit, level_cap=cap, level_floor=level_floor, iv_floor=iv_floor
    )

    # ---- IV ----
    if ivs is None:
        if not ranking:
            raise ValueError(
                f"{species_id} 在{league_name(cp_limit)}没有合法的 IV 组合"
                f"（{level_floor:g} 级时 CP 就超过 {cp_limit}）"
            )
        ivs = ranking[0].ivs
        notes.append(
            f"IV {_iv_text(ivs)}：{league_name(cp_limit)} IV 排名第 1"
            f"（能力值乘积最大；IV 下限 {iv_floor}，共 {len(ranking)} 个组合）"
        )
    else:
        entry = find_rank(ranking, ivs)
        if entry is None:
            rank_text = f"不在排名里（排名用的 IV 下限是 {iv_floor}，最低等级 {level_floor:g}）"
        else:
            rank_text = f"排名第 {entry.rank} / {len(ranking)}（{entry.percent_of_best:.2f}%）"
        notes.append(f"IV {_iv_text(ivs)}（指定）：{rank_text}")

    # ---- 等级 ----
    legal_level = highest_level_under_cp(species.base_stats, ivs, cp_limit, cap, level_floor)
    if level is None:
        if legal_level is None:
            raise ValueError(
                f"{species_id} IV {_iv_text(ivs)} 在 {level_floor:g} 级时 CP 就超过 {cp_limit}"
            )
        level = legal_level
        cap_cp = calculate_cp(species.base_stats, ivs, cap)
        if level == cap:
            notes.append(f"等级 {level:g}：等级上限（CP {cap_cp}）")
        elif downlevel:
            notes.append(
                f"等级 {level:g}：{cap:g} 级时 CP {cap_cp} 超过 {cp_limit}，"
                f"自动降到 CP 不超过上限的最高等级（CP {calculate_cp(species.base_stats, ivs, level)}）"
            )
        else:
            notes.append(
                f"等级 {level:g}：CP 不超过 {cp_limit} 的最高等级"
                f"（CP {calculate_cp(species.base_stats, ivs, level)}）"
            )
    else:
        if not is_valid_level(level):
            raise ValueError(f"不合法的等级：{level}")
        if level > cap:
            raise ValueError(f"{species_id} 指定的等级 {level:g} 超过等级上限 {cap:g}")
        given_cp = calculate_cp(species.base_stats, ivs, level)
        if given_cp <= cp_limit:
            notes.append(f"等级 {level:g}（指定）：CP {given_cp}")
        elif downlevel:
            # 降到不超过指定等级、CP 合法的最高等级
            lowered = highest_level_under_cp(species.base_stats, ivs, cp_limit, level, MIN_LEVEL)
            if lowered is None:
                raise ValueError(f"{species_id} IV {_iv_text(ivs)} 在 1 级时 CP 就超过 {cp_limit}")
            notes.append(
                f"等级 {lowered:g}：指定的 {level:g} 级 CP {given_cp} 超过 {cp_limit}，"
                f"自动降到 CP 不超过上限的最高等级（CP {calculate_cp(species.base_stats, ivs, lowered)}）"
            )
            level = lowered
        else:
            raise ValueError(
                f"{species_id} 指定的 {level:g} 级 CP {given_cp} 超过 {cp_limit}"
            )

    return PokemonBuild(
        species_id=species_id,
        level=level,
        ivs=ivs,
        fast_move_id=fast_move_id,
        charged_move_ids=tuple(charged_move_ids),
        mega_level=mega_level,
        notes=tuple(notes),
    )


def check_team(gm: GameMaster, builds: Sequence[PokemonBuild], season: SeasonRules) -> None:
    """检查一队是否符合赛季规则（目前只检查 Mega 数量）。不符合时报错。"""
    limit = season.max_megas_per_team
    if limit is None:
        return
    megas = [b.species_id for b in builds if gm.get_species(b.species_id).is_mega]
    if len(megas) > limit:
        raise ValueError(
            f"每队最多 {limit} 只 Mega（赛季规则：{season.name}），这队有 {len(megas)} 只："
            + "、".join(megas)
        )


def _iv_text(ivs: IVs) -> str:
    return f"{ivs.atk}/{ivs.def_}/{ivs.hp}"
