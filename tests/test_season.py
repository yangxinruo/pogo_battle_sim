"""赛季规则（pogo_sim/season.py）和大招数量检查（combatant.check_charged_moves）。"""

import pytest

from pogo_sim.combatant import PokemonBuild, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.season import (
    MEGA_CAP_52,
    MEGA_CAP_55,
    MEGA_PLUS_2,
    PVPOKE_SEASON,
    MegaLevelCap,
    SeasonRules,
    check_team,
    level_cap_for,
    season_build,
)
from pogo_sim.stats import IVs, calculate_cp

FROSLASS_MEGA_FILE = "data/custom/mega_froslass.toml"
FROSLASS_MEGA_MOVES = ("POWDER_SNOW", ("AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"))


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster(custom_files=[FROSLASS_MEGA_FILE])


# ---- 等级上限 ----
# froslass_mega 和 mewtwo_mega_x 是 supermega（默认 Mega 等级 4），lucario_mega 默认 Mega 等级 3。
LEVEL_CAP_CASES = [
    # (赛季, 宝可梦, CP 上限, 挚友, 指定 Mega 等级, 期望上限)
    (PVPOKE_SEASON, "azumarill", 1500, False, None, 50),
    (PVPOKE_SEASON, "azumarill", 1500, True, None, 51),
    (PVPOKE_SEASON, "froslass_mega", 1500, False, None, 52),
    (PVPOKE_SEASON, "froslass_mega", 1500, True, None, 52),  # 固定 52，挚友不另加
    (PVPOKE_SEASON, "froslass_mega", 1500, False, 3, 50),  # Mega 等级 3 不适用
    (PVPOKE_SEASON, "froslass_mega", 10000, False, None, 50),  # 大师联盟不适用
    (PVPOKE_SEASON, "lucario_mega", 1500, False, None, 50),
    (MEGA_CAP_52, "lucario_mega", 10000, False, None, 52),
    (MEGA_CAP_52, "lucario_mega", 1500, False, 1, 52),
    (MEGA_CAP_52, "azumarill", 10000, True, None, 51),
    (MEGA_CAP_55, "froslass_mega", 10000, False, None, 55),
    (MEGA_CAP_55, "lucario_mega", 2500, True, 2, 55),
    (MEGA_PLUS_2, "froslass_mega", 10000, False, None, 52),
    (MEGA_PLUS_2, "froslass_mega", 10000, True, None, 53),
    (MEGA_PLUS_2, "lucario_mega", 1500, True, 1, 53),
    (MEGA_PLUS_2, "azumarill", 1500, True, None, 51),
]


@pytest.mark.parametrize(
    ("season", "species_id", "cp_limit", "best_buddy", "mega_level", "expected"),
    LEVEL_CAP_CASES,
)
def test_level_cap(
    gm: GameMaster,
    season: SeasonRules,
    species_id: str,
    cp_limit: int,
    best_buddy: bool,
    mega_level: int | None,
    expected: float,
) -> None:
    species = gm.get_species(species_id)
    cap, _ = level_cap_for(species, cp_limit, season, best_buddy=best_buddy, mega_level=mega_level)
    assert cap == expected


def test_level_cap_descriptions(gm: GameMaster) -> None:
    froslass_mega = gm.get_species("froslass_mega")
    lucario_mega = gm.get_species("lucario_mega")
    assert level_cap_for(froslass_mega, 1500, PVPOKE_SEASON)[1] == (
        "Mega 等级上限 52（适用条件：只限 Mega 等级 ≥ 4，大师联盟除外）"
    )
    assert level_cap_for(froslass_mega, 10000, PVPOKE_SEASON)[1] == (
        "等级上限 50（大师联盟不适用 Mega 上限）"
    )
    assert level_cap_for(lucario_mega, 1500, PVPOKE_SEASON)[1] == (
        "等级上限 50（Mega 等级 3 低于 4，不适用 Mega 上限）"
    )
    assert level_cap_for(froslass_mega, 10000, MEGA_PLUS_2, best_buddy=True)[1] == (
        "Mega 等级上限 53 = 普通上限 51（含挚友 +1） + 2"
    )
    assert level_cap_for(lucario_mega, 10000, MEGA_CAP_55)[1] == "Mega 等级上限 55"


def test_level_cap_above_55_is_rejected(gm: GameMaster) -> None:
    season = SeasonRules(name="太高", mega_level_cap=MegaLevelCap(extra_levels=6))
    with pytest.raises(ValueError, match="等级上限 56.0 不合法"):
        level_cap_for(gm.get_species("froslass_mega"), 10000, season)


def test_non_mega_cannot_have_mega_level(gm: GameMaster) -> None:
    with pytest.raises(ValueError, match="azumarill 不是 Mega"):
        level_cap_for(gm.get_species("azumarill"), 1500, PVPOKE_SEASON, mega_level=4)


# ---- season_build ----


