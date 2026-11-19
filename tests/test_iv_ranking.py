"""IV 排名（pogo_sim/iv_ranking.py）：与 PvPoke 的排名逐个核对，再加几个手算的用例。"""

import random

import pytest

from pogo_sim.cpm import LEVEL_STEP
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.iv_ranking import (
    find_rank,
    pvpoke_iv_floor,
    pvpoke_level_floor,
    rank_ivs,
    rank_species_ivs,
)
from pogo_sim.stats import IVs, calculate_cp, highest_level_under_cp
from tests.pvpoke_reference import decode_iv_levels, decode_iv_order, load_iv_reference

FROSLASS_MEGA_FILE = "data/custom/mega_froslass.toml"
IV_CASES = load_iv_reference()["cases"]


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster(custom_files=[FROSLASS_MEGA_FILE])


@pytest.mark.parametrize(
    "case", IV_CASES, ids=[f"{c['species']}-{c['cp']}-L{c['pvpoke_level_cap']}" for c in IV_CASES]
)
def test_ranking_matches_pvpoke(gm: GameMaster, case: dict) -> None:
    """完整的名次顺序、每个组合的等级、前 20 名的 CP 和实际能力值都与 PvPoke 相同（浮点逐位相等）。

    等级上限直接用 PvPoke 里宝可梦的上限（supermega 是 52）；
    什么情况下用什么上限是赛季规则的事，在 season.py 里处理。
    """
    species = gm.get_species(case["species"])
    ranking = rank_species_ivs(species, case["cp"], level_cap=case["pvpoke_level_cap"])

    assert len(ranking) == case["count"]
    assert [(e.ivs.atk, e.ivs.def_, e.ivs.hp) for e in ranking] == decode_iv_order(case["order"])
    assert [e.level for e in ranking] == decode_iv_levels(case["levels"])

    for entry, expected in zip(ranking, case["top"]):
        assert [entry.ivs.atk, entry.ivs.def_, entry.ivs.hp] == expected["ivs"]
        assert entry.cp == expected["cp"]
        assert entry.stats.atk == expected["atk"]
        assert entry.stats.def_ == expected["def"]
        assert entry.stats.hp == expected["hp"]
        assert entry.stat_product == expected["overall"]


def test_pvpoke_floors(gm: GameMaster) -> None:
    """IV 下限和最低等级的默认值（PvPoke 按标签和 levelFloor 决定）。"""
    expected_iv_floor = {
        "azumarill": 0,
        "swampert_shadow": 0,
        "registeel": 1,
        "nihilego": 1,  # 究极异兽
        "latias": 0,  # 野外出现的传说
        "registeel_shadow": 6,
        "jirachi": 10,  # 不能交换
        "mewtwo_mega_x": 1,  # Mega 也看标签：它有 legendary
        "froslass_mega": 0,
    }
    for species_id, floor in expected_iv_floor.items():
        assert pvpoke_iv_floor(gm.get_species(species_id)) == floor, species_id

    mewtwo_x = gm.get_species("mewtwo_mega_x")
    snom = gm.get_species("snom")
    assert mewtwo_x.level_floor == 15.0
    assert gm.get_species("azumarill").level_floor == 1.0
    assert pvpoke_level_floor(mewtwo_x, 2500) == 15.0
    assert pvpoke_level_floor(snom, 1500) == 20.0
    assert pvpoke_level_floor(snom, 500) == 1.0  # 小小杯忽略 levelFloor


def test_mega_froslass_great_league(gm: GameMaster) -> None:
    """覆盖文件里的 Mega 雪妖女（GO 种族值 289/194/172）在超级联盟的排名。"""
    ranking = rank_species_ivs(gm.get_species("froslass_mega"), 1500)
    assert len(ranking) == 4096

    best = ranking[0]
    assert (best.ivs, best.level, best.cp) == (IVs(4, 15, 15), 14.5, 1498)
    assert best.percent_of_best == 100
    assert best.describe() == "IV 4/15/15，14.5 级，CP 1498，第 1 名（100.00%）"

    perfect = find_rank(ranking, IVs(15, 15, 15))
    assert perfect is not None
    assert (perfect.rank, perfect.level, perfect.cp) == (3696, 13.5, 1448)
    assert perfect.describe() == "IV 15/15/15，13.5 级，CP 1448，第 3696 名（92.53%）"


