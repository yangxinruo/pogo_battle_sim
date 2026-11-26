"""队伍对队伍（pogo_sim/team_matrix.py，docs/mechanics.md 13.10）。"""

import csv
import io
import re
from collections import Counter
from pathlib import Path

import pytest

from pogo_sim.config import REPO_ROOT, ConfigError, Entry, entry_table, load_toml, parse_entry
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.moveset import Moveset
from pogo_sim.rankings import prepare_pool
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.season import PVPOKE_SEASON
from pogo_sim.simple_policy import SimplePolicyConfig
from pogo_sim.stats import IVs
from pogo_sim.team_battle import make_policies, prepare_team, run_team_battle
from pogo_sim.team_matrix import (
    GROUP_HANDWRITTEN,
    GROUP_SAMPLED,
    SampleSpec,
    TeamMatrix,
    draw_sample,
    find_team,
    format_csv,
    format_report,
    format_summary,
    iter_team_matrix,
    load_team_matrix_config,
    opponent_groups,
    outcome,
    pairing,
    parse_team_matrix_config,
    prepare_team_matrix,
    run_team_matrix,
    tally,
)
from pogo_sim.team_policy import TeamPolicyConfig

EXAMPLE = REPO_ROOT / "experiments" / "gl_team_matrix_example.toml"
EXAMPLE_TEXT = EXAMPLE.read_text(encoding="utf-8")
SMALL_TEXT = EXAMPLE_TEXT.replace("count = 50", "count = 3", 1)  # 抽样是逐队进行的：前 3 队和抽 50 队时的前 3 队相同


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "matrix.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _variant(tmp_path: Path, old: str, new: str, text: str = SMALL_TEXT) -> Path:
    """把配置里的 old 换成 new（old 必须在里面，只换第一处）。"""
    assert old in text
    return _write(tmp_path, text.replace(old, new, 1))


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


@pytest.fixture(scope="module")
def small(tmp_path_factory: pytest.TempPathFactory) -> TeamMatrix:
    """示例配置，只抽 3 队：我方 2 队 × 对手 4 队。"""
    return prepare_team_matrix(load_team_matrix_config(_write(tmp_path_factory.mktemp("small"), SMALL_TEXT)))


@pytest.fixture(scope="module")
def small_results(small: TeamMatrix):
    return run_team_matrix(small)


def _spec(**changes) -> SampleSpec:
    values = dict(
        rankings="mega", top=8, mega_top=3, count=20, seed=7, ivs="rank1", shields=2, policy=TeamPolicyConfig()
    )
    values.update(changes)
    return SampleSpec(**values)


# ---- 配置 ----


def test_example_config() -> None:
    config = load_team_matrix_config(EXAMPLE)
    assert config.league == 1500
    assert config.rules == PVPOKE_COMPAT
    assert [t.name for t in config.teams] == ["Team A", "Team A (Mega Froslass)"]
    assert [t.name for t in config.opponent_teams] == ["Team B"]
    assert config.sample == SampleSpec(
        rankings="mega", top=30, mega_top=10, count=50, seed=1, ivs="rank1", shields=2, policy=TeamPolicyConfig()
    )
    assert [e.species_id for e in config.teams[1].members] == ["azumarill", "medicham", "froslass_mega"]


def test_example_results(small: TeamMatrix, small_results) -> None:
    """回归：示例报告（docs/experiments/gl_team_matrix_example.md）里抽到的前 3 队和对它们的结果。"""
    sampled = [o for o in small.opponents if o.group == GROUP_SAMPLED]
    assert [o.member_names() for o in sampled] == [
        ["Corsola (Galarian) #11", "Rillaboom #26", "Malamar (Mega) #32"],
        ["Audino (Mega) #177", "Azumarill #22", "Quagsire (Shadow) #13"],
        ["Raichu (Mega X) #183", "Araquanid #18", "Altaria (Shadow) #8"],
    ]
    assert [o.name for o in small.opponents] == ["Team B", "抽样 1", "抽样 2", "抽样 3"]
    team_a = small_results[0]
    # 对 Team B 和 3v3 示例（gl_3v3_example.md）是同一场
    assert [r.ratings for r in team_a] == [(221, 778), (406, 593), (461, 538), (449, 550)]
    assert [r.ratings for r in small_results[1]] == [(566, 433), (414, 585), (419, 580), (250, 750)]
    assert [outcome(r) for r in small_results[1]] == ["赢", "输", "输", "输"]