def test_mega_froslass_great_league(gm: GameMaster) -> None:
    """默认：IV 排名第 1，52 级超过 1500，自动降等级。"""
    build = season_build(gm, "froslass_mega", 1500, *FROSLASS_MEGA_MOVES)
    assert (build.level, build.ivs, build.mega_level) == (14.5, IVs(4, 15, 15), None)
    assert build.notes == (
        "赛季规则：PvPoke 兼容；超级联盟",
        "Mega 等级 4（默认）",
        "Mega 等级上限 52（适用条件：只限 Mega 等级 ≥ 4，大师联盟除外）",
        "IV 4/15/15：超级联盟 IV 排名第 1（能力值乘积最大；IV 下限 0，共 4096 个组合）",
        "等级 14.5：52 级时 CP 4187 超过 1500，自动降到 CP 不超过上限的最高等级（CP 1498）",
    )

    combatant = make_combatant(gm, build, index=0)
    assert combatant.cp == 1498
    assert combatant.mega_level == 4
    assert [m.move_id for m in combatant.charged_moves] == list(FROSLASS_MEGA_MOVES[1])


def test_master_league_mega_plus_2_with_best_buddy(gm: GameMaster) -> None:
    build = season_build(
        gm, "froslass_mega", 10000, *FROSLASS_MEGA_MOVES, season=MEGA_PLUS_2, best_buddy=True
    )
    assert (build.level, build.ivs) == (53.0, IVs(15, 15, 15))
    assert build.notes[-1] == "等级 53：等级上限（CP 4396）"


def test_non_mega_default_build(gm: GameMaster) -> None:
    build = season_build(gm, "azumarill", 1500, "BUBBLE", ["ICE_BEAM", "PLAY_ROUGH"])
    assert (build.level, build.ivs) == (45.5, IVs(0, 15, 15))
    assert build.notes == (
        "赛季规则：PvPoke 兼容；超级联盟",
        "等级上限 50",
        "IV 0/15/15：超级联盟 IV 排名第 1（能力值乘积最大；IV 下限 0，共 4096 个组合）",
        "等级 45.5：CP 不超过 1500 的最高等级（CP 1499）",
    )


def test_given_ivs_show_their_rank(gm: GameMaster) -> None:
    build = season_build(
        gm, "azumarill", 1500, "BUBBLE", ["ICE_BEAM"], ivs=IVs(15, 15, 15), best_buddy=True
    )
    assert build.level == 36.0
    assert build.notes[1:] == (
        "等级上限 51（含挚友 +1）",
        "IV 15/15/15（指定）：排名第 2558 / 4096（93.73%）",
        "等级 36：CP 不超过 1500 的最高等级（CP 1497）",
    )


def test_given_ivs_below_iv_floor(gm: GameMaster) -> None:
    """IV 下限只是排名用的假设，指定的 IV 低于它也可以用，只是不在排名里。"""
    build = season_build(gm, "registeel", 1500, "LOCK_ON", ["FOCUS_BLAST"], ivs=IVs(0, 15, 15))
    assert build.notes[2] == "IV 0/15/15（指定）：不在排名里（排名用的 IV 下限是 1，最低等级 1）"


def test_mega_downlevel_ignores_level_floor(gm: GameMaster) -> None:
    """Mega 超梦X 的 levelFloor 是 15，但对战中自动降等级时从 1 级起找（用户确认）。"""
    build = season_build(
        gm,
        "mewtwo_mega_x",
        1500,
        "PSYCHO_CUT",
        ["FOCUS_BLAST"],
        ivs=IVs(15, 15, 15),
        level=50,
    )
    assert build.level == 8.5
    assert build.notes[-2:] == (
        "IV 15/15/15（指定）：排名第 964 / 3375（95.62%）",
        "等级 8.5：指定的 50 级 CP 6910 超过 1500，自动降到 CP 不超过上限的最高等级（CP 1470）",
    )

    best = season_build(gm, "mewtwo_mega_x", 1500, "PSYCHO_CUT", ["FOCUS_BLAST"])
    assert best.level < 15
    assert calculate_cp(gm.get_species("mewtwo_mega_x").base_stats, best.ivs, best.level) <= 1500


def test_without_auto_downlevel_mega_is_like_any_pokemon(gm: GameMaster) -> None:
    season = SeasonRules(name="不降等级", mega_auto_downlevel=False)
    # 最低 15 级时任何 IV 都超过 1500
    with pytest.raises(ValueError, match="mewtwo_mega_x 在超级联盟没有合法的 IV 组合"):
        season_build(gm, "mewtwo_mega_x", 1500, "PSYCHO_CUT", ["FOCUS_BLAST"], season=season)
    # 指定的等级超过 CP 上限时报错，而不是降等级
    with pytest.raises(ValueError, match="froslass_mega 指定的 20 级 CP 2067 超过 1500"):
        season_build(gm, "froslass_mega", 1500, *FROSLASS_MEGA_MOVES, season=season, level=20)
    # 不指定等级时结果相同，但说明不是"自动降等级"
    build = season_build(gm, "froslass_mega", 1500, *FROSLASS_MEGA_MOVES, season=season)
    assert (build.level, build.ivs) == (14.5, IVs(4, 15, 15))
    assert build.notes[-1] == "等级 14.5：CP 不超过 1500 的最高等级（CP 1498）"


