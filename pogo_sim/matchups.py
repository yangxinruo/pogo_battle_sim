"""对战配置：一组测试对象对一组对手，每一对打 0–2 盾对 0–2 盾的九宫格。

配置写在 TOML 文件里（例子：experiments/mega_zygarde_ml.toml）。换配招、对手、联盟、赛季规则、
策略参数都只改配置文件，不改代码。用 tools/run_matchups.py 运行。

文件格式：
    description = "说明"                               # 可选
    custom_files = ["data/custom/mega_zygarde.toml"]   # 可选：覆盖文件，路径相对仓库根目录。
                                                       # 赛季的招式平衡调整也写成覆盖文件（patch_moves）放这里
    league = 10000                                     # CP 上限：500 / 1500 / 2500 / 10000（大师联盟）
    season = "pvpoke"                                  # 赛季规则预设，见 season.SEASON_PRESETS

    [policy]                                           # 可选：简单规则策略的参数（SimplePolicyConfig），双方相同
    bait_shields = false

    [[subject]]                                        # 测试对象（九宫格的行），可以有多个
    label = "Dragon Tail"                              # 可选：报告里的名字，默认是宝可梦名；同一组里不能重名
    species = "zygarde_mega"
    fast = "DRAGON_TAIL"
    charged = ["CRUNCH", "BULLDOZE", "NIHIL_LIGHT"]
    # 以下可选：
    # ivs = [15, 15, 15]          攻 / 防 / HP；不写时用 IV 排名第 1
    # level = 50                  不写时用上限内 CP 合法的最高等级
    # best_buddy = true
    # mega_level = 4
    # outside_movepool = true     允许招式池外的招式（见 moveset.py），报告里会标出来

    [[opponent]]                                       # 对手，写法同上
    ...

九宫格里的评分都是从测试对象一方看的 PvPoke 对战评分（battle.battle_rating），大于 500 算赢。
"""

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.combatant import PokemonBuild, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.moveset import Moveset, moves_outside_movepool
from pogo_sim.season import SEASON_PRESETS, SeasonRules, league_name, season_build
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.stats import IVs, calculate_cp
from pogo_sim.team import Team

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

SHIELD_COUNTS: tuple[int, ...] = (0, 1, 2)
WIN_RATING = 500  # 评分大于 500 算赢（一方倒下时，赢家的评分一定大于 500，见 battle.battle_rating）

_TOP_LEVEL_KEYS = {"description", "custom_files", "league", "season", "policy", "subject", "opponent"}
_ENTRY_KEYS = {
    "label", "species", "fast", "charged",
    "ivs", "level", "best_buddy", "mega_level", "outside_movepool",
}
_GROUP_NAMES = {"subject": "测试对象", "opponent": "对手"}


class MatchupConfigError(ValueError):
    """对战配置文件写错了。"""


# ---- 配置 ----


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


@dataclass(frozen=True)
class MatchupConfig:
    description: str
    custom_files: tuple[Path, ...]
    league: int
    season: SeasonRules
    policy: SimplePolicyConfig
    subjects: tuple[Entry, ...]
    opponents: tuple[Entry, ...]


def load_matchup_config(path: Path | str) -> MatchupConfig:
    """读取并检查对战配置文件（格式见模块说明）。写错时抛出 MatchupConfigError。"""
    path = Path(path)
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    where = path.name

    unknown = set(raw) - _TOP_LEVEL_KEYS
    if unknown:
        raise MatchupConfigError(f"{where}：不认识的字段 {', '.join(sorted(unknown))}")
    for key in ("league", "season", "subject", "opponent"):
        if key not in raw:
            raise MatchupConfigError(f"{where}：缺少 {key}")

    league = raw["league"]
    if not isinstance(league, int) or isinstance(league, bool) or league <= 0:
        raise MatchupConfigError(f"{where}：league 要写正整数（CP 上限），得到 {league!r}")
    season_key = raw["season"]
    if season_key not in SEASON_PRESETS:
        raise MatchupConfigError(
            f"{where}：不认识的赛季规则 {season_key!r}（可用：{', '.join(SEASON_PRESETS)}）"
        )

    custom_files = raw.get("custom_files", [])
    if not isinstance(custom_files, list) or not all(isinstance(p, str) for p in custom_files):
        raise MatchupConfigError(f"{where}：custom_files 要写字符串列表")

    return MatchupConfig(
        description=str(raw.get("description", "")),
        custom_files=tuple(_resolve(p) for p in custom_files),
        league=league,
        season=SEASON_PRESETS[season_key],
        policy=_parse_policy(raw.get("policy", {}), where),
        subjects=_parse_group(raw["subject"], f"{where}：subject"),
        opponents=_parse_group(raw["opponent"], f"{where}：opponent"),
    )


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _parse_policy(raw: dict[str, Any], where: str) -> SimplePolicyConfig:
    """[policy] 表：只能写 SimplePolicyConfig 里有的参数，值的类型要对。"""
    hints = get_type_hints(SimplePolicyConfig)
    for key, value in raw.items():
        if key not in hints:
            raise MatchupConfigError(
                f"{where}：不认识的策略参数 {key}（可用：{', '.join(hints)}）"
            )
        hint = hints[key]
        if get_origin(hint) is Literal:
            ok = value in get_args(hint)
            expected = " / ".join(repr(v) for v in get_args(hint))
        elif hint is bool:
            ok = isinstance(value, bool)
            expected = "true / false"
        else:  # float
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            expected = "数字"
        if not ok:
            raise MatchupConfigError(f"{where}：策略参数 {key} 要写 {expected}，得到 {value!r}")
    return SimplePolicyConfig(**raw)