def test_each_pairing_equals_a_standalone_battle(small: TeamMatrix, small_results) -> None:
    """每队只建一次配置、评估器在各场之间共用，结果和把这两队写进 3v3 配置单独打一场相同。"""
    config = small.config
    for team in (*small.teams, *small.opponents):  # 从配置（Entry）重新建，和抽样时用的候选相同
        assert prepare_team(small.gm, team.setup, config.league, config.season) == team.members
    for team, row in zip(small.teams, small_results):
        for opponent, result in zip(small.opponents, row):
            alone = run_team_battle(pairing(small, team, opponent))  # 不共用评估器
            assert (alone.ratings, alone.turns, alone.events) == (result.ratings, result.turns, result.events)


def test_evaluators_shared_across_battles(small: TeamMatrix) -> None:
    evaluators: dict[SimplePolicyConfig, MatchupEvaluator] = {}
    first = make_policies(pairing(small, small.teams[0], small.opponents[0]), evaluators)
    second = make_policies(pairing(small, small.teams[1], small.opponents[1]), evaluators)
    assert len({id(p.evaluator) for p in (*first, *second)}) == 1
    assert list(evaluators) == [SimplePolicyConfig()]


def test_mirror_names(small: TeamMatrix) -> None:
    """两队都有的宝可梦（抽样 2 也有 Azumarill）在时间线里后面加队名。"""
    battle = pairing(small, small.teams[0], small.opponents[2])
    assert battle.teams[0].names[0] == "Azumarill (Team A)"
    assert battle.teams[1].names[1] == "Azumarill (抽样 2)"


# ---- 抽样 ----


def test_sample_is_reproducible(gm: GameMaster) -> None:
    def names(spec: SampleSpec) -> list[list[str]]:
        return [t.member_names() for t in draw_sample(gm, spec, 1500, PVPOKE_SEASON, 3).teams]

    first = names(_spec())
    assert names(_spec()) == first
    assert names(_spec(seed=8)) != first
    # 抽得多时，前面的队伍不变
    assert names(_spec(count=30))[:20] == first


def test_sample_rules(gm: GameMaster) -> None:
    """每队正好 1 只 Mega，同一种不重复（按图鉴编号），成员组合不重复，都来自候选，出场顺序随机。"""
    sample = draw_sample(gm, _spec(count=60), 1500, PVPOKE_SEASON, 3)
    non_megas, megas = (set(p.participants) for p in sample.pools)
    assert len(non_megas) == 8 and len(megas) == 3
    mega_slots = Counter()
    for team in sample.teams:
        species = [gm.get_species(p.build.species_id) for p in team.members]
        assert sum(s.is_mega for s in species) == 1
        assert len({s.dex for s in species}) == 3
        assert all(p in non_megas | megas for p in team.members)
        mega_slots[next(i for i, s in enumerate(species) if s.is_mega)] += 1
        assert team.setup.shields == 2 and team.setup.policy == TeamPolicyConfig()
        assert [e.species_id for e in team.setup.members] == [p.build.species_id for p in team.members]
    assert set(mega_slots) == {0, 1, 2}  # Mega 首发、第二、第三只都有
    assert len({frozenset(p.label for p in t.members) for t in sample.teams}) == 60
    assert [t.name for t in sample.teams[:2]] == ["抽样 1", "抽样 2"]


