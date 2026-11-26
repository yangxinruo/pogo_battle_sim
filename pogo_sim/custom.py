"""自定义覆盖文件：未发布的宝可梦和招式，或对已有条目的修改。

覆盖文件是 TOML，字段名与 PvPoke 的 gamemaster.json 相同，示例见 data/custom/，
规则见 docs/mechanics.md 第 10 节。覆盖文件不会自动生效，要显式传给 load_gamemaster。

合并发生在原始数据这一层（gamemaster.json 读进来的字典，还没转成 Species / Move），
合并完和 gamemaster 走同一套解析，所以不会有两套解析逻辑。

四种表，写法 [表名.ID]，按下面的顺序应用（先招式后宝可梦，宝可梦才能用同一个文件里新加的招式）：
  new_moves      新招式。ID 已经存在时报错
  patch_moves    修改已有招式。只替换写出来的字段，其余保持原样；ID 不存在时报错
  new_pokemon    新宝可梦。ID 已经存在时报错
  patch_pokemon  修改已有宝可梦。规则同 patch_moves
另有一个 [meta] 表放说明（description、sources），加载时不用。

报错的用意："新"的 ID 撞上已有条目，多半是 PvPoke 后来加了同名条目，要人来决定是删掉自定义还是改成 patch；
"改"的 ID 不存在，多半是拼错了。两种情况都不该悄悄继续。

宝可梦可以用 mainSeriesStats（正作六项种族值）代替 baseStats，加载时用
conversion.convert_with_details 换算；tags 里有 "mega" 时用 Mega 的削弱规则。
"""

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pogo_sim.conversion import (
    MEGA_NERF,
    STANDARD_NERF,
    MainSeriesStats,
    NerfRule,
    convert_with_details,
)
from pogo_sim.typechart import ALL_TYPES

# 原始数据里的一个条目（gamemaster.json 里的一个对象）。
RawEntry = dict[str, Any]

CUSTOM_DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data" / "custom"

TABLE_ORDER: tuple[str, ...] = ("new_moves", "patch_moves", "new_pokemon", "patch_pokemon")
META_TABLE = "meta"

# 新条目必须写的字段（ID 由表名后面的键给出，不用写 moveId / speciesId）。
# 这些是 gamemaster.py 解析时一定会读的字段；其他字段可以省略，解析时用默认值。
REQUIRED_MOVE_FIELDS: tuple[str, ...] = ("name", "type", "power", "energy", "energyGain", "turns")
REQUIRED_POKEMON_FIELDS: tuple[str, ...] = (
    "speciesName",
    "dex",
    "types",
    "fastMoves",
    "chargedMoves",
)
NUMERIC_MOVE_FIELDS: tuple[str, ...] = ("power", "energy", "energyGain", "turns")
MOVE_LIST_FIELDS: tuple[str, ...] = ("fastMoves", "chargedMoves", "extraChargedMoves")

# 本项目加的字段：正作六项种族值。键名 → MainSeriesStats 的字段名。
MAIN_SERIES_STATS_FIELD = "mainSeriesStats"
MAIN_SERIES_KEYS: dict[str, str] = {
    "hp": "hp",
    "attack": "attack",
    "defense": "defense",
    "spAttack": "sp_attack",
    "spDefense": "sp_defense",
    "speed": "speed",
}
BASE_STATS_FIELD = "baseStats"
BASE_STATS_KEYS: tuple[str, ...] = ("atk", "def", "hp")

# gamemaster 用 "none" 占第二属性的位置。
NO_TYPE = "none"


class CustomDataError(ValueError):
    """覆盖文件写错了。信息里带文件名和条目。"""


@dataclass
class CustomFileResult:
    """应用一个覆盖文件的结果。"""

    log: list[str] = field(default_factory=list)  # 每条改动一行，写明改了什么、种族值怎么来的
    species_ids: set[str] = field(default_factory=set)  # 新增或修改过的宝可梦，加载后要检查它们的招式


