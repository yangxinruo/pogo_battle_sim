"""gamemaster.json 读取的测试。"""

import pytest

from pogo_sim.gamemaster import GameMaster, StatChange, load_gamemaster
from pogo_sim.stats import BaseStats, IVs


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def test_counts_match_snapshot(gm: GameMaster) -> None:
    # 与 data/SOURCE.md 记录的快照一致。更新快照时这里要跟着改。
    assert len(gm.species) == 1753
    assert len(gm.moves) == 357
    assert gm.timestamp == "2026-11-17 14:44:05"


def test_species_fields(gm: GameMaster) -> None:
    azumarill = gm.get_species("azumarill")
    assert azumarill.name == "Azumarill"
    assert azumarill.base_stats == BaseStats(atk=112, def_=152, hp=225)
    assert azumarill.types == ("water", "fairy")
    assert "BUBBLE" in azumarill.fast_move_ids
    assert "PLAY_ROUGH" in azumarill.charged_move_ids
    assert azumarill.default_spreads[1500].level == 43.0
    assert azumarill.default_spreads[1500].ivs == IVs(atk=4, def_=15, hp=13)
    assert not azumarill.is_shadow
    assert not azumarill.is_mega


def test_single_type_drops_none(gm: GameMaster) -> None:
    assert gm.get_species("mewtwo").types == ("psychic",)


def test_shadow_and_mega_tags(gm: GameMaster) -> None:
    assert gm.get_species("swampert_shadow").is_shadow
    mega = gm.get_species("mewtwo_mega_x")
    assert mega.is_mega
    assert mega.extra_charged_move_ids == ("DYNAMIC_PUNCH_PLUS",)


def test_fast_move(gm: GameMaster) -> None:
    counter = gm.get_move("COUNTER")
    assert counter.is_fast
    assert counter.type == "fighting"
    assert counter.power == 8
    assert counter.energy_gain == 6
    assert counter.turns == 2
    assert counter.effect is None


def test_charged_move_with_guaranteed_debuff(gm: GameMaster) -> None:
    icy_wind = gm.get_move("ICY_WIND")
    assert not icy_wind.is_fast
    assert icy_wind.energy_cost == 45
    assert icy_wind.effect is not None
    assert icy_wind.effect.chance == 1.0
    assert icy_wind.effect.on_self is None
    assert icy_wind.effect.on_opponent == StatChange(atk=-1, def_=0)


def test_charged_move_with_chance_buff(gm: GameMaster) -> None:
    night_slash = gm.get_move("NIGHT_SLASH")
    assert night_slash.effect is not None
    assert night_slash.effect.chance == 0.125
    assert night_slash.effect.on_self == StatChange(atk=1, def_=0)
    assert night_slash.effect.on_opponent is None


def test_move_affecting_both_sides(gm: GameMaster) -> None:
    obstruct = gm.get_move("OBSTRUCT")
    assert obstruct.effect is not None
    assert obstruct.effect.on_self == StatChange(atk=0, def_=1)
    assert obstruct.effect.on_opponent == StatChange(atk=0, def_=-1)


def test_mega_move_flag(gm: GameMaster) -> None:
    assert gm.get_move("DYNAMIC_PUNCH_PLUS").is_mega_move
    assert not gm.get_move("DYNAMIC_PUNCH").is_mega_move


def test_every_referenced_move_exists(gm: GameMaster) -> None:
    for species in gm.species.values():
        move_ids = (
            species.fast_move_ids
            + species.charged_move_ids
            + species.extra_charged_move_ids
        )
        for move_id in move_ids:
            assert move_id in gm.moves, f"{species.species_id} 引用了不存在的招式 {move_id}"


# gamemaster 里"快速技能列表中出现了非快速技能"的已知例外，都是原始数据的特殊情况：
# - 百变怪的 Transform：energyGain 为 0，按 PvPoke 的规则（energyGain > 0 才算快速技能）
#   不算快速技能。写引擎时如果要支持百变怪需要单独处理。
# - 玛机雅娜（未发布）：占位数据，快速技能和大招都填的是 Struggle。
KNOWN_NON_FAST_IN_FAST_LIST = {("ditto", "TRANSFORM"), ("magearna", "STRUGGLE")}


def test_fast_and_charged_moves_are_classified(gm: GameMaster) -> None:
    non_fast_in_fast_list = set()
    for species in gm.species.values():
        for move_id in species.fast_move_ids:
            if not gm.get_move(move_id).is_fast:
                non_fast_in_fast_list.add((species.species_id, move_id))
        for move_id in species.charged_move_ids + species.extra_charged_move_ids:
            assert not gm.get_move(move_id).is_fast, move_id

    assert non_fast_in_fast_list == KNOWN_NON_FAST_IN_FAST_LIST


def test_unknown_ids_raise(gm: GameMaster) -> None:
    with pytest.raises(KeyError):
        gm.get_species("not_a_pokemon")
    with pytest.raises(KeyError):
        gm.get_move("NOT_A_MOVE")