def test_sample_without_megas(gm: GameMaster) -> None:
    sample = draw_sample(gm, _spec(mega_top=0), 1500, PVPOKE_SEASON, 3)
    assert len(sample.pools) == 1
    assert not any(gm.get_species(p.build.species_id).is_mega for t in sample.teams for p in t.members)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        # 非 Mega 前 2 + Mega 前 1：只有一种组合
        (dict(top=2, mega_top=1, count=2), "试了 100 次，只抽出 1 个不同的队伍，不够 2 个"),
        (dict(top=2, mega_top=0), "候选里不同种的宝可梦不够组成一队（3 只），把 top 调大"),
        (dict(rankings="all"), "all 排名里没有能用的 Mega"),
    ],
)
def test_sample_errors(gm: GameMaster, changes: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(f"opponent_sample：{message}")):
        draw_sample(gm, _spec(**changes), 1500, PVPOKE_SEASON, 3)


def test_sample_without_rankings(gm: GameMaster) -> None:
    with pytest.raises(ConfigError, match=re.escape("opponent_sample：没有小小杯的 mega 排名")):
        draw_sample(gm, _spec(), 500, PVPOKE_SEASON, 3)


# ---- 报告 ----


def test_tally(small_results) -> None:
    t = tally(small_results[1])
    assert (t.battles, t.wins, t.draws, t.losses) == (4, 1, 0, 3)
    assert t.mean_rating == sum(r.ratings[0] for r in small_results[1]) / 4


def test_summary(small: TeamMatrix, small_results) -> None:
    lines = format_summary(small, small_results).splitlines()
    assert lines[0] == "| 我方队伍 | 对手 | 场数 | 赢 | 平 | 输 | 平均评分 | 平均剩余只数（我方 / 对方） |"
    assert [line.split(" | ")[:6] for line in lines[2:]] == [
        ["| Team A", "手写", "1", "0", "0", "1"],
        ["| Team A", "抽样", "3", "0", "0", "3"],
        ["| Team A", "全部", "4", "0", "0", "4"],
        ["| Team A (Mega Froslass)", "手写", "1", "1", "0", "0"],
        ["| Team A (Mega Froslass)", "抽样", "3", "0", "0", "3"],
        ["| Team A (Mega Froslass)", "全部", "4", "1", "0", "3"],
    ]


def test_report(small: TeamMatrix, small_results) -> None:
    report = format_report(small, small_results, source="x.toml")
    lines = report.splitlines()
    for heading in (
        "## 我方队伍", "## 总表", "## Team A 的每一场", "## Team A (Mega Froslass) 的每一场",
        "## 对手队伍", "### 手写的（1 队）", "### 随机抽的（3 队）",
        "#### 候选：非 Mega 前 30", "#### 候选：Mega 前 10",
    ):
        assert heading in lines, heading
    assert "- 配置文件：`x.toml`" in lines
    assert (
        "- 对战：我方 2 队，每一队对 4 队对手（手写 1 队、随机抽 3 队）各打一场 3v3，我方是第 0 方。"
        "对战是确定的，同一个配置每次结果相同"
    ) in lines
    assert "| Team B | Swampert、Altaria、Trevenant | 输 | 221 对 778 | 0 对 3 | 0 对 0 | 100 |" in lines
    assert "| Team B | Swampert、Altaria、Trevenant | **赢** | 566 对 433 | 1 对 0 | 0 对 0 | 108 |" in lines
    assert "| 抽样 1 | Corsola (Galarian) #11 | Rillaboom #26 | Malamar (Mega) #32 |" in lines
    assert "随机种子 1：每队 1 只 Mega（Mega 前 10 只里抽）和 2 只非 Mega（非 Mega 前 30 只里抽）" in report


def test_example_report_is_current() -> None:
    """docs/experiments 里的示例报告和抽 3 队时的前几行一致（报告格式改了要重新生成）。"""
    saved = (REPO_ROOT / "docs" / "experiments" / "gl_team_matrix_example.md").read_text(encoding="utf-8")
    assert "| Team A | 抽样 | 50 | 13 | 0 | 37 | 456 | 0.40 / 1.02 |" in saved
    assert "| 抽样 1 | Corsola (Galarian) #11、Rillaboom #26、Malamar (Mega) #32 | 输 | 406 对 593 | 0 对 1 | 0 对 0 | 126 |" in saved