def _parse_group(raw: Any, where: str) -> tuple[Entry, ...]:
    if not isinstance(raw, list) or not raw:
        raise MatchupConfigError(f"{where}：至少要写一个（[[...]] 表）")
    return tuple(_parse_entry(item, f"{where} 第 {i + 1} 项") for i, item in enumerate(raw))


def _parse_entry(raw: dict[str, Any], where: str) -> Entry:
    unknown = set(raw) - _ENTRY_KEYS
    if unknown:
        raise MatchupConfigError(f"{where}：不认识的字段 {', '.join(sorted(unknown))}")
    for key in ("species", "fast", "charged"):
        if key not in raw:
            raise MatchupConfigError(f"{where}：缺少 {key}")

    def check(key: str, ok: bool, expected: str) -> None:
        if key in raw and not ok:
            raise MatchupConfigError(f"{where}：{key} 要写{expected}，得到 {raw[key]!r}")

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
        raise MatchupConfigError(f"{where}：{e}") from e
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


# ---- 按赛季规则建配置 ----


@dataclass(frozen=True)
class Participant:
    """按赛季规则建好配置的一只宝可梦。"""

    label: str
    build: PokemonBuild
    outside_movepool: tuple[str, ...]  # 配置里允许的招式池外招式；没有时为空


@dataclass(frozen=True)
class Matchups:
    """准备好的一组对战：配置、加载了覆盖文件的 gamemaster、双方的配置。"""

    config: MatchupConfig
    gm: GameMaster
    subjects: tuple[Participant, ...]
    opponents: tuple[Participant, ...]


def prepare_matchups(config: MatchupConfig) -> Matchups:
    """加载覆盖文件，给每只宝可梦按赛季规则建配置，并检查招式。"""
    gm = load_gamemaster(custom_files=config.custom_files)
    return Matchups(
        config=config,
        gm=gm,
        subjects=_prepare_group(gm, config, config.subjects, "subject"),
        opponents=_prepare_group(gm, config, config.opponents, "opponent"),
    )


def _prepare_group(
    gm: GameMaster, config: MatchupConfig, entries: Sequence[Entry], group: str
) -> tuple[Participant, ...]:
    participants = []
    for i, entry in enumerate(entries):
        where = f"{_GROUP_NAMES[group]}第 {i + 1} 项（{entry.label or entry.species_id}）"
        try:
            participants.append(_prepare_entry(gm, config, entry))
        except (KeyError, ValueError) as e:
            message = e.args[0] if e.args else str(e)
            raise MatchupConfigError(f"{where}：{message}") from e

    labels = [p.label for p in participants]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise MatchupConfigError(
            f"{_GROUP_NAMES[group]}里有重名的 {', '.join(duplicates)}：同一种宝可梦写了几套配招时，给每套写 label"
        )
    return tuple(participants)


def _prepare_entry(gm: GameMaster, config: MatchupConfig, entry: Entry) -> Participant:
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
        config.league,
        entry.moveset.fast,
        entry.moveset.charged,
        season=config.season,
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


# ---- 对战和九宫格 ----


@dataclass(frozen=True)
class ShieldGrid:
    """一对宝可梦在 0–2 盾对 0–2 盾下的评分，从测试对象一方看。"""

    subject: str
    opponent: str
    # ratings[测试对象的盾数][对手的盾数]
    ratings: tuple[tuple[int, ...], ...]

    def all_ratings(self) -> list[int]:
        return [r for row in self.ratings for r in row]

    @property
    def wins(self) -> int:
        return sum(1 for r in self.all_ratings() if r > WIN_RATING)

    @property
    def average(self) -> float:
        ratings = self.all_ratings()
        return sum(ratings) / len(ratings)


