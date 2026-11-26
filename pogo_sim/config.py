"""配置文件（TOML）的共用部分：1v1 九宫格（matchups.py）和 3v3（team_battle.py）都用。

- 一只宝可梦的写法（Entry）：种类、配招，可选 label、IV、等级、挚友、Mega 等级、outside_movepool；
- 按赛季规则建配置（prepare_entry → Participant），并检查招式；
- 参数表（[policy]、[rules] 这类）转成 dataclass，检查参数名和值的类型（parse_params）；
- 报告里一只宝可梦的一行说明、Markdown 表格。

写错时抛出 ConfigError，信息里指出是哪个文件、哪一项。
"""

import tomllib
from dataclasses import dataclass, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

from pogo_sim.combatant import PokemonBuild, make_combatant
from pogo_sim.gamemaster import GameMaster
from pogo_sim.moveset import Moveset, moves_outside_movepool
from pogo_sim.season import SeasonRules, season_build
from pogo_sim.stats import IVs, calculate_cp

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

ENTRY_KEYS = frozenset({
    "label", "species", "fast", "charged",
    "ivs", "level", "best_buddy", "mega_level", "outside_movepool",
})


class ConfigError(ValueError):
    """配置文件写错了。"""


def load_toml(path: Path) -> dict[str, Any]:
    with open(path, "rb") as f:
        try:
            return tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path.name}：不是合法的 TOML（{e}）") from e


def resolve_path(path: str) -> Path:
    """配置里的路径：相对路径按仓库根目录算。"""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def check_unknown_keys(raw: dict[str, Any], allowed: set[str] | frozenset[str], where: str) -> None:
    unknown = set(raw) - set(allowed)
    if unknown:
        raise ConfigError(f"{where}：不认识的字段 {', '.join(sorted(unknown))}")


# ---- 参数表 ----


def parse_params(cls: type, raw: Any, where: str, what: str, prefix: str = "") -> Any:
    """把一个参数表转成 cls（frozen dataclass，例如 SimplePolicyConfig、BattleRules）。

    只能写 cls 里有的字段；值的类型要对（Literal 的取值、true / false、整数、数字）。
    字段本身是 dataclass 的（例如 TeamPolicyConfig.moves）写成子表，例如 [policy.moves]。
    what 是报错时的叫法，例如"策略参数"；prefix 是子表的前缀（报错时写成 moves.bait_shields）。
    没写的字段用 cls 的默认值。
    """
    if not isinstance(raw, dict):
        table = f" {prefix.rstrip('.')}" if prefix else ""
        raise ConfigError(f"{where}：{what}{table} 要写成表，得到 {raw!r}")
    hints = get_type_hints(cls)
    names = [f.name for f in fields(cls)]
    values: dict[str, Any] = {}
    for key, value in raw.items():
        name = f"{prefix}{key}"
        if key not in names:
            raise ConfigError(f"{where}：不认识的{what} {name}（可用：{', '.join(prefix + n for n in names)}）")
        hint = hints[key]
        if is_dataclass(hint):
            values[key] = parse_params(hint, value, where, what, prefix=f"{name}.")
            continue
        ok, expected = _check_value(hint, value)
        if expected is None:
            raise ConfigError(f"{where}：{what} {name} 不能在配置文件里改")
        if not ok:
            raise ConfigError(f"{where}：{what} {name} 要写 {expected}，得到 {value!r}")
        values[key] = float(value) if hint is float else value
    return cls(**values)


def _check_value(hint: Any, value: Any) -> tuple[bool, str | None]:
    """值是否符合类型；第二项是报错时写的"要写什么"，None 表示这种类型不支持在配置里写。"""
    if get_origin(hint) is Literal:
        return value in get_args(hint), " / ".join(repr(v) for v in get_args(hint))
    if hint is bool:
        return isinstance(value, bool), "true / false"
    if hint is int:
        return isinstance(value, int) and not isinstance(value, bool), "整数"
    if hint is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool), "数字"
    return False, None


def params_to_dict(params: Any) -> dict[str, Any]:
    """parse_params 的反方向：dataclass 转成嵌套的 dict（报告里列出参数用）。"""
    result: dict[str, Any] = {}
    for f in fields(params):
        value = getattr(params, f.name)
        result[f.name] = params_to_dict(value) if is_dataclass(value) else value
    return result