def test_report_without_handwritten_opponents(tmp_path: Path) -> None:
    text = re.sub(r"\[\[opponent_team\]\].*?(?=# ---- 对手：随机抽)", "", SMALL_TEXT, flags=re.S)
    text = text.replace("count = 3", "count = 1").replace("top = 30", "top = 5").replace("mega_top = 10", "mega_top = 2")
    matrix = prepare_team_matrix(load_team_matrix_config(_write(tmp_path, text)))
    assert [o.group for o in matrix.opponents] == [GROUP_SAMPLED]
    lines = format_report(matrix, run_team_matrix(matrix)).splitlines()
    assert "### 手写的（1 队）" not in lines
    summary_rows = [line for line in lines if line.startswith("| Team A")]
    assert [row.split(" | ")[1] for row in summary_rows][:2] == ["抽样", "抽样"]  # 只有一组时没有"全部"


def test_csv(small: TeamMatrix, small_results) -> None:
    rows = list(csv.reader(io.StringIO(format_csv(small, small_results))))
    assert rows[0] == [
        "team", "opponent_group", "opponent", "opponent_members", "result", "timed_out",
        "team_rating", "opponent_rating", "team_remaining", "opponent_remaining",
        "team_shields_left", "opponent_shields_left", "turns",
    ]
    assert len(rows) == 1 + 2 * 4
    assert rows[1] == ["Team A", GROUP_HANDWRITTEN, "Team B", "Swampert / Altaria / Trevenant", "loss", "0",
                       "221", "778", "0", "3", "0", "0", "100"]
    assert rows[7][:5] == ["Team A (Mega Froslass)", GROUP_SAMPLED, "抽样 2",
                           "Audino (Mega) #177 / Azumarill #22 / Quagsire (Shadow) #13", "loss"]


def test_find_team(small: TeamMatrix) -> None:
    assert find_team(small.opponents, "抽样 3", "对手") is small.opponents[3]
    with pytest.raises(ConfigError, match=re.escape("我方里没有叫 'Team C' 的队伍（有：Team A, Team A (Mega Froslass)）")):
        find_team(small.teams, "Team C", "我方")