def make_sides(
    matchups: Matchups,
    subject: Participant,
    opponent: Participant,
    subject_shields: int,
    opponent_shields: int,
) -> tuple[Team, Team]:
    """建立一场 1v1 的双方（每队一只）：测试对象是第 0 方，对手是第 1 方。"""
    gm = matchups.gm
    return (
        Team((make_combatant(gm, subject.build, 0),), shields=subject_shields),
        Team((make_combatant(gm, opponent.build, 1),), shields=opponent_shields),
    )


def fight(matchups: Matchups, sides: tuple[Team, Team]) -> BattleResult:
    """双方都用配置里的简单规则策略打一场。"""
    policy = matchups.config.policy
    return Battle(sides, (SimplePolicy(policy), SimplePolicy(policy))).run()


def shield_grid(matchups: Matchups, subject: Participant, opponent: Participant) -> ShieldGrid:
    ratings = tuple(
        tuple(
            fight(matchups, make_sides(matchups, subject, opponent, mine, theirs)).ratings[0]
            for theirs in SHIELD_COUNTS
        )
        for mine in SHIELD_COUNTS
    )
    return ShieldGrid(subject.label, opponent.label, ratings)


def run_all(matchups: Matchups) -> list[ShieldGrid]:
    """全部九宫格：先按测试对象，再按对手的顺序。"""
    return [
        shield_grid(matchups, subject, opponent)
        for subject in matchups.subjects
        for opponent in matchups.opponents
    ]


def find_participant(group: Sequence[Participant], label: str) -> Participant:
    for participant in group:
        if participant.label == label:
            return participant
    raise KeyError(f"找不到 {label!r}（可用：{', '.join(p.label for p in group)}）")


# ---- 报告（Markdown） ----


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _marked(participant: Participant) -> str:
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
        f"{_marked(participant)}：{species.name}，CP {cp}，{build.level:g} 级，"
        f"IV {ivs.atk}/{ivs.def_}/{ivs.hp}，{moves}"
    )
    if participant.outside_movepool:
        line += f"（招式池外：{', '.join(participant.outside_movepool)}）"
    return line


def format_summary(matchups: Matchups, grids: Sequence[ShieldGrid]) -> str:
    """总表：行是测试对象，列是对手，每格是九宫格里赢了几场和平均评分。"""
    by_pair = {(g.subject, g.opponent): g for g in grids}
    header = ["测试对象 \\ 对手", *(_marked(o) for o in matchups.opponents)]
    rows = []
    for subject in matchups.subjects:
        cells = []
        for opponent in matchups.opponents:
            grid = by_pair[(subject.label, opponent.label)]
            cells.append(f"{grid.wins}/9 胜，平均 {grid.average:.0f}")
        rows.append([_marked(subject), *cells])
    return _table(header, rows)


def format_grid(grid: ShieldGrid) -> str:
    """一个九宫格：行是测试对象的盾数，列是对手的盾数。"""
    header = [f"{grid.subject} 对 {grid.opponent}", *(f"对手 {s} 盾" for s in SHIELD_COUNTS)]
    rows = [
        [f"自己 {mine} 盾", *(str(r) for r in grid.ratings[mine])]
        for mine in SHIELD_COUNTS
    ]
    return _table(header, rows)


def format_report(matchups: Matchups, grids: Sequence[ShieldGrid], source: str = "") -> str:
    """完整报告：设置、双方配置、总表、每一对的九宫格。"""
    config = matchups.config
    lines = []
    if config.description:
        lines += [config.description, ""]
    if source:
        lines.append(f"- 配置文件：`{source}`")
    lines.append(f"- 联盟：{league_name(config.league)}；赛季规则：{config.season.name}")
    lines.append(f"- 策略：双方都是简单规则策略，参数 {config.policy}")
    lines.append(
        "- 评分：PvPoke 的对战评分，从测试对象一方看。"
        "500 × 对手损失的 HP 比例 + 500 × 自己剩余的 HP 比例，向下取整；大于 500 算赢"
    )
    for log in matchups.gm.custom_log:
        lines.append(f"- 覆盖文件：{log}")
    lines += ["", "测试对象：", ""]
    lines += [f"- {format_participant(matchups.gm, p)}" for p in matchups.subjects]
    lines += ["", "对手：", ""]
    lines += [f"- {format_participant(matchups.gm, p)}" for p in matchups.opponents]
    if any(p.outside_movepool for p in (*matchups.subjects, *matchups.opponents)):
        lines += ["", "\\* 带了招式池外的招式（假设）。"]
    lines += ["", "## 总表", "", "每格是 0–2 盾对 0–2 盾九场里赢了几场，以及九场的平均评分。", ""]
    lines.append(format_summary(matchups, grids))
    lines += ["", "## 九宫格", ""]
    for grid in grids:
        lines += [format_grid(grid), ""]
    return "\n".join(lines).rstrip() + "\n"