def apply_custom_file(
    path: Path,
    species: dict[str, RawEntry],
    moves: dict[str, RawEntry],
    standard_nerf: NerfRule = STANDARD_NERF,
    mega_nerf: NerfRule = MEGA_NERF,
) -> CustomFileResult:
    """把一个覆盖文件应用到原始数据上。直接修改传入的 species 和 moves 两个字典。

    species / moves：按 ID 索引的原始条目。
    standard_nerf / mega_nerf：mainSeriesStats 换算时用的削弱规则，默认与 conversion 模块一致。
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    source = path.name

    unknown_tables = set(data) - set(TABLE_ORDER) - {META_TABLE}
    if unknown_tables:
        raise CustomDataError(
            f"{source}：不认识的表 {sorted(unknown_tables)}，只能用 {list(TABLE_ORDER)} 和 {META_TABLE}"
        )

    # 允许的字段 = gamemaster 里出现过的所有字段（有些本项目不用，但从 PvPoke 复制过来时不必删）。
    # 写了别的字段多半是拼错了，报错。
    allowed_move_fields = _fields_in_use(moves)
    allowed_species_fields = _fields_in_use(species) | {MAIN_SERIES_STATS_FIELD}

    result = CustomFileResult()
    for table in TABLE_ORDER:
        for entry_id, fields in data.get(table, {}).items():
            where = f"{source} [{table}.{entry_id}]"
            if not isinstance(fields, dict):
                raise CustomDataError(f"{where}：应该是一个表（字段 = 值），得到 {fields!r}")

            if table in ("new_moves", "patch_moves"):
                _check_fields(fields, allowed_move_fields, "moveId", entry_id, where)
                if table == "new_moves":
                    line = _new_move(entry_id, fields, moves, where)
                else:
                    line = _patch_move(entry_id, fields, moves, where)
            else:
                _check_fields(fields, allowed_species_fields, "speciesId", entry_id, where)
                if table == "new_pokemon":
                    line = _new_pokemon(entry_id, fields, species, where, standard_nerf, mega_nerf)
                else:
                    line = _patch_pokemon(entry_id, fields, species, where, standard_nerf, mega_nerf)
                result.species_ids.add(entry_id)

            result.log.append(f"{source}：{line}")

    return result


def touched_ids(path: Path) -> tuple[set[str], set[str]]:
    """覆盖文件新加或修改的宝可梦 ID 和招式 ID：(宝可梦, 招式)。只看表名下面的键，不检查内容。

    队伍库用它判断一队用到了哪些覆盖文件（team_library.custom_files_used）。
    """
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise CustomDataError(f"{path.name}：不是合法的 TOML（{e}）") from e
    species = {key for table in ("new_pokemon", "patch_pokemon") for key in data.get(table, {})}
    moves = {key for table in ("new_moves", "patch_moves") for key in data.get(table, {})}
    return species, moves


# ---- 招式 ----


def _new_move(move_id: str, fields: RawEntry, moves: dict[str, RawEntry], where: str) -> str:
    if move_id in moves:
        raise CustomDataError(f"{where}：招式 {move_id} 已经存在；要修改已有招式请用 patch_moves")
    _check_required(fields, REQUIRED_MOVE_FIELDS, where)
    entry = {"moveId": move_id, **fields}
    _check_move(entry, where)
    moves[move_id] = entry
    return f"新招式 {move_id}（{_format_fields(fields)}）"


def _patch_move(move_id: str, fields: RawEntry, moves: dict[str, RawEntry], where: str) -> str:
    if move_id not in moves:
        raise CustomDataError(f"{where}：招式 {move_id} 不存在；要新增招式请用 new_moves")
    old = moves[move_id]
    entry = {**old, **fields}
    _check_move(entry, where)
    moves[move_id] = entry
    return f"修改招式 {move_id}：{_format_changes(old, fields)}"


def _check_move(entry: RawEntry, where: str) -> None:
    _check_type_name(entry["type"], where)
    for name in NUMERIC_MOVE_FIELDS:
        _check_number(entry[name], name, where)


# ---- 宝可梦 ----


def _new_pokemon(
    species_id: str,
    fields: RawEntry,
    species: dict[str, RawEntry],
    where: str,
    standard_nerf: NerfRule,
    mega_nerf: NerfRule,
) -> str:
    if species_id in species:
        raise CustomDataError(
            f"{where}：宝可梦 {species_id} 已经存在；要修改已有宝可梦请用 patch_pokemon"
        )
    _check_required(fields, REQUIRED_POKEMON_FIELDS, where)
    has_main = MAIN_SERIES_STATS_FIELD in fields
    has_base = BASE_STATS_FIELD in fields
    if has_main == has_base:
        raise CustomDataError(
            f"{where}：{MAIN_SERIES_STATS_FIELD}（正作种族值）和 {BASE_STATS_FIELD}（GO 种族值）必须写一个，也只能写一个"
        )

    entry = {"speciesId": species_id, **fields}
    stats_note = _resolve_stats(entry, where, standard_nerf, mega_nerf)
    _check_pokemon(entry, where)
    species[species_id] = entry

    base = entry[BASE_STATS_FIELD]
    return (
        f"新宝可梦 {species_id}（{entry['speciesName']}）："
        f"种族值 {base['atk']}/{base['def']}/{base['hp']}{stats_note}"
    )


def _patch_pokemon(
    species_id: str,
    fields: RawEntry,
    species: dict[str, RawEntry],
    where: str,
    standard_nerf: NerfRule,
    mega_nerf: NerfRule,
) -> str:
    if species_id not in species:
        raise CustomDataError(f"{where}：宝可梦 {species_id} 不存在；要新增宝可梦请用 new_pokemon")
    if MAIN_SERIES_STATS_FIELD in fields and BASE_STATS_FIELD in fields:
        raise CustomDataError(
            f"{where}：{MAIN_SERIES_STATS_FIELD} 和 {BASE_STATS_FIELD} 只能写一个"
        )

    old = species[species_id]
    entry = {**old, **fields}
    stats_note = _resolve_stats(entry, where, standard_nerf, mega_nerf)
    _check_pokemon(entry, where)
    species[species_id] = entry

    # 种族值单独说明（mainSeriesStats 换算后改的是 baseStats），其他字段列出新旧值。
    other_fields = {
        key: value
        for key, value in fields.items()
        if key not in (MAIN_SERIES_STATS_FIELD, BASE_STATS_FIELD)
    }
    parts = []
    if MAIN_SERIES_STATS_FIELD in fields or BASE_STATS_FIELD in fields:
        before, after = old[BASE_STATS_FIELD], entry[BASE_STATS_FIELD]
        parts.append(
            f"种族值 {before['atk']}/{before['def']}/{before['hp']} → "
            f"{after['atk']}/{after['def']}/{after['hp']}{stats_note}"
        )
    if other_fields:
        parts.append(_format_changes(old, other_fields))
    return f"修改宝可梦 {species_id}：{'；'.join(parts)}"


def _resolve_stats(
    entry: RawEntry, where: str, standard_nerf: NerfRule, mega_nerf: NerfRule
) -> str:
    """如果条目写的是 mainSeriesStats，换算成 baseStats 并删掉 mainSeriesStats。

    返回写进日志的换算说明；条目直接写 baseStats 时返回空字符串。
    换算时按条目（合并后的）tags 判断是不是 Mega，用对应的削弱规则。
    """
    if MAIN_SERIES_STATS_FIELD not in entry:
        return ""

    raw = entry.pop(MAIN_SERIES_STATS_FIELD)
    if not isinstance(raw, dict) or set(raw) != set(MAIN_SERIES_KEYS):
        raise CustomDataError(
            f"{where}：{MAIN_SERIES_STATS_FIELD} 要写全六项 {list(MAIN_SERIES_KEYS)}，得到 {raw!r}"
        )
    for key, value in raw.items():
        _check_positive_int(value, f"{MAIN_SERIES_STATS_FIELD}.{key}", where)
    main = MainSeriesStats(**{MAIN_SERIES_KEYS[key]: value for key, value in raw.items()})

    is_mega = "mega" in entry.get("tags", [])
    conversion = convert_with_details(
        main, is_mega=is_mega, nerf_rule=mega_nerf if is_mega else standard_nerf
    )
    stats = conversion.stats
    entry[BASE_STATS_FIELD] = {"atk": stats.atk, "def": stats.def_, "hp": stats.hp}

    main_text = "/".join(str(raw[key]) for key in MAIN_SERIES_KEYS)
    kind = "Mega 规则" if is_mega else "非 Mega 规则"
    return f"（由正作 {main_text} 换算，{kind}：{conversion.describe()}）"


def _check_pokemon(entry: RawEntry, where: str) -> None:
    base = entry.get(BASE_STATS_FIELD)
    if not isinstance(base, dict) or set(base) != set(BASE_STATS_KEYS):
        raise CustomDataError(
            f"{where}：{BASE_STATS_FIELD} 要写全 {list(BASE_STATS_KEYS)}，得到 {base!r}"
        )
    for key, value in base.items():
        _check_positive_int(value, f"{BASE_STATS_FIELD}.{key}", where)

    types = entry["types"]
    if not isinstance(types, list) or not 1 <= len(types) <= 2:
        raise CustomDataError(f"{where}：types 要写 1 到 2 个属性，得到 {types!r}")
    real_types = [t for t in types if t != NO_TYPE]
    if not real_types or len(set(real_types)) != len(real_types):
        raise CustomDataError(f"{where}：types 不对：{types!r}")
    for type_name in real_types:
        _check_type_name(type_name, where)

    for name in MOVE_LIST_FIELDS:
        value = entry.get(name, [])
        if not isinstance(value, list) or not all(isinstance(m, str) for m in value):
            raise CustomDataError(f"{where}：{name} 要写成招式 ID 的列表，得到 {value!r}")

    if not isinstance(entry["dex"], int) or isinstance(entry["dex"], bool):
        raise CustomDataError(f"{where}：dex 要写整数，得到 {entry['dex']!r}")


# ---- 通用检查和格式化 ----


def _fields_in_use(entries: dict[str, RawEntry]) -> set[str]:
    """数据里出现过的所有字段名。"""
    fields: set[str] = set()
    for entry in entries.values():
        fields.update(entry)
    return fields


def _check_fields(
    fields: RawEntry, allowed: set[str], id_field: str, entry_id: str, where: str
) -> None:
    unknown = set(fields) - allowed
    if unknown:
        raise CustomDataError(f"{where}：不认识的字段 {sorted(unknown)}（字段名要和 gamemaster.json 一致）")
    if id_field in fields and fields[id_field] != entry_id:
        raise CustomDataError(
            f"{where}：{id_field} 写的是 {fields[id_field]!r}，和表名里的 ID {entry_id!r} 不一致"
        )


def _check_required(fields: RawEntry, required: tuple[str, ...], where: str) -> None:
    missing = [name for name in required if name not in fields]
    if missing:
        raise CustomDataError(f"{where}：缺少字段 {missing}")


def _check_type_name(type_name: str, where: str) -> None:
    if type_name not in ALL_TYPES:
        raise CustomDataError(f"{where}：不认识的属性 {type_name!r}")


def _check_number(value: Any, name: str, where: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise CustomDataError(f"{where}：{name} 要写非负数，得到 {value!r}")


def _check_positive_int(value: Any, name: str, where: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CustomDataError(f"{where}：{name} 要写正整数，得到 {value!r}")


def _show(value: Any) -> str:
    """日志里显示一个字段值。用 JSON 写法，和 gamemaster.json 一致。"""
    return json.dumps(value, ensure_ascii=False)


def _format_fields(fields: RawEntry) -> str:
    return "，".join(f"{key} {_show(value)}" for key, value in fields.items())


def _format_changes(old: RawEntry, fields: RawEntry) -> str:
    """列出每个被改字段的旧值和新值；原来没有这个字段时旧值写"（无）"。"""
    parts = []
    for key, value in fields.items():
        before = _show(old[key]) if key in old else "（无）"
        parts.append(f"{key} {before} → {_show(value)}")
    return "，".join(parts)
