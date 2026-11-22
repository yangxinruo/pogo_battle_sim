"""1v1 对战配置里的环境前 N（[[opponent_pool]]，3v3-f1）。"""

import csv
import io
import re
from pathlib import Path

import pytest

from pogo_sim.matchups import (
    REPO_ROOT,
    WIN_RATING,
    MatchupConfigError,
    find_opponent,
    find_participant,
    format_csv,
    format_pool_summary,
    format_report,
    load_matchup_config,
    prepare_matchups,
    run_all,
    run_pools,
    shield_grid,
)
from pogo_sim.rankings import PoolSpec

EXAMPLE_CONFIG = REPO_ROOT / "experiments" / "gl_mega_froslass_top.toml"

# 小配置：Mega 雪妖女和普通雪妖女，对 Mega 前 2、非 Mega 前 3（mega 排名，超级联盟）
POOL_CONFIG = """
league = 1500
season = "pvpoke"
custom_files = ["data/custom/mega_froslass.toml"]

[[subject]]
label = "Mega Froslass"
species = "froslass_mega"
fast = "POWDER_SNOW"
charged = ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"]

[[subject]]
species = "froslass"
fast = "POWDER_SNOW"
charged = ["AVALANCHE", "SHADOW_BALL"]

[[opponent_pool]]
name = "Mega 前 2"
rankings = "mega"
kind = "mega"
top = 2

[[opponent_pool]]
rankings = "mega"
kind = "non_mega"
top = 3
"""