def test_ranks_and_percentages_are_consistent(gm: GameMaster) -> None:
    ranking = rank_species_ivs(gm.get_species("azumarill"), 1500)
    assert [e.rank for e in ranking] == list(range(1, len(ranking) + 1))
    products = [e.stat_product for e in ranking]
    assert products == sorted(products, reverse=True)
    assert all(0 < e.percent_of_best <= 100 for e in ranking)
    assert all(e.cp <= 1500 for e in ranking)


def test_iv_floor_excludes_low_ivs(gm: GameMaster) -> None:
    ranking = rank_species_ivs(gm.get_species("registeel"), 1500)
    assert len(ranking) == 15**3
    assert find_rank(ranking, IVs(0, 15, 15)) is None  # 攻击 IV 0 低于传说的下限 1
    # 手动指定下限会覆盖 PvPoke 的默认值
    assert len(rank_species_ivs(gm.get_species("registeel"), 1500, iv_floor=0)) == 16**3


def test_level_floor_can_empty_the_ranking(gm: GameMaster) -> None:
    """Mega 超梦X 最低 15 级，15 级时任何 IV 都超过 1500。"""
    mewtwo_x = gm.get_species("mewtwo_mega_x")
    assert rank_species_ivs(mewtwo_x, 1500) == []
    # 不考虑最低等级时就有合法组合（它是传说，IV 下限 1，共 15³ 个）
    assert len(rank_species_ivs(mewtwo_x, 1500, level_floor=1.0)) == 15**3


def test_uncapped_league_puts_everything_at_level_cap(gm: GameMaster) -> None:
    ranking = rank_species_ivs(gm.get_species("dialga"), 10000, level_cap=51)
    assert {e.level for e in ranking} == {51.0}
    assert ranking[0].ivs == IVs(15, 15, 15)


def test_invalid_iv_floor(gm: GameMaster) -> None:
    base = gm.get_species("azumarill").base_stats
    with pytest.raises(ValueError, match="IV 下限 16 超出范围"):
        rank_ivs(base, 1500, iv_floor=16)


def _highest_level_linear(base, ivs, cp_limit, level_cap, level_floor):
    """逐级往上找的写法，用来核对二分查找。"""
    best = None
    level = level_floor
    while level <= level_cap:
        if calculate_cp(base, ivs, level) > cp_limit:
            break
        best = level
        level += LEVEL_STEP
    return best


def test_binary_search_matches_linear_scan(gm: GameMaster) -> None:
    """highest_level_under_cp 用二分查找；随机抽 2000 个情况和逐级查找对比。"""
    rng = random.Random(20261118)
    species = list(gm.species.values())
    for _ in range(2000):
        base = rng.choice(species).base_stats
        ivs = IVs(rng.randint(0, 15), rng.randint(0, 15), rng.randint(0, 15))
        cp_limit = rng.choice([500, 1500, 2500, 10000, rng.randint(10, 4000)])
        level_floor = rng.choice([1.0, 1.5, 15.0, 20.0])
        level_cap = rng.choice([level_floor, 40.0, 50.0, 51.0, 52.0, 55.0])
        assert highest_level_under_cp(
            base, ivs, cp_limit, level_cap, level_floor
        ) == _highest_level_linear(base, ivs, cp_limit, level_cap, level_floor)


def test_highest_level_rejects_bad_ranges(gm: GameMaster) -> None:
    base = gm.get_species("azumarill").base_stats
    with pytest.raises(ValueError, match="高于等级上限"):
        highest_level_under_cp(base, IVs(0, 0, 0), 1500, level_cap=20, level_floor=25)
    with pytest.raises(ValueError, match="不合法的等级范围"):
        highest_level_under_cp(base, IVs(0, 0, 0), 1500, level_cap=50.25)
