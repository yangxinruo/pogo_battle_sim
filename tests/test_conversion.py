"""正作能力值 → GO 种族值换算的测试。"""

import pytest

from pogo_sim.conversion import (
    MEGA_NERF,
    MainSeriesStats,
    NerfRule,
    apply_conversion_formula,
    convert_main_series_stats,
    round_half_up,
)
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.stats import BaseStats


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def test_round_half_up() -> None:
    assert round_half_up(202.5) == 203  # 内置 round(202.5) 会得到 202
    assert round_half_up(202.49) == 202
    assert round_half_up(203.5) == 204


MEGA_MEWTWO_X = MainSeriesStats(
    hp=106, attack=190, defense=100, sp_attack=154, sp_defense=100, speed=130
)


def test_mega_mewtwo_x_formula_only() -> None:
    """只套公式、不削弱时是 412/222/235（CLAUDE.md 最初给的验算值）。"""
    assert apply_conversion_formula(MEGA_MEWTWO_X) == BaseStats(atk=412, def_=222, hp=235)


def test_mega_mewtwo_x_with_mega_nerf(gm: GameMaster) -> None:
    """用户确认游戏里是 0.97 倍削弱后的 399/215/228，与 PvPoke 数据一致。"""
    expected = BaseStats(atk=399, def_=215, hp=228)
    assert convert_main_series_stats(MEGA_MEWTWO_X, is_mega=True) == expected
    assert gm.get_species("mewtwo_mega_x").base_stats == expected


def test_custom_nerf_rule() -> None:
    """门槛可以换：把 Mega 门槛提到 7000，Mega 超梦X 就不削弱了。"""
    lenient = NerfRule(cp_threshold=7000, multiplier=MEGA_NERF.multiplier)
    assert convert_main_series_stats(
        MEGA_MEWTWO_X, is_mega=True, nerf_rule=lenient
    ) == BaseStats(atk=412, def_=222, hp=235)


# 正作种族值（HP, 攻击, 防御, 特攻, 特防, 速度）。换算结果应与 gamemaster 里的 GO 种族值一致。
NON_MEGA_CASES = {
    # 不触发削弱
    "bulbasaur": (45, 49, 49, 65, 65, 45),
    "azumarill": (100, 50, 80, 60, 80, 50),
    "medicham": (60, 60, 75, 60, 75, 80),
    "registeel": (80, 75, 150, 75, 150, 50),
    "swampert": (100, 110, 90, 85, 90, 60),
    "garchomp": (108, 130, 95, 80, 85, 102),
    # 触发 0.91 削弱（15/15/15、40 级 CP ≥ 4000）
    "mewtwo": (106, 110, 90, 154, 90, 130),
    "dialga": (100, 120, 120, 150, 100, 90),
    "groudon": (100, 150, 140, 100, 90, 90),
    "slaking": (150, 160, 100, 95, 65, 100),  # 防御 166：区分削弱倍率乘在取整前还是取整后
    "regigigas": (110, 160, 110, 80, 110, 100),  # HP 221：同上
}


@pytest.mark.parametrize("species_id", NON_MEGA_CASES)
def test_non_mega_matches_gamemaster(gm: GameMaster, species_id: str) -> None:
    main = MainSeriesStats(*NON_MEGA_CASES[species_id])
    assert convert_main_series_stats(main) == gm.get_species(species_id).base_stats


