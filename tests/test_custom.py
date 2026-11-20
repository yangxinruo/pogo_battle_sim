"""自定义覆盖文件（custom.py）的测试。"""

import re
from pathlib import Path

import pytest

from pogo_sim.combatant import PokemonBuild, make_combatant
from pogo_sim.conversion import MEGA_NERF, NerfRule
from pogo_sim.custom import CUSTOM_DATA_DIR, CustomDataError
from pogo_sim.gamemaster import GameMaster, StatChange, load_gamemaster
from pogo_sim.stats import BaseStats, IVs

MEGA_FROSLASS_FILE = CUSTOM_DATA_DIR / "mega_froslass.toml"
MOONBLAST_PLUS_FILE = CUSTOM_DATA_DIR / "moonblast_plus_mega_flag.toml"


def write_toml(tmp_path: Path, text: str, name: str = "custom.toml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# 一只最简单的新宝可梦，错误用例在它的基础上改一处。
MINIMAL_POKEMON = """
[new_pokemon.test_mon]
speciesName = "Test Mon"
dex = 9999
types = ["normal"]
baseStats = { atk = 150, def = 150, hp = 150 }
fastMoves = ["TACKLE"]
chargedMoves = ["BODY_SLAM"]
"""


# ---- 示例文件 ----


@pytest.fixture(scope="module")
def gm_custom() -> GameMaster:
    return load_gamemaster(custom_files=[MEGA_FROSLASS_FILE, MOONBLAST_PLUS_FILE])


def test_without_custom_files_nothing_changes() -> None:
    gm = load_gamemaster()
    assert gm.custom_log == ()
    assert "froslass_mega" not in gm.species
    assert not gm.get_move("MOONBLAST_PLUS").is_mega_move


def test_mega_froslass_from_main_series_stats(gm_custom: GameMaster) -> None:
    """只给正作能力值（70/80/70/140/100/120），换算出 GO 种族值。"""
    mega = gm_custom.get_species("froslass_mega")
    assert mega.base_stats == BaseStats(atk=289, def_=194, hp=172)
    assert mega.name == "Froslass (Mega)"
    assert mega.types == ("ice", "ghost")
    assert mega.is_mega
    assert "supermega" in mega.tags
    assert not mega.released
    assert mega.fast_move_ids == ("HEX", "POWDER_SNOW")
    assert mega.extra_charged_move_ids == ("AVALANCHE_PLUS",)
    assert mega.default_spreads == {}


def test_new_move_from_example(gm_custom: GameMaster) -> None:
    move = gm_custom.get_move("AVALANCHE_PLUS")
    assert move.name == "Avalanche+"
    assert move.type == "ice"
    assert move.power == 75
    assert move.energy_cost == 35
    assert not move.is_fast
    assert move.is_mega_move
    assert move.effect is None


def test_patch_only_changes_given_fields(gm_custom: GameMaster) -> None:
    """Moonblast+ 只补 isMegaMove，其他字段（威力、能量、10% 降攻）不变。"""
    original = load_gamemaster().get_move("MOONBLAST_PLUS")
    patched = gm_custom.get_move("MOONBLAST_PLUS")
    assert patched.is_mega_move
    assert patched.power == original.power == 80
    assert patched.energy_cost == original.energy_cost == 50
    assert patched.effect == original.effect
    assert patched.effect is not None
    assert patched.effect.on_opponent == StatChange(atk=-1, def_=0)


def test_custom_log_explains_every_change(gm_custom: GameMaster) -> None:
    assert gm_custom.custom_log == (
        "mega_froslass.toml：新招式 AVALANCHE_PLUS（name \"Avalanche+\"，type \"ice\"，power 75，"
        "energy 35，energyGain 0，turns 1，isMegaMove true）",
        "mega_froslass.toml：新宝可梦 froslass_mega（Froslass (Mega)）：种族值 289/194/172"
        "（由正作 70/80/70/140/100/120 换算，Mega 规则：只套公式 289/194/172，"
        "40 级满 IV CP 3753 < 6000，不削弱）",
        "moonblast_plus_mega_flag.toml：修改招式 MOONBLAST_PLUS：isMegaMove （无） → true",
    )


def test_custom_mega_can_battle_with_third_move(gm_custom: GameMaster) -> None:
    """自定义的 Mega 能建成 Combatant：带第三个大招，supermega 默认 Mega 等级 4。"""
    build = PokemonBuild(
        "froslass_mega",
        14.5,
        IVs(4, 15, 15),
        "POWDER_SNOW",
        ("AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"),
    )
    combatant = make_combatant(gm_custom, build, 0, shields=2)
    assert combatant.mega_level == 4
    assert combatant.cp == 1498
    assert [m.move_id for m in combatant.charged_moves] == ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"]


# ---- 用正作能力值定义已有的 Mega，结果应与 gamemaster 一致 ----


@pytest.mark.parametrize(
    ("species_id", "main_stats", "tags", "expected_note"),
    [
        # Mega 超梦X：Mega 规则，CP 6491 ≥ 6000，乘 0.97
        (
            "mewtwo_mega_x",
            (106, 190, 100, 154, 100, 130),
            '["mega", "supermega"]',
            "Mega 规则：只套公式 412/222/235，40 级满 IV CP 6491 ≥ 6000，乘 0.97",
        ),
        # Mega 路卡利欧：Mega 规则，不削弱
        (
            "lucario_mega",
            (70, 145, 88, 140, 70, 112),
            '["mega"]',
            "Mega 规则：只套公式 310/175/172，40 级满 IV CP 3826 < 6000，不削弱",
        ),
        # 请假王：非 Mega，CP 5308 ≥ 4000，乘 0.91（防御 166 能区分倍率乘在取整前还是取整后）
        (
            "slaking",
            (150, 160, 100, 95, 65, 100),
            "[]",
            "非 Mega 规则：只套公式 319/183/312，40 级满 IV CP 5308 ≥ 4000，乘 0.91",
        ),
    ],
)
def test_main_series_stats_match_gamemaster(
    tmp_path: Path,
    species_id: str,
    main_stats: tuple[int, ...],
    tags: str,
    expected_note: str,
) -> None:
    hp, attack, defense, sp_attack, sp_defense, speed = main_stats
    path = write_toml(
        tmp_path,
        f"""
[new_pokemon.{species_id}_copy]
speciesName = "Copy"
dex = 1
types = ["normal"]
mainSeriesStats = {{ hp = {hp}, attack = {attack}, defense = {defense}, spAttack = {sp_attack}, spDefense = {sp_defense}, speed = {speed} }}
fastMoves = ["TACKLE"]
chargedMoves = ["BODY_SLAM"]
tags = {tags}
""",
    )
    gm = load_gamemaster(custom_files=[path])
    copy = gm.get_species(f"{species_id}_copy")
    assert copy.base_stats == gm.get_species(species_id).base_stats
    assert expected_note in gm.custom_log[0]


def test_nerf_rule_can_be_changed_at_load_time(tmp_path: Path) -> None:
    """把 Mega 削弱门槛提到 7000：Mega 超梦X 只套公式，不再乘 0.97。"""
    path = write_toml(
        tmp_path,
        """
[new_pokemon.mewtwo_mega_x_copy]
speciesName = "Copy"
dex = 150
types = ["psychic", "fighting"]
mainSeriesStats = { hp = 106, attack = 190, defense = 100, spAttack = 154, spDefense = 100, speed = 130 }
fastMoves = ["CONFUSION"]
chargedMoves = ["PSYSTRIKE"]
tags = ["mega"]
""",
    )
    lenient = NerfRule(cp_threshold=7000, multiplier=MEGA_NERF.multiplier)
    gm = load_gamemaster(custom_files=[path], mega_nerf=lenient)
    assert gm.get_species("mewtwo_mega_x_copy").base_stats == BaseStats(atk=412, def_=222, hp=235)
    assert "CP 6491 < 7000，不削弱" in gm.custom_log[0]


def test_new_pokemon_with_go_base_stats(tmp_path: Path) -> None:
    gm = load_gamemaster(custom_files=[write_toml(tmp_path, MINIMAL_POKEMON)])
    mon = gm.get_species("test_mon")
    assert mon.base_stats == BaseStats(atk=150, def_=150, hp=150)
    assert mon.types == ("normal",)
    assert not mon.is_mega
    assert not mon.released  # 不写 released 时默认未发布
    assert gm.custom_log == ("custom.toml：新宝可梦 test_mon（Test Mon）：种族值 150/150/150",)


def test_patch_pokemon_with_main_series_stats(tmp_path: Path) -> None:
    """改已有宝可梦的种族值：给正作能力值，换算后替换 baseStats；其他字段照列新旧值。"""
    path = write_toml(
        tmp_path,
        """
[patch_pokemon.lucario_mega]
mainSeriesStats = { hp = 70, attack = 155, defense = 88, spAttack = 140, spDefense = 70, speed = 112 }
released = false
""",
    )
    gm = load_gamemaster(custom_files=[path])
    lucario = gm.get_species("lucario_mega")
    assert lucario.base_stats != BaseStats(atk=310, def_=175, hp=172)
    assert lucario.types == ("fighting", "steel")  # 没写的字段不变
    assert not lucario.released
    assert gm.custom_log[0].startswith(
        "custom.toml：修改宝可梦 lucario_mega：种族值 310/175/172 → "
    )
    assert gm.custom_log[0].endswith("；released true → false")


def test_later_file_can_patch_entry_from_earlier_file(tmp_path: Path) -> None:
    first = write_toml(tmp_path, MINIMAL_POKEMON, "first.toml")
    second = write_toml(
        tmp_path,
        """
[patch_pokemon.test_mon]
types = ["normal", "fairy"]
""",
        "second.toml",
    )
    gm = load_gamemaster(custom_files=[first, second])
    assert gm.get_species("test_mon").types == ("normal", "fairy")
    assert gm.custom_log[1] == 'second.toml：修改宝可梦 test_mon：types ["normal"] → ["normal", "fairy"]'


def test_pokemon_can_use_move_from_same_file(tmp_path: Path) -> None:
    """表的应用顺序是先招式后宝可梦，所以同一个文件里新加的招式可以直接用。"""
    path = write_toml(
        tmp_path,
        MINIMAL_POKEMON.replace('chargedMoves = ["BODY_SLAM"]', 'chargedMoves = ["NEW_BEAM"]')
        + """
[new_moves.NEW_BEAM]
name = "New Beam"
type = "normal"
power = 100
energy = 50
energyGain = 0
turns = 1
""",
    )
    gm = load_gamemaster(custom_files=[path])
    assert gm.get_species("test_mon").charged_move_ids == ("NEW_BEAM",)
    assert gm.custom_log[0].startswith("custom.toml：新招式 NEW_BEAM")


# ---- 写错时报错 ----

BAD_FILES = {
    "new 的 ID 已存在": (
        MINIMAL_POKEMON.replace("test_mon", "azumarill"),
        "宝可梦 azumarill 已经存在；要修改已有宝可梦请用 patch_pokemon",
    ),
    "patch 的 ID 不存在": (
        "[patch_pokemon.azumarrill]\nreleased = false\n",
        "宝可梦 azumarrill 不存在",
    ),
    "新招式 ID 已存在": (
        '[new_moves.COUNTER]\nname = "x"\ntype = "normal"\npower = 1\nenergy = 0\nenergyGain = 1\nturns = 1\n',
        "招式 COUNTER 已经存在",
    ),
    "修改不存在的招式": ("[patch_moves.MOONBLAST_PLUSS]\nisMegaMove = true\n", "招式 MOONBLAST_PLUSS 不存在"),
    "两种种族值都写": (
        MINIMAL_POKEMON.replace(
            "baseStats",
            "mainSeriesStats = { hp = 1, attack = 1, defense = 1, spAttack = 1, spDefense = 1, speed = 1 }\nbaseStats",
        ),
        "必须写一个，也只能写一个",
    ),
    "种族值都没写": (
        MINIMAL_POKEMON.replace("baseStats = { atk = 150, def = 150, hp = 150 }\n", ""),
        "必须写一个，也只能写一个",
    ),
    "正作能力值缺一项": (
        MINIMAL_POKEMON.replace(
            "baseStats = { atk = 150, def = 150, hp = 150 }",
            "mainSeriesStats = { hp = 1, attack = 1, defense = 1, spAttack = 1, spDefense = 1 }",
        ),
        "mainSeriesStats 要写全六项",
    ),
    "GO 种族值缺一项": (
        MINIMAL_POKEMON.replace("{ atk = 150, def = 150, hp = 150 }", "{ atk = 150, def = 150 }"),
        "baseStats 要写全",
    ),
    "字段名拼错": (MINIMAL_POKEMON.replace("chargedMoves", "chargedMove"), "不认识的字段 ['chargedMove']"),
    "表名拼错": (MINIMAL_POKEMON.replace("new_pokemon", "new_pokemons"), "不认识的表 ['new_pokemons']"),
    "属性拼错": (MINIMAL_POKEMON.replace('["normal"]', '["normel"]'), "不认识的属性 'normel'"),
    "缺必填字段": (MINIMAL_POKEMON.replace("dex = 9999\n", ""), "缺少字段 ['dex']"),
    "speciesId 与表名不一致": (
        MINIMAL_POKEMON.replace("dex = 9999", 'dex = 9999\nspeciesId = "other_mon"'),
        "和表名里的 ID 'test_mon' 不一致",
    ),
    "引用不存在的招式": (
        MINIMAL_POKEMON.replace('["BODY_SLAM"]', '["BODY_SLAMM"]'),
        "test_mon 引用了不存在的招式 BODY_SLAMM",
    ),
    "大招列表里写了快招": (
        MINIMAL_POKEMON.replace('["BODY_SLAM"]', '["TACKLE"]'),
        "test_mon 的大招列表里 TACKLE 是快速技能",
    ),
    "快招列表里写了大招": (
        MINIMAL_POKEMON.replace('fastMoves = ["TACKLE"]', 'fastMoves = ["BODY_SLAM"]'),
        "test_mon 的 fastMoves 里 BODY_SLAM 不是快速技能",
    ),
    "招式数值写成字符串": (
        '[patch_moves.COUNTER]\npower = "8"\n',
        "power 要写非负数",
    ),
}


@pytest.mark.parametrize("case", BAD_FILES)
def test_bad_custom_file_raises(tmp_path: Path, case: str) -> None:
    text, message = BAD_FILES[case]
    path = write_toml(tmp_path, text)
    with pytest.raises(CustomDataError, match=re.escape(message)):
        load_gamemaster(custom_files=[path])



def test_mega_zygarde_file() -> None:
    """Mega 基格尔德：40 级满 IV CP 8052 超过门槛，按 0.97 削弱；专属招式能当第三个大招。"""
    gm = load_gamemaster(custom_files=[CUSTOM_DATA_DIR / "mega_zygarde.toml"])
    zygarde = gm.get_species("zygarde_mega")
    assert zygarde.base_stats == BaseStats(atk=403, def_=181, hp=415)
    assert gm.custom_log[1] == (
        "mega_zygarde.toml：新宝可梦 zygarde_mega（Zygarde (Mega)）：种族值 403/181/415"
        "（由正作 216/70/91/216/85/100 换算，Mega 规则：只套公式 416/187/428，"
        "40 级满 IV CP 8052 ≥ 6000，乘 0.97）"
    )
    assert zygarde.extra_charged_move_ids == ("NIHIL_LIGHT",)
    assert gm.get_move("NIHIL_LIGHT").is_mega_move

    build = PokemonBuild("zygarde_mega", 50, IVs(15, 15, 15), "DRAGON_TAIL", ("CRUNCH", "BULLDOZE", "NIHIL_LIGHT"))
    combatant = make_combatant(gm, build, 0, shields=2)
    assert combatant.cp == 8568
    assert combatant.mega_level == 4