# ---- 写错的配置 ----


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("count = 3", "count = 0", "opponent_sample：count 要写正整数，得到 0"),
        ("count = 3", "", "opponent_sample：缺少 count"),
        ("mega_top = 10", "mega_top = -1", "opponent_sample：mega_top 要写不小于 0 的整数，得到 -1"),
        ("seed = 1", 'seed = "a"', "opponent_sample：seed 要写整数，得到 'a'"),
        ("seed = 1", "seed = 1\nweights = true", "opponent_sample：不认识的字段 weights"),
        ("seed = 1", 'seed = 1\nivs = "max"', "opponent_sample：ivs 要写 'rank1' / 'pvpoke_default'，得到 'max'"),
        ("seed = 1", "seed = 1\nshields = 3", "opponent_sample：shields 要写 0 到 2 的整数，得到 3"),
        ('rankings = "mega"', 'rankings = "great"', "opponent_sample：rankings 要写 'all' / 'mega'，得到 'great'"),
        ("seed = 1", "seed = 1\npolicy = 1", "opponent_sample：policy 要写成表（[opponent_sample.policy]）"),
        ('name = "Team B"', 'name = "Team A"', "队伍名字不能重复：Team A"),
        ('name = "Team B"', 'name = "抽样 2"', "队伍名字不能重复：抽样 2（抽样的队伍叫\"抽样 1\"……"),
        (
            '[[opponent_team.member]]\nspecies = "trevenant"',
            '[[opponent_team.memb]]\nspecies = "trevenant"',
            "对手第 1 队（Team B）：不认识的字段 memb",
        ),
    ],
)
def test_bad_config(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_team_matrix_config(_variant(tmp_path, old, new))


def test_bad_opponent_team_size(tmp_path: Path) -> None:
    text = SMALL_TEXT.replace(
        '[[opponent_team.member]]\nspecies = "trevenant"\nfast = "SHADOW_CLAW"\ncharged = ["SEED_BOMB", "SHADOW_BALL"]\n', ""
    )
    with pytest.raises(
        ConfigError, match=re.escape("对手第 1 队（Team B）：每队要正好 3 只（[[opponent_team.member]]），得到 2")
    ):
        load_team_matrix_config(_write(tmp_path, text))


def test_needs_opponents(tmp_path: Path) -> None:
    text = re.sub(r"\[\[opponent_team\]\].*", "", SMALL_TEXT, flags=re.S)
    with pytest.raises(ConfigError, match=re.escape("缺少对手（[[opponent_team]] 或 [opponent_sample]）")):
        load_team_matrix_config(_write(tmp_path, text))


def test_sample_policy_overrides_shared_policy(tmp_path: Path) -> None:
    text = SMALL_TEXT.replace(
        'season = "pvpoke"', 'season = "pvpoke"\n[policy]\nswitch_below = 400', 1
    ) + '[opponent_sample.policy]\nswitching = "never"\n'
    config = load_team_matrix_config(_write(tmp_path, text))
    assert config.sample.policy == TeamPolicyConfig(switch_below=400, switching="never")
    assert config.teams[0].policy == TeamPolicyConfig(switch_below=400)
    assert config.opponent_teams[0].policy == TeamPolicyConfig(switch_below=400)


def test_prepare_errors_name_the_team(tmp_path: Path) -> None:
    config = load_team_matrix_config(_variant(tmp_path, 'species = "trevenant"', 'species = "trevenantt"'))
    with pytest.raises(ConfigError, match=re.escape("Team B 第 3 只（trevenantt）：找不到宝可梦：trevenantt")):
        prepare_team_matrix(config)


# ---- 网页用的（4h） ----


def test_parse_dict_same_as_file() -> None:
    """读进来的 dict 和配置文件走同一套检查（网页发来的配置走 parse_team_matrix_config）。"""
    assert parse_team_matrix_config(load_toml(EXAMPLE), EXAMPLE.name) == load_team_matrix_config(EXAMPLE)
    with pytest.raises(ConfigError, match="^网页：配置要写成表（键值对），得到 list$"):
        parse_team_matrix_config([1], "网页")


def test_iter_team_matrix(small: TeamMatrix, small_results) -> None:
    """逐场给出的结果和 run_team_matrix 相同，顺序是先按我方、再按对手。"""
    items = list(iter_team_matrix(small))
    assert [(i, j) for i, j, _ in items] == [(i, j) for i in range(2) for j in range(4)]
    assert all(result == small_results[i][j] for i, j, result in items)


def test_prepare_with_another_pool_builder(tmp_path: Path) -> None:
    """建抽样候选的函数可以换（网页换成带缓存的），抽出来的一样。"""
    calls = []

    def build(gm, spec, league, season):
        calls.append(spec.name)
        return prepare_pool(gm, spec, league, season)

    config = load_team_matrix_config(_write(tmp_path, SMALL_TEXT))
    assert prepare_team_matrix(config, build) == prepare_team_matrix(config)
    assert calls == ["非 Mega 前 30", "Mega 前 10"]


def test_opponent_groups(small: TeamMatrix) -> None:
    assert opponent_groups(small) == [(GROUP_HANDWRITTEN, [0]), (GROUP_SAMPLED, [1, 2, 3]), ("全部", [0, 1, 2, 3])]


def test_entry_table_roundtrip(small: TeamMatrix) -> None:
    """entry_table 是 parse_entry 反过来（网页把随机抽的队伍送到"打一场"页时用）。"""
    entries = [entry for team in (*small.teams, *small.opponents) for entry in team.setup.members]
    entries.append(Entry("X", "azumarill", Moveset("BUBBLE", ("ICE_BEAM",)), IVs(1, 2, 3), 20.5, True, 2, True))
    for entry in entries:
        assert parse_entry(entry_table(entry), "x") == entry
    assert entry_table(entries[0]) == {"species": "azumarill", "fast": "BUBBLE", "charged": ["ICE_BEAM", "PLAY_ROUGH"]}