def merge_tables(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """把 override 合并到 base 上（子表逐项合并），返回新的 dict。"""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_tables(merged[key], value)
        else:
            merged[key] = value
    return merged


def format_params(params: Any, defaults: Any | None = None) -> str:
    """参数写成一行 key = value；给了 defaults 时只写和默认不同的。子表写成 moves.bait_shields。"""
    items = _flatten(params_to_dict(params))
    if defaults is not None:
        default_items = dict(_flatten(params_to_dict(defaults)))
        items = [(k, v) for k, v in items if default_items.get(k) != v]
    return ", ".join(f"{k} = {_toml_value(v)}" for k, v in items)


def _flatten(table: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    items = []
    for key, value in table.items():
        if isinstance(value, dict):
            items += _flatten(value, f"{prefix}{key}.")
        else:
            items.append((f"{prefix}{key}", value))
    return items


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


# ---- 一只宝可梦 ----


@dataclass(frozen=True)
class Entry:
    """配置文件里的一只宝可梦（还没按赛季规则建配置）。"""

    label: str | None  # None：用宝可梦名
    species_id: str
    moveset: Moveset
    ivs: IVs | None = None
    level: float | None = None
    best_buddy: bool = False
    mega_level: int | None = None
    outside_movepool: bool = False


def parse_entry(raw: dict[str, Any], where: str, extra_keys: frozenset[str] = frozenset()) -> Entry:
    """一只宝可梦的表。extra_keys 是调用方自己处理的其他字段（这里不报"不认识"）。"""
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}：要写成表，得到 {raw!r}")
    check_unknown_keys(raw, ENTRY_KEYS | extra_keys, where)
    for key in ("species", "fast", "charged"):
        if key not in raw:
            raise ConfigError(f"{where}：缺少 {key}")

    def check(key: str, ok: bool, expected: str) -> None:
        if key in raw and not ok:
            raise ConfigError(f"{where}：{key} 要写{expected}，得到 {raw[key]!r}")

    check("label", isinstance(raw.get("label"), str), "字符串")
    check("species", isinstance(raw.get("species"), str), "字符串")
    check("fast", isinstance(raw.get("fast"), str), "字符串")
    charged = raw["charged"]
    check("charged", isinstance(charged, list) and all(isinstance(m, str) for m in charged), "字符串列表")
    ivs = raw.get("ivs")
    check(
        "ivs",
        isinstance(ivs, list) and len(ivs) == 3 and all(isinstance(v, int) for v in ivs),
        " 3 个整数（攻 / 防 / HP）",
    )
    level = raw.get("level")
    check("level", isinstance(level, (int, float)) and not isinstance(level, bool), "数字")
    check("best_buddy", isinstance(raw.get("best_buddy"), bool), " true / false")
    mega_level = raw.get("mega_level")
    check("mega_level", isinstance(mega_level, int) and not isinstance(mega_level, bool), "整数")
    check("outside_movepool", isinstance(raw.get("outside_movepool"), bool), " true / false")

    try:
        parsed_ivs = IVs(*ivs) if ivs is not None else None
    except ValueError as e:
        raise ConfigError(f"{where}：{e}") from e
    return Entry(
        label=raw.get("label"),
        species_id=raw["species"],
        moveset=Moveset(raw["fast"], tuple(charged)),
        ivs=parsed_ivs,
        level=float(level) if level is not None else None,
        best_buddy=raw.get("best_buddy", False),
        mega_level=mega_level,
        outside_movepool=raw.get("outside_movepool", False),
    )


def entry_table(entry: Entry) -> dict[str, Any]:
    """parse_entry 反过来：一只写成配置文件里的表，没设的可选项不写。parse_entry(entry_table(e)) == e。

    网页把队伍对队伍里随机抽的队伍送到"打一场"页时用（web_api.matrix_pairing_config）。
    """
    table: dict[str, Any] = {
        "species": entry.species_id,
        "fast": entry.moveset.fast,
        "charged": list(entry.moveset.charged),
    }
    if entry.label is not None:
        table["label"] = entry.label
    if entry.ivs is not None:
        table["ivs"] = [entry.ivs.atk, entry.ivs.def_, entry.ivs.hp]
    if entry.level is not None:
        table["level"] = entry.level
    if entry.best_buddy:
        table["best_buddy"] = True
    if entry.mega_level is not None:
        table["mega_level"] = entry.mega_level
    if entry.outside_movepool:
        table["outside_movepool"] = True
    return table


@dataclass(frozen=True)
class Participant:
    """按赛季规则建好配置的一只宝可梦。"""

    label: str
    build: PokemonBuild
    outside_movepool: tuple[str, ...]  # 配置里允许的招式池外招式；没有时为空


def prepare_entry(gm: GameMaster, entry: Entry, league: int, season: SeasonRules) -> Participant:
    """按赛季规则建配置，并检查招式。种类、招式、等级不合法时抛出 KeyError / ValueError。"""
    species = gm.get_species(entry.species_id)
    outside = moves_outside_movepool(species, entry.moveset)
    if outside and not entry.outside_movepool:
        raise ValueError(
            f"{entry.species_id} 的招式池里没有 {', '.join(outside)}。"
            "要试招式池外的招，给这套配招写 outside_movepool = true，或者用覆盖文件改招式池"
        )
    build = season_build(
        gm,
        entry.species_id,
        league,
        entry.moveset.fast,
        entry.moveset.charged,
        season=season,
        ivs=entry.ivs,
        level=entry.level,
        best_buddy=entry.best_buddy,
        mega_level=entry.mega_level,
    )
    if outside:
        note = f"招式池外的招式：{', '.join(outside)}（配置里写了 outside_movepool = true）"
        build = replace(build, notes=build.notes + (note,))
    make_combatant(gm, build, 0)  # 提前检查招式（快招 / 大招、第三个大招的规则）
    return Participant(entry.label or species.name, build, tuple(outside))


def error_message(e: Exception) -> str:
    """KeyError 的 str() 带引号，取原始信息。"""
    return e.args[0] if e.args else str(e)


# ---- 报告 ----


def format_table(header: list[str], rows: list[list[str]]) -> str:
    """Markdown 表格。"""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def marked(participant: Participant) -> str:
    """招式池外的配招在名字后面加 *。"""
    return participant.label + ("*" if participant.outside_movepool else "")


def format_participant(gm: GameMaster, participant: Participant) -> str:
    """一行说明，例如"Dragon Tail：Zygarde (Mega)，CP 8568，50 级，IV 15/15/15，DRAGON_TAIL / CRUNCH, ..."。"""
    build = participant.build
    species = gm.get_species(build.species_id)
    ivs = build.ivs
    cp = calculate_cp(species.base_stats, ivs, build.level)
    moves = Moveset(build.fast_move_id, build.charged_move_ids).describe()
    line = (
        f"{marked(participant)}：{species.name}，CP {cp}，{build.level:g} 级，"
        f"IV {ivs.atk}/{ivs.def_}/{ivs.hp}，{moves}"
    )
    if participant.outside_movepool:
        line += f"（招式池外：{', '.join(participant.outside_movepool)}）"
    return line