# 正作种族值（HP, 攻击, 防御, 特攻, 特防, 速度）。这是 gamemaster 里全部有正作数据的 Mega。
# 注释里是只套公式时 15/15/15、40 级的 CP，用来看削弱门槛在哪。
MEGA_CASES = {
    # 不削弱
    "sableye_mega": (50, 85, 125, 85, 115, 20),  # 1942
    "mawile_mega": (50, 105, 125, 55, 95, 50),  # 2380
    "medicham_mega": (60, 100, 85, 80, 85, 100),  # 2495
    "audino_mega": (103, 60, 126, 80, 126, 50),  # 2524
    "altaria_mega": (75, 110, 110, 110, 105, 80),  # 3163
    "camerupt_mega": (70, 120, 100, 145, 105, 20),  # 3220
    "glalie_mega": (80, 120, 80, 120, 80, 100),  # 3229
    "sharpedo_mega": (70, 140, 70, 110, 65, 105),  # 3273
    "absol_mega": (65, 150, 60, 115, 60, 115),  # 3301
    "beedrill_mega": (65, 150, 40, 15, 80, 145),  # 3383
    "abomasnow_mega": (90, 132, 105, 132, 105, 30),  # 3405
    "manectric_mega": (70, 75, 80, 135, 80, 135),  # 3580
    "banette_mega": (64, 165, 75, 93, 83, 75),  # 3594
    "steelix_mega": (75, 125, 230, 55, 95, 30),  # 3670
    "pidgeot_mega": (83, 80, 80, 135, 80, 121),  # 3680
    "venusaur_mega": (80, 100, 123, 122, 120, 80),  # 3698
    "lopunny_mega": (65, 136, 94, 54, 96, 135),  # 3745
    "slowbro_mega": (95, 75, 180, 130, 80, 30),  # 3755
    "lucario_mega": (70, 145, 88, 140, 70, 112),  # 3826
    "houndoom_mega": (75, 90, 90, 140, 90, 115),  # 3842
    "charizard_mega_x": (78, 130, 111, 130, 85, 100),  # 3850
    "kangaskhan_mega": (105, 125, 100, 60, 100, 100),  # 3850
    "blastoise_mega": (79, 103, 120, 135, 115, 78),  # 3941
    "sceptile_mega": (70, 110, 75, 145, 85, 145),  # 4056
    "scizor_mega": (70, 150, 140, 65, 100, 75),  # 4087
    "aerodactyl_mega": (80, 135, 85, 70, 95, 150),  # 4118
    "blaziken_mega": (80, 160, 80, 130, 80, 100),  # 4161
    "aggron_mega": (70, 140, 230, 60, 80, 50),  # 4162
    "pinsir_mega": (65, 155, 120, 65, 90, 105),  # 4182
    "ampharos_mega": (90, 95, 105, 165, 110, 45),  # 4245
    "gengar_mega": (60, 65, 80, 170, 95, 130),  # 4336
    "diancie_mega": (50, 160, 110, 160, 110, 110),  # 4346
    "swampert_mega": (100, 150, 110, 95, 110, 70),  # 4401
    "charizard_mega_y": (78, 104, 78, 159, 115, 100),  # 4455
    "alakazam_mega": (55, 50, 65, 175, 105, 150),  # 4510
    "gardevoir_mega": (68, 85, 65, 165, 135, 100),  # 4512
    "gallade_mega": (68, 165, 95, 65, 115, 110),  # 4521
    "gyarados_mega": (95, 155, 109, 70, 130, 81),  # 4717
    "latias_mega": (80, 100, 120, 140, 150, 110),  # 4801
    "heracross_mega": (80, 185, 115, 40, 105, 75),  # 4814
    "metagross_mega": (80, 145, 150, 105, 110, 110),  # 4911
    "latios_mega": (80, 130, 100, 160, 120, 110),  # 5007
    "salamence_mega": (95, 145, 130, 120, 90, 120),  # 5031
    "tyranitar_mega": (100, 164, 150, 95, 120, 71),  # 5347
    "garchomp_mega": (108, 170, 115, 120, 95, 92),  # 5424  ← 不削弱的最高者
    # 乘 0.97
    "rayquaza_mega": (105, 180, 100, 180, 100, 115),  # 6039  ← 削弱的最低者
    "groudon_primal": (100, 180, 160, 150, 90, 90),  # 6255
    "kyogre_primal": (100, 150, 90, 180, 160, 90),  # 6255
    "mewtwo_mega_x": (106, 190, 100, 154, 100, 130),  # 6491
    "mewtwo_mega_y": (106, 150, 70, 194, 120, 140),  # 6802
}


@pytest.mark.parametrize("species_id", MEGA_CASES)
def test_mega_matches_gamemaster(gm: GameMaster, species_id: str) -> None:
    main = MainSeriesStats(*MEGA_CASES[species_id])
    assert (
        convert_main_series_stats(main, is_mega=True)
        == gm.get_species(species_id).base_stats
    )
