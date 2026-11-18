"""CP、HP、实际攻防的测试。"""

import pytest

from pogo_sim.cpm import CPM_TABLE, get_cpm
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.stats import (
    BaseStats,
    IVs,
    calculate_battle_stats,
    calculate_cp,
    highest_level_under_cp,
)


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def test_cpm_table() -> None:
    assert len(CPM_TABLE) == 109  # 1 到 55 级，步长 0.5
    assert get_cpm(1) == pytest.approx(0.094)
    assert get_cpm(40) == pytest.approx(0.7903)
    assert get_cpm(50) == pytest.approx(0.8403)
    # CPM 随等级严格递增
    assert all(a < b for a, b in zip(CPM_TABLE, CPM_TABLE[1:]))


@pytest.mark.parametrize("level", [0.5, 55.5, 40.25])
def test_invalid_level_rejected(level: float) -> None:
    with pytest.raises(ValueError):
        get_cpm(level)


def test_invalid_iv_rejected() -> None:
    with pytest.raises(ValueError):
        IVs(atk=16, def_=0, hp=0)


# 游戏内广为人知的 15/15/15 CP 值，独立于 PvPoke，用来验证 CP 公式和 CPM 表。
KNOWN_MAX_IV_CP = [
    ("mewtwo", 20, 2387),  # 团体战捕获的满 IV 超梦
    ("mewtwo", 40, 4178),
    ("mewtwo", 50, 4724),
    ("dialga", 40, 4038),
    ("azumarill", 40, 1588),
    ("azumarill", 50, 1795),
    ("registeel", 40, 2447),
    ("swampert", 40, 2974),
    ("giratina_altered", 40, 3379),
]


@pytest.mark.parametrize("species_id, level, expected_cp", KNOWN_MAX_IV_CP)
def test_known_cp_values(
    gm: GameMaster, species_id: str, level: float, expected_cp: int
) -> None:
    species = gm.get_species(species_id)
    assert calculate_cp(species.base_stats, IVs(15, 15, 15), level) == expected_cp


def test_cp_minimum_is_10() -> None:
    weak = BaseStats(atk=29, def_=85, hp=85)  # 鲤鱼王
    assert calculate_cp(weak, IVs(0, 0, 0), 1) == 10


# PvPoke 在各联盟默认使用的等级和 IV（来自 gamemaster 的 defaultIVs），
# 以及用我们的公式算出的 CP 和 HP。CP 应该贴着上限但不超过。
# 这些数值在生成时已人工核对过，保留作为回归测试。
PVPOKE_DEFAULT_SPREADS = [
    # (species_id, CP 上限, 等级, (攻, 防, HP IV), CP, HP)
    ("azumarill", 1500, 43.0, (4, 15, 13), 1499, 191),
    ("medicham", 1500, 49.0, (7, 15, 14), 1500, 141),
    ("registeel", 1500, 22.5, (8, 15, 14), 1499, 129),
    ("registeel", 2500, 49.0, (4, 6, 14), 2498, 170),
    ("sableye_mega", 1500, 29.0, (4, 13, 15), 1496, 109),
    ("mewtwo_mega_x", 1500, 9.0, (5, 13, 8), 1496, 94),
]


@pytest.mark.parametrize(
    "species_id, cp_limit, level, ivs, expected_cp, expected_hp", PVPOKE_DEFAULT_SPREADS
)
def test_pvpoke_default_spreads(
    gm: GameMaster,
    species_id: str,
    cp_limit: int,
    level: float,
    ivs: tuple[int, int, int],
    expected_cp: int,
    expected_hp: int,
) -> None:
    species = gm.get_species(species_id)
    spread = species.default_spreads[cp_limit]

    # gamemaster 里的预设和我们记录的一致
    assert spread.level == level
    assert spread.ivs == IVs(*ivs)

    assert calculate_cp(species.base_stats, spread.ivs, level) == expected_cp
    assert calculate_battle_stats(species.base_stats, spread.ivs, level).hp == expected_hp

    # 这个等级确实是该 IV 下不超过上限的最高等级
    assert highest_level_under_cp(species.base_stats, spread.ivs, cp_limit) == level


def test_no_default_spread_exceeds_cp_limit(gm: GameMaster) -> None:
    """全量检查：PvPoke 给每只宝可梦预设的等级和 IV，用我们的公式算都不超过联盟上限。"""
    for species in gm.species.values():
        for cp_limit, spread in species.default_spreads.items():
            cp = calculate_cp(species.base_stats, spread.ivs, spread.level)
            assert cp <= cp_limit, f"{species.species_id} 在 {cp_limit} 联盟算出 CP {cp}"


def test_battle_stats_keep_decimals_for_atk_and_def(gm: GameMaster) -> None:
    azumarill = gm.get_species("azumarill")
    stats = calculate_battle_stats(azumarill.base_stats, IVs(4, 15, 13), 43.0)
    cpm = get_cpm(43.0)
    assert stats.atk == pytest.approx(cpm * (112 + 4))
    assert stats.def_ == pytest.approx(cpm * (152 + 15))
    assert stats.hp == 191
    assert isinstance(stats.hp, int)


def test_hp_minimum_is_10() -> None:
    tiny = BaseStats(atk=1, def_=1, hp=1)
    assert calculate_battle_stats(tiny, IVs(0, 0, 0), 1).hp == 10


def test_highest_level_under_cp_edge_cases(gm: GameMaster) -> None:
    mewtwo = gm.get_species("mewtwo")
    # 1 级满 IV 超梦的 CP 是 59，上限设得比它还低时没有合法等级
    assert highest_level_under_cp(mewtwo.base_stats, IVs(15, 15, 15), 50) is None
    # 上限很高时停在等级上限
    assert highest_level_under_cp(mewtwo.base_stats, IVs(15, 15, 15), 10000) == 50.0
    assert (
        highest_level_under_cp(mewtwo.base_stats, IVs(15, 15, 15), 10000, level_cap=40)
        == 40.0
    )


def test_cpm_table_matches_pvpoke() -> None:
    """CPM 表逐位等于 PvPoke Pokemon.js 里的值（1 到 55 级）。"""
    from tests.pvpoke_reference import load_damage_reference

    reference = load_damage_reference()["cpm"]
    assert len(reference) == len(CPM_TABLE)
    for level, value in reference:
        assert get_cpm(level) == value, level
