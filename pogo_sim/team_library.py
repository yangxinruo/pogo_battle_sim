"""队伍库（4f）：一队一个 TOML 文件，放在仓库的 teams/（入库，跟着备份到 GitHub）。

网页上可以列出库里的队伍、载入到页面上的某一队、把页面上的一队存进来；**不能删除**
（用户 2026-11-25：在想好怎么存数据之前，网页只作为一个接口；要删就手动删文件）。
同名的文件已经有了时，网页先问再覆盖（提交过的旧版本能从 git 找回）。

文件格式：
    league = 1500                          # 常用联盟：只用来在列表里筛选，载入时不强制
    custom_files = ["mega_froslass.toml"]  # 可选：这一队用到的覆盖文件（data/custom/ 里的文件名），载入时自动勾上
    note = "说明"                          # 可选

    [team]                                 # 和 3v3 配置里的一个 [[team]] 写法相同（team_battle.py 开头）：
    name = "Team A"                        #   name、可选 shields、可选 [team.policy]、[[team.member]] 正好 3 只
    shields = 2                            #   把 [team] 改成 [[team]] 就能贴进 3v3 配置
    [[team.member]]
    species = "azumarill"
    fast = "BUBBLE"
    charged = ["ICE_BEAM", "PLAY_ROUGH"]
    ...

文件名由队名得到（file_name）：字母、数字（含中文）、下划线、点、减号以外的字符都换成下划线（空格、括号在命令行里
要转义），例如 "Team A (Mega Froslass)" → Team_A_Mega_Froslass.toml。
手写的文件也可以，文件名不必和队名对应；读不了的文件在列表里单独列出原因，不影响其他队伍。
"""

import os
import re
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pogo_sim.config import REPO_ROOT, ConfigError, Entry, check_unknown_keys, load_toml
from pogo_sim.custom import CustomDataError, touched_ids
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.team_battle import parse_team
from pogo_sim.toml_writer import dumps

LIBRARY_DIR: Path = REPO_ROOT / "teams"
FILE_KEYS = frozenset({"league", "custom_files", "note", "team"})
FILE_HEADER = (
    "队伍库的一队（格式见 pogo_sim/team_library.py 开头）。",
    "[team] 和 3v3 配置里的一个 [[team]] 写法相同：把 [team] 改成 [[team]] 就能贴进 3v3 配置。",
)

# 文件名里只留字母、数字（\w 含中文）、下划线、点、减号；其余（空白、路径分隔符、括号、引号……）换成下划线
_UNSAFE = re.compile(r"[^\w.-]+")


@dataclass(frozen=True)
class LibraryTeam:
    """库里的一队。"""

    file: str  # 文件名，例如 "Team_A.toml"
    league: int  # 常用联盟（CP 上限），只用来筛选
    custom_files: tuple[str, ...]  # 用到的覆盖文件（data/custom/ 里的文件名）
    note: str
    team: dict[str, Any]  # [team] 表的原样内容（和 3v3 配置里的一个 [[team]] 相同）

    @property
    def name(self) -> str:
        return self.team["name"]


@dataclass(frozen=True)
class BrokenFile:
    """读不了的文件和原因。"""

    file: str
    error: str


@dataclass(frozen=True)
class Library:
    teams: tuple[LibraryTeam, ...]  # 按文件名
    broken: tuple[BrokenFile, ...]


def file_name(team_name: str) -> str:
    """队名对应的文件名，例如 "Team A (Mega Froslass)" → "Team_A_Mega_Froslass.toml"。"""
    stem = _UNSAFE.sub("_", team_name.strip()).strip("._")
    if not stem:
        raise ConfigError(f"队名 {team_name!r} 变成文件名以后是空的，换一个队名")
    return f"{stem}.toml"


def parse_library_team(raw: Any, file: str) -> LibraryTeam:
    """检查一个队伍文件的内容（已经读进来的 dict）。[team] 的检查和 3v3 配置相同。写错时抛出 ConfigError。

    这里只检查写法；宝可梦、招式是否存在要看载入时选了哪些覆盖文件，载入以后建配置时检查。
    """
    where = f"teams/{file}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}：要写成表（键值对），得到 {type(raw).__name__}")
    check_unknown_keys(raw, FILE_KEYS, where)
    for key in ("league", "team"):
        if key not in raw:
            raise ConfigError(f"{where}：缺少 {key}")
    league = raw["league"]
    if not isinstance(league, int) or isinstance(league, bool) or league <= 0:
        raise ConfigError(f"{where}：league 要写正整数（CP 上限），得到 {league!r}")
    custom_files = raw.get("custom_files", [])
    if not isinstance(custom_files, list) or not all(
        isinstance(name, str) and name.endswith(".toml") and "/" not in name and "\\" not in name
        for name in custom_files
    ):
        raise ConfigError(f"{where}：custom_files 要写 data/custom/ 里的文件名列表（例如 \"mega_froslass.toml\"）")
    note = raw.get("note", "")
    if not isinstance(note, str):
        raise ConfigError(f"{where}：note 要写字符串，得到 {note!r}")
    team = raw["team"]
    parse_team(team, {}, PVPOKE_COMPAT, where)
    return LibraryTeam(file, league, tuple(custom_files), note, team)


def load_library(directory: Path | None = None) -> Library:
    """读库里的全部队伍（*.toml，按文件名）。读不了的文件放进 broken，不影响其他的。"""
    directory = directory or LIBRARY_DIR
    teams = []
    broken = []
    if directory.is_dir():
        for path in sorted(directory.glob("*.toml")):
            try:
                teams.append(parse_library_team(load_toml(path), path.name))
            except ConfigError as e:
                broken.append(BrokenFile(path.name, str(e)))
    return Library(tuple(teams), tuple(broken))


def library_text(entry: LibraryTeam) -> str:
    """一队写成文件的文本。"""
    data: dict[str, Any] = {"league": entry.league}
    if entry.custom_files:
        data["custom_files"] = list(entry.custom_files)
    if entry.note:
        data["note"] = entry.note
    data["team"] = entry.team
    return dumps(data, FILE_HEADER)


def save_team(entry: LibraryTeam, directory: Path | None = None, overwrite: bool = False) -> bool:
    """存进库里。文件已经有了、又没让覆盖时不写，返回 False；写了返回 True。

    写之前核对写出来的文本能原样读回来；先写临时文件再改名，写到一半出错不会留下坏文件。
    """
    directory = directory or LIBRARY_DIR
    path = directory / entry.file
    if path.exists() and not overwrite:
        return False
    text = library_text(entry)
    if parse_library_team(tomllib.loads(text), entry.file) != entry:  # 写出去的就是要存的
        raise ValueError(f"teams/{entry.file}：写出来的文本读回来不一样")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, suffix=".tmp", delete=False) as f:
        f.write(text)
    os.replace(f.name, path)
    return True


def custom_files_used(paths: Sequence[Path], members: Sequence[Entry]) -> tuple[str, ...]:
    """这几个覆盖文件里，这一队用到了哪些（文件名，按给的顺序）。

    用到 = 某一只的宝可梦被这个文件新加或修改过，或者某个招式被这个文件新加或修改过（custom.touched_ids）。
    """
    species = {m.species_id for m in members}
    moves = {move for m in members for move in (m.moveset.fast, *m.moveset.charged)}
    used = []
    for path in paths:
        try:
            touched_species, touched_moves = touched_ids(path)
        except CustomDataError as e:
            raise ConfigError(str(e)) from e
        if species & touched_species or moves & touched_moves:
            used.append(path.name)
    return tuple(used)