EXPLICIT_OPPONENT = """
[[opponent]]
species = "azumarill"
fast = "BUBBLE"
charged = ["ICE_BEAM", "PLAY_ROUGH"]
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def pool_matchups(tmp_path_factory: pytest.TempPathFactory):
    path = _write(tmp_path_factory.mktemp("pools"), POOL_CONFIG + EXPLICIT_OPPONENT)
    return prepare_matchups(load_matchup_config(path))


# ---- 示例配置 ----


def test_example_config_loads() -> None:
    config = load_matchup_config(EXAMPLE_CONFIG)
    assert [e.label for e in config.subjects] == ["Mega Froslass (Powder Snow)", "Mega Froslass (Hex)", "Froslass"]
    assert config.opponents == ()
    assert config.opponent_pools == (
        PoolSpec("Mega 前 10", "mega", "mega", 10),
        PoolSpec("非 Mega 前 50", "mega", "non_mega", 50),
    )


def test_example_regression(tmp_path: Path) -> None:
    """示例报告里 Mega 雪妖女（Powder Snow）对 Mega 勾魂眼那一行（docs/experiments/gl_mega_froslass_top.md）。

    只取 Mega 前 1、只留第一个测试对象，省时间；配置的其余部分和示例相同。
    """
    text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    text = text.replace("top = 10", "top = 1").replace("top = 50", "top = 1")
    config = load_matchup_config(_write(tmp_path, text))
    matchups = prepare_matchups(config)
    pool_grids = run_pools(matchups)
    grid = pool_grids[0].by_subject[0][0]
    assert (grid.subject, grid.opponent) == ("Mega Froslass (Powder Snow)", "Sableye (Mega)")
    assert grid.all_ratings() == [426, 119, 119, 615, 615, 215, 615, 615, 284]
    report = (REPO_ROOT / "docs" / "experiments" / "gl_mega_froslass_top.md").read_text(encoding="utf-8")
    assert (
        "| 1 | Sableye (Mega) | 426 | 119 | 119 | **615** | **615** | 215 | **615** | **615** | 284 | 4/9 | 403 |"
        in report
    )


# ---- 准备和对战 ----


def test_pools_prepared(pool_matchups) -> None:
    pools = pool_matchups.pools
    assert [p.spec.name for p in pools] == ["Mega 前 2", "非 Mega 前 3（mega 排名）"]
    assert [p.label for p in pools[0].participants] == ["Sableye (Mega)", "Malamar (Mega)"]
    assert [m.ranked.rank for m in pools[1].members] == [2, 3, 4]
    assert [p.label for p in pool_matchups.opponents] == ["Azumarill"]


def test_pool_grids_are_shield_grids(pool_matchups) -> None:
    """环境前 N 的每一格和手写对手一样，就是 shield_grid（直接打九场）。"""
    pool_grids = run_pools(pool_matchups)
    assert len(pool_grids) == 2
    for pg in pool_grids:
        assert len(pg.by_subject) == len(pool_matchups.subjects)
        for subject, grids in zip(pool_matchups.subjects, pg.by_subject):
            assert [g.opponent for g in grids] == [p.label for p in pg.pool.participants]
            for opponent, grid in zip(pg.pool.participants, grids):
                assert grid == shield_grid(pool_matchups, subject, opponent)


def test_pool_summary_counts(pool_matchups) -> None:
    pool_grids = run_pools(pool_matchups)
    pg = pool_grids[1]
    rows = format_pool_summary(pool_matchups, pg).splitlines()[2:]
    for subject, grids, row in zip(pool_matchups.subjects, pg.by_subject, rows):
        same_1 = sum(1 for g in grids if g.ratings[1][1] > WIN_RATING)
        total = sum(g.wins for g in grids)
        average = sum(r for g in grids for r in g.all_ratings()) / (9 * len(grids))
        assert row == (
            f"| {subject.label} | 赢 {sum(1 for g in grids if g.ratings[0][0] > WIN_RATING)} / 3 | 赢 {same_1} / 3 "
            f"| 赢 {sum(1 for g in grids if g.ratings[2][2] > WIN_RATING)} / 3 | 赢 {total} / 27 | {average:.0f} |"
        )


def test_report_sections(pool_matchups) -> None:
    grids = run_all(pool_matchups)
    pool_grids = run_pools(pool_matchups)
    report = format_report(pool_matchups, grids, source="x.toml", pool_grids=pool_grids)
    # 手写对手照旧
    assert "## 总表" in report and "## 九宫格" in report and "对手：\n\n- Azumarill：" in report
    # 每组环境前 N 一节：说明、对手表、总表、每个测试对象一张表
    assert "- Mega 前 2：PvPoke 的 mega 排名（Mega 版，Mega 和非 Mega 一起排），超级联盟，Mega 前 2 只；" in report
    assert "## 环境前 N：Mega 前 2" in report
    assert "## 环境前 N：非 Mega 前 3（mega 排名）" in report
    assert report.count("### 对手") == 2 and report.count("### 总表") == 2
    assert report.count("### Mega Froslass") == 2 and report.count("### Froslass") == 2
    assert "| 2 | Melmetal | 93.8 | 1499 | 15.5 | 1/15/14 | THUNDER_SHOCK / DOUBLE_IRON_BASH, DYNAMIC_PUNCH |" in report
    # 一行一个对手的九宫格，赢的加粗
    grid = pool_grids[0].by_subject[0][0]
    cells = " | ".join(f"**{r}**" if r > WIN_RATING else str(r) for r in grid.all_ratings())
    assert f"| 1 | Sableye (Mega) | {cells} | {grid.wins}/9 | {grid.average:.0f} |" in report


def test_report_without_explicit_opponents(tmp_path: Path) -> None:
    text = POOL_CONFIG.replace("top = 2", "top = 1").replace("top = 3", "top = 1")
    matchups = prepare_matchups(load_matchup_config(_write(tmp_path, text)))
    report = format_report(matchups, run_all(matchups), pool_grids=run_pools(matchups))
    assert run_all(matchups) == []
    lines = report.splitlines()
    assert "对手：" not in lines and "## 九宫格" not in lines and "## 总表" not in lines
    assert "## 环境前 N：Mega 前 2" in report


def test_csv(pool_matchups) -> None:
    grids = run_all(pool_matchups)
    pool_grids = run_pools(pool_matchups)
    rows = list(csv.reader(io.StringIO(format_csv(pool_matchups, grids, pool_grids))))
    assert rows[0] == ["group", "rank", "subject", "opponent", "subject_shields", "opponent_shields", "rating"]
    # 2 个测试对象 ×（1 个手写 + 2 + 3）× 9
    assert len(rows) == 1 + 2 * 6 * 9
    assert rows[1] == ["手写", "", "Mega Froslass", "Azumarill", "0", "0", str(grids[0].ratings[0][0])]
    sableye = pool_grids[0].by_subject[1][0]
    assert ["Mega 前 2", "1", "Froslass", "Sableye (Mega)", "1", "2", str(sableye.ratings[1][2])] in rows


def test_find_opponent(pool_matchups) -> None:
    assert find_opponent(pool_matchups, "Azumarill") is pool_matchups.opponents[0]
    assert find_opponent(pool_matchups, "Malamar (Mega)") is pool_matchups.pools[0].participants[1]
    with pytest.raises(KeyError, match="找不到 'Lugia'"):
        find_opponent(pool_matchups, "Lugia")


def test_find_opponent_ambiguous(tmp_path: Path) -> None:
    """两组环境前 N 里同名、配置不同（这里 IV 规则不同）时分不清。配置相同就没关系。"""
    text = POOL_CONFIG.replace("top = 3", "top = 1") + (
        '\n[[opponent_pool]]\nname = "PvPoke IV"\nrankings = "mega"\nkind = "non_mega"\ntop = 1\nivs = "pvpoke_default"\n'
        '\n[[opponent_pool]]\nname = "again"\nrankings = "mega"\nkind = "mega"\ntop = 1\n'
    )
    matchups = prepare_matchups(load_matchup_config(_write(tmp_path, text)))
    with pytest.raises(KeyError, match="'Melmetal' 在几组环境前 N 里都有，配置不同"):
        find_opponent(matchups, "Melmetal")
    assert find_opponent(matchups, "Sableye (Mega)") is matchups.pools[0].participants[0]
    # 测试对象照旧用 find_participant
    assert find_participant(matchups.subjects, "Froslass") is matchups.subjects[1]


# ---- 写错的配置 ----


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("kind = \"mega\"\n", "", "opponent_pool 第 1 项：缺少 kind"),
        ("top = 2", "top = 2\ncount = 2", "opponent_pool 第 1 项：不认识的字段 count"),
        ("kind = \"mega\"", "kind = \"megas\"", "opponent_pool 第 1 项：kind 要写 'mega' / 'non_mega'，得到 'megas'"),
        ("top = 3", "top = 3\nivs = [15, 15, 15]", "opponent_pool 第 2 项：ivs 要写 'rank1' / 'pvpoke_default'"),
        ("top = 3", "top = 3\nname = \"Mega 前 2\"", "opponent_pool：name 重复：Mega 前 2"),
    ],
)
def test_bad_pool_config(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert old in POOL_CONFIG
    with pytest.raises(MatchupConfigError, match=re.escape(message)):
        load_matchup_config(_write(tmp_path, POOL_CONFIG.replace(old, new, 1)))


@pytest.mark.parametrize("value", ['"mega"', "[]"])
def test_pool_not_a_list(tmp_path: Path, value: str) -> None:
    text = f"opponent_pool = {value}\n" + POOL_CONFIG.split("[[opponent_pool]]")[0]
    with pytest.raises(MatchupConfigError, match=re.escape("opponent_pool：要写成 [[opponent_pool]] 表，至少一个")):
        load_matchup_config(_write(tmp_path, text))


def test_needs_some_opponents(tmp_path: Path) -> None:
    text = POOL_CONFIG.split("[[opponent_pool]]")[0]
    with pytest.raises(MatchupConfigError, match=re.escape("缺少对手（[[opponent]] 或 [[opponent_pool]]）")):
        load_matchup_config(_write(tmp_path, text))


def test_league_without_rankings(tmp_path: Path) -> None:
    text = POOL_CONFIG.replace("league = 1500", "league = 500").replace('custom_files = ["data/custom/mega_froslass.toml"]', "")
    text = text.replace('species = "froslass_mega"', 'species = "froslass"').replace(', "AVALANCHE_PLUS"', "")
    config = load_matchup_config(_write(tmp_path, text))
    with pytest.raises(MatchupConfigError, match=re.escape("环境前 N（Mega 前 2）：没有小小杯的 mega 排名")):
        prepare_matchups(config)


def test_explicit_opponent_clashes_with_pool(tmp_path: Path) -> None:
    text = POOL_CONFIG + EXPLICIT_OPPONENT.replace('species = "azumarill"', 'label = "Melmetal"\nspecies = "azumarill"')
    with pytest.raises(MatchupConfigError, match="手写的对手和环境前 N（非 Mega 前 3（mega 排名））里有重名的 Melmetal"):
        prepare_matchups(load_matchup_config(_write(tmp_path, text)))
