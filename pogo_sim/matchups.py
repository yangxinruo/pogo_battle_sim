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

一只宝可梦的写法、参数表的检查、报告里的一行说明和 3v3 配置（team_battle.py）共用，在 config.py。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.combatant import make_combatant
from pogo_sim.config import (  # 共用部分；REPO_ROOT、Entry、Participant 也从这里导入
    REPO_ROOT,
    ConfigError,
    Entry,
    Participant,
    check_unknown_keys,
    error_message,
    format_participant,
    format_table,
    load_toml,
    marked,
    parse_entry,
    parse_params,
    prepare_entry,
    resolve_path,
)
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.season import SEASON_PRESETS, SeasonRules, league_name
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team

SHIELD_COUNTS: tuple[int, ...] = (0, 1, 2)
WIN_RATING = 500  # 评分大于 500 算赢（一方倒下时，赢家的评分一定大于 500，见 battle.battle_rating）

_TOP_LEVEL_KEYS = {"description", "custom_files", "league", "season", "policy", "subject", "opponent"}
_GROUP_NAMES = {"subject": "测试对象", "opponent": "对手"}


# 配置写错时的异常（和 3v3 配置共用，见 config.ConfigError）
MatchupConfigError = ConfigError


# ---- 配置 ----


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
    raw = load_toml(path)
    where = path.name

    check_unknown_keys(raw, _TOP_LEVEL_KEYS, where)
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
        custom_files=tuple(resolve_path(p) for p in custom_files),
        league=league,
        season=SEASON_PRESETS[season_key],
        policy=parse_params(SimplePolicyConfig, raw.get("policy", {}), where, "策略参数"),
        subjects=_parse_group(raw["subject"], f"{where}：subject"),
        opponents=_parse_group(raw["opponent"], f"{where}：opponent"),
    )


def _parse_group(raw: Any, where: str) -> tuple[Entry, ...]:
    if not isinstance(raw, list) or not raw:
        raise MatchupConfigError(f"{where}：至少要写一个（[[...]] 表）")
    return tuple(parse_entry(item, f"{where} 第 {i + 1} 项") for i, item in enumerate(raw))


# ---- 按赛季规则建配置 ----


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
            participants.append(prepare_entry(gm, entry, config.league, config.season))
        except (KeyError, ValueError) as e:
            raise MatchupConfigError(f"{where}：{error_message(e)}") from e

    labels = [p.label for p in participants]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise MatchupConfigError(
            f"{_GROUP_NAMES[group]}里有重名的 {', '.join(duplicates)}：同一种宝可梦写了几套配招时，给每套写 label"
        )
    return tuple(participants)


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


def format_summary(matchups: Matchups, grids: Sequence[ShieldGrid]) -> str:
    """总表：行是测试对象，列是对手，每格是九宫格里赢了几场和平均评分。"""
    by_pair = {(g.subject, g.opponent): g for g in grids}
    header = ["测试对象 \\ 对手", *(marked(o) for o in matchups.opponents)]
    rows = []
    for subject in matchups.subjects:
        cells = []
        for opponent in matchups.opponents:
            grid = by_pair[(subject.label, opponent.label)]
            cells.append(f"{grid.wins}/9 胜，平均 {grid.average:.0f}")
        rows.append([marked(subject), *cells])
    return format_table(header, rows)


def format_grid(grid: ShieldGrid) -> str:
    """一个九宫格：行是测试对象的盾数，列是对手的盾数。"""
    header = [f"{grid.subject} 对 {grid.opponent}", *(f"对手 {s} 盾" for s in SHIELD_COUNTS)]
    rows = [
        [f"自己 {mine} 盾", *(str(r) for r in grid.ratings[mine])]
        for mine in SHIELD_COUNTS
    ]
    return format_table(header, rows)


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