def test_given_level_errors(gm: GameMaster) -> None:
    with pytest.raises(ValueError, match="azumarill 指定的 40 级 CP 1588 超过 1500"):
        season_build(gm, "azumarill", 1500, "BUBBLE", ["ICE_BEAM"], ivs=IVs(15, 15, 15), level=40)
    with pytest.raises(ValueError, match="azumarill 指定的等级 51 超过等级上限 50"):
        season_build(gm, "azumarill", 10000, "BUBBLE", ["ICE_BEAM"], level=51)
    with pytest.raises(ValueError, match="不合法的等级：40.2"):
        season_build(gm, "azumarill", 1500, "BUBBLE", ["ICE_BEAM"], level=40.2)


def test_given_level_within_cp(gm: GameMaster) -> None:
    build = season_build(
        gm, "azumarill", 1500, "BUBBLE", ["ICE_BEAM"], ivs=IVs(15, 15, 15), level=30
    )
    assert build.level == 30
    assert build.notes[-1] == "等级 30（指定）：CP 1361"


def test_notes_do_not_affect_equality() -> None:
    a = PokemonBuild("azumarill", 45.5, IVs(0, 15, 15), "BUBBLE", ("ICE_BEAM",), notes=("甲",))
    b = PokemonBuild("azumarill", 45.5, IVs(0, 15, 15), "BUBBLE", ("ICE_BEAM",))
    assert a == b


# ---- 每队 Mega 数量 ----


def test_team_mega_limit(gm: GameMaster) -> None:
    froslass = season_build(gm, "froslass_mega", 1500, *FROSLASS_MEGA_MOVES)
    lucario = season_build(gm, "lucario_mega", 1500, "COUNTER", ["AURA_SPHERE"])
    azumarill = season_build(gm, "azumarill", 1500, "BUBBLE", ["ICE_BEAM"])

    check_team(gm, [froslass, azumarill], PVPOKE_SEASON)
    with pytest.raises(ValueError, match="每队最多 1 只 Mega.*froslass_mega、lucario_mega"):
        check_team(gm, [froslass, azumarill, lucario], PVPOKE_SEASON)
    check_team(gm, [froslass, lucario], SeasonRules(name="不限", max_megas_per_team=None))


# ---- 第三个大招 ----


@pytest.mark.parametrize(
    ("species_id", "fast", "charged", "message"),
    [
        (
            "lucario_mega",  # Mega，但没有 extraChargedMoves
            "COUNTER",
            ("AURA_SPHERE", "SHADOW_BALL", "POWER_UP_PUNCH"),
            "lucario_mega 不能带第三个大招：只有带 extraChargedMoves 的 Mega 可以",
        ),
        (
            "cramorant",  # 有 extraChargedMoves，但不是 Mega
            "PECK",
            ("SURF", "BRAVE_BIRD", "GULP_MISSILE_PIKACHU"),
            "cramorant 不能带第三个大招",
        ),
        (
            "azumarill",
            "BUBBLE",
            ("ICE_BEAM", "PLAY_ROUGH", "HYDRO_PUMP"),
            "azumarill 不能带第三个大招",
        ),
        (
            "froslass_mega",  # 第三个不在 extraChargedMoves 里
            "POWDER_SNOW",
            ("AVALANCHE", "SHADOW_BALL", "CRUNCH"),
            "froslass_mega 的第三个大招只能从 extraChargedMoves 里选（AVALANCHE_PLUS），得到 CRUNCH",
        ),
        (
            "froslass_mega",
            "POWDER_SNOW",
            ("AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS", "CRUNCH"),
            "froslass_mega 只能带 1 到 3 个大招，得到 4 个",
        ),
        ("froslass_mega", "POWDER_SNOW", (), "froslass_mega 只能带 1 到 3 个大招，得到 0 个"),
    ],
)
def test_bad_charged_moves(
    gm: GameMaster, species_id: str, fast: str, charged: tuple[str, ...], message: str
) -> None:
    build = PokemonBuild(species_id, 20, IVs(10, 10, 10), fast, charged)
    with pytest.raises(ValueError, match=message):
        make_combatant(gm, build, index=0)


def test_third_charged_move_from_gamemaster_mega(gm: GameMaster) -> None:
    build = PokemonBuild(
        "mewtwo_mega_x", 20, IVs(15, 15, 15), "PSYCHO_CUT",
        ("FOCUS_BLAST", "PSYSTRIKE", "DYNAMIC_PUNCH_PLUS"),
    )
    combatant = make_combatant(gm, build, index=0)
    assert combatant.charged_moves[2].move_id == "DYNAMIC_PUNCH_PLUS"
