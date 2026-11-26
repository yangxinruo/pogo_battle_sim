"""队伍库（pogo_sim/team_library.py，4f）：文件名、文件格式的检查、读整个库、存进去、用到的覆盖文件。"""

import tomllib

import pytest

from pogo_sim.config import REPO_ROOT, ConfigError, Entry
from pogo_sim.custom import touched_ids
from pogo_sim.moveset import Moveset
from pogo_sim.team_library import (
    LibraryTeam,
    custom_files_used,
    file_name,
    library_text,
    load_library,
    parse_library_team,
    save_team,
)

CUSTOM = REPO_ROOT / "data" / "custom"
TEAM = {
    "name": "Team A",
    "shields": 2,
    "policy": {"switching": "never"},
    "member": [
        {"species": "azumarill", "fast": "BUBBLE", "charged": ["ICE_BEAM", "PLAY_ROUGH"]},
        {"species": "medicham", "fast": "COUNTER", "charged": ["ICE_PUNCH", "PSYCHIC"], "ivs": [0, 15, 15]},
        {"species": "froslass_mega", "fast": "POWDER_SNOW", "charged": ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"]},
    ],
}


def entry(**changes) -> LibraryTeam:
    fields = {"file": "Team_A.toml", "league": 1500, "custom_files": ("mega_froslass.toml",), "note": "说明", "team": TEAM}
    return LibraryTeam(**(fields | changes))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Team A", "Team_A.toml"),
        ("Team A (Mega Froslass)", "Team_A_Mega_Froslass.toml"),
        ("  超级联盟 / 雪妖女  ", "超级联盟_雪妖女.toml"),
        ('a:b*c?"d<e>f|g\\h', "a_b_c_d_e_f_g_h.toml"),
        ("A&B; $x 'y'", "A_B_x_y.toml"),
        ("Mega-Froslass v1.2", "Mega-Froslass_v1.2.toml"),
        ("..hidden", "hidden.toml"),
    ],
)
def test_file_name(name, expected):
    assert file_name(name) == expected


def test_file_name_cannot_be_empty():
    with pytest.raises(ConfigError, match="变成文件名以后是空的"):
        file_name(" / ")


def test_text_roundtrip():
    """写出来的文件读回来是同一队；[team] 改成 [[team]] 就是 3v3 配置里的一队。"""
    text = library_text(entry())
    assert text.startswith("# 队伍库的一队")
    assert parse_library_team(tomllib.loads(text), "Team_A.toml") == entry()
    assert "\n[team]\nname = \"Team A\"\nshields = 2\n\n[team.policy]\nswitching = \"never\"\n\n[[team.member]]\n" in text
    plain = library_text(entry(custom_files=(), note=""))
    assert "custom_files" not in plain and "note" not in plain


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"league": "1500"}, "league 要写正整数"),
        ({"custom_files": ["data/custom/x.toml"]}, "custom_files 要写 data/custom/ 里的文件名列表"),
        ({"note": 3}, "note 要写字符串"),
        ({"extra": 1}, "不认识的字段 extra"),
        ({"team": {**TEAM, "member": TEAM["member"][:2]}}, "每队要正好 3 只"),
        ({"team": {**TEAM, "policy": {"nope": 1}}}, "nope"),
    ],
)
def test_parse_errors(change, message):
    raw = {"league": 1500, "team": TEAM} | change
    with pytest.raises(ConfigError, match=message):
        parse_library_team(raw, "x.toml")
    with pytest.raises(ConfigError, match="缺少 league"):
        parse_library_team({"team": TEAM}, "x.toml")


def test_save_and_load(tmp_path):
    assert save_team(entry(), tmp_path)
    assert (tmp_path / "Team_A.toml").read_text(encoding="utf-8") == library_text(entry())
    # 已经有了：不让覆盖时不写
    assert not save_team(entry(note="新的"), tmp_path)
    assert load_library(tmp_path).teams == (entry(),)
    assert save_team(entry(note="新的"), tmp_path, overwrite=True)
    assert load_library(tmp_path).teams == (entry(note="新的"),)
    assert [p.name for p in tmp_path.iterdir()] == ["Team_A.toml"]  # 没有留下临时文件


def test_load_library_lists_broken_files(tmp_path):
    save_team(entry(), tmp_path)
    save_team(entry(file="B.toml", team={**TEAM, "name": "B"}), tmp_path)
    (tmp_path / "bad.toml").write_text("league = [", encoding="utf-8")
    (tmp_path / "wrong.toml").write_text("league = 1500\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("不是队伍", encoding="utf-8")
    library = load_library(tmp_path)
    assert [t.file for t in library.teams] == ["B.toml", "Team_A.toml"]
    assert [b.file for b in library.broken] == ["bad.toml", "wrong.toml"]
    assert "不是合法的 TOML" in library.broken[0].error
    assert library.broken[1].error == "teams/wrong.toml：缺少 team"
    assert load_library(tmp_path / "nothing").teams == ()


def test_touched_ids():
    species, moves = touched_ids(CUSTOM / "mega_froslass.toml")
    assert "froslass_mega" in species and "AVALANCHE_PLUS" in moves
    species, moves = touched_ids(CUSTOM / "moonblast_plus_mega_flag.toml")
    assert (species, moves) == (set(), {"MOONBLAST_PLUS"})


def test_custom_files_used():
    """用到 = 宝可梦或招式被这个覆盖文件新加或修改过。"""
    paths = sorted(CUSTOM.glob("*.toml"))
    members = [
        Entry(None, "azumarill", Moveset("BUBBLE", ("ICE_BEAM",))),
        Entry(None, "froslass_mega", Moveset("POWDER_SNOW", ("AVALANCHE_PLUS",))),
    ]
    assert custom_files_used(paths, members) == ("mega_froslass.toml",)
    clefable = [Entry(None, "clefable_mega", Moveset("FAIRY_WIND", ("MOONBLAST_PLUS",)))]
    assert custom_files_used(paths, clefable) == ("moonblast_plus_mega_flag.toml",)
    assert custom_files_used(paths, members[:1]) == ()
