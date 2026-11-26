"""对战配置文件和九宫格。"""

from pathlib import Path

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import UNCAPPED_CP, make_combatant
from pogo_sim.config import load_toml
from pogo_sim.matchups import (
    REPO_ROOT,
    MatchupConfigError,
    ShieldGrid,
    battle_names,
    fight,
    find_participant,
    format_grid,
    format_outcome,
    format_report,
    load_matchup_config,
    make_sides,
    parse_matchup_config,
    prepare_matchups,
    run_all,
    shield_grid,
)
from pogo_sim.season import MEGA_PLUS_2, PVPOKE_SEASON
from pogo_sim.simple_policy import SimplePolicy, SimplePolicyConfig
from pogo_sim.team import Team

EXAMPLE_CONFIG = REPO_ROOT / "experiments" / "mega_zygarde_ml.toml"

# 小配置：超级联盟，Mega 雪妖女对玛力露丽（与 tests/test_mega_1v1.py 同一对）
SMALL_CONFIG = """
league = 1500
season = "pvpoke"
custom_files = ["data/custom/mega_froslass.toml"]

[[subject]]
species = "froslass_mega"
fast = "POWDER_SNOW"
charged = ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"]

[[opponent]]
species = "azumarill"
fast = "BUBBLE"
charged = ["ICE_BEAM", "PLAY_ROUGH"]
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


# ---- 示例配置 ----


def test_example_config_loads() -> None:
    config = load_matchup_config(EXAMPLE_CONFIG)
    assert config.league == UNCAPPED_CP
    assert config.season == PVPOKE_SEASON
    assert config.policy == SimplePolicyConfig()
    assert config.custom_files == (REPO_ROOT / "data" / "custom" / "mega_zygarde.toml",)
    assert [e.label for e in config.subjects] == [
        "Dragon Tail + Bulldoze", "Bite + Bulldoze", "Dragon Tail + Earthquake",
    ]
    assert len(config.opponents) == 6


def test_example_outside_movepool_is_marked() -> None:
    matchups = prepare_matchups(load_matchup_config(EXAMPLE_CONFIG))
    avalanche = find_participant(matchups.opponents, "Mega Mewtwo Y (Avalanche)")
    assert avalanche.outside_movepool == ("AVALANCHE",)
    assert avalanche.build.notes[-1] == "招式池外的招式：AVALANCHE（配置里写了 outside_movepool = true）"
    assert find_participant(matchups.opponents, "Lugia").outside_movepool == ()


def test_example_grid_matches_direct_battles() -> None:
    """九宫格的每一格就是用对应盾数直接打一场的评分。"""
    matchups = prepare_matchups(load_matchup_config(EXAMPLE_CONFIG))
    subject = find_participant(matchups.subjects, "Dragon Tail + Bulldoze")
    opponent = find_participant(matchups.opponents, "Mega Mewtwo Y (Thunderbolt)")
    grid = shield_grid(matchups, subject, opponent)

    for mine in range(3):
        for theirs in range(3):
            sides = (
                Team((make_combatant(matchups.gm, subject.build, 0),), shields=mine),
                Team((make_combatant(matchups.gm, opponent.build, 1),), shields=theirs),
            )
            result = Battle(sides, (SimplePolicy(), SimplePolicy())).run()
            assert grid.ratings[mine][theirs] == result.ratings[0]
    # 0 盾对 0 盾：上一版（单独的脚本）算出的同一场
    assert grid.ratings[0][0] == 513


# ---- 小配置：报告 ----


def test_report_for_small_config(tmp_path: Path) -> None:
    matchups = prepare_matchups(load_matchup_config(_write(tmp_path, SMALL_CONFIG)))
    subject, opponent = matchups.subjects[0], matchups.opponents[0]
    assert (subject.label, opponent.label) == ("Froslass (Mega)", "Azumarill")  # 不写 label 时用宝可梦名

    grids = run_all(matchups)
    assert len(grids) == 1
    # 2 盾对 2 盾：tests/test_mega_1v1.py 里的同一场
    assert grids[0].ratings[2][2] == 578
    sides = make_sides(matchups, subject, opponent, 2, 2)
    assert [side.shields for side in sides] == [2, 2]

    report = format_report(matchups, grids, source="config.toml")
    assert "- 联盟：超级联盟；赛季规则：PvPoke 兼容" in report
    assert (
        "- Froslass (Mega)：Froslass (Mega)，CP 1498，14.5 级，IV 4/15/15，"
        "POWDER_SNOW / AVALANCHE, SHADOW_BALL, AVALANCHE_PLUS"
    ) in report
    summary_row = f"| Froslass (Mega) | {grids[0].wins}/9 胜，平均 {grids[0].average:.0f} |"
    assert summary_row in report
    assert format_grid(grids[0]) in report
    assert "招式池外" not in report


def test_policy_and_season_from_config(tmp_path: Path) -> None:
    text = SMALL_CONFIG.replace('season = "pvpoke"', 'season = "mega_plus_2"') + (
        '\n[policy]\nbait_shields = false\nshielding = "when_low"\nshield_hp_fraction = 0.3\n'
    )
    config = load_matchup_config(_write(tmp_path, text))
    assert config.season == MEGA_PLUS_2
    assert config.policy == SimplePolicyConfig(
        bait_shields=False, shielding="when_low", shield_hp_fraction=0.3
    )


def test_entry_options(tmp_path: Path) -> None:
    text = SMALL_CONFIG.replace(
        'species = "azumarill"',
        'species = "azumarill"\nlabel = "Azu"\nivs = [15, 15, 15]\nlevel = 30\nbest_buddy = true',
    )
    matchups = prepare_matchups(load_matchup_config(_write(tmp_path, text)))
    azu = matchups.opponents[0]
    assert azu.label == "Azu"
    assert (azu.build.level, (azu.build.ivs.atk, azu.build.ivs.def_, azu.build.ivs.hp)) == (30.0, (15, 15, 15))


# ---- 九宫格 ----


def test_shield_grid_wins_and_average() -> None:
    grid = ShieldGrid("A", "B", ((500, 501, 100), (900, 800, 700), (0, 1000, 499)))
    assert grid.wins == 5  # 刚好 500 不算赢
    assert grid.average == pytest.approx(5000 / 9)
    assert format_grid(grid).splitlines() == [
        "| A 对 B | 对手 0 盾 | 对手 1 盾 | 对手 2 盾 |",
        "|---|---|---|---|",
        "| 自己 0 盾 | 500 | 501 | 100 |",
        "| 自己 1 盾 | 900 | 800 | 700 |",
        "| 自己 2 盾 | 0 | 1000 | 499 |",
    ]


# ---- 写错的配置 ----


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("league = 1500", "league = 1500\nleage = 2500", "不认识的字段 leage"),
        ("league = 1500\n", "", "缺少 league"),
        ("league = 1500", 'league = "1500"', "league 要写正整数"),
        ('season = "pvpoke"', 'season = "s27"', "不认识的赛季规则 's27'"),
        ('custom_files = ["data/custom/mega_froslass.toml"]', 'custom_files = "x.toml"', "custom_files 要写字符串列表"),
        ('fast = "BUBBLE"', 'fast = "BUBBLE"\nshield = 2', "opponent 第 1 项：不认识的字段 shield"),
        ('fast = "BUBBLE"\n', "", "opponent 第 1 项：缺少 fast"),
        ('charged = ["ICE_BEAM", "PLAY_ROUGH"]', 'charged = "ICE_BEAM"', "charged 要写字符串列表"),
        ('fast = "BUBBLE"', 'fast = "BUBBLE"\nivs = [15, 15]', "ivs 要写 3 个整数"),
        ('fast = "BUBBLE"', 'fast = "BUBBLE"\nivs = [16, 15, 15]', "opponent 第 1 项："),
        ('fast = "BUBBLE"', 'fast = "BUBBLE"\nbest_buddy = 1', "best_buddy 要写 true / false"),
    ],
)
def test_bad_config_file(tmp_path: Path, old: str, new: str, message: str) -> None:
    assert old in SMALL_CONFIG
    with pytest.raises(MatchupConfigError, match=message):
        load_matchup_config(_write(tmp_path, SMALL_CONFIG.replace(old, new)))


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ("bait_shield = false", "不认识的策略参数 bait_shield"),
        ('shielding = "sometimes"', "策略参数 shielding 要写 'always' / 'never' / 'when_low'"),
        ('bait_shields = "no"', "策略参数 bait_shields 要写 true / false"),
        ("shield_hp_fraction = true", "策略参数 shield_hp_fraction 要写 数字"),
    ],
)
def test_bad_policy(tmp_path: Path, policy: str, message: str) -> None:
    with pytest.raises(MatchupConfigError, match=message):
        load_matchup_config(_write(tmp_path, SMALL_CONFIG + f"\n[policy]\n{policy}\n"))


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # 招式池外的招没有写 outside_movepool
        ('charged = ["ICE_BEAM", "PLAY_ROUGH"]', 'charged = ["ICE_BEAM", "SURF"]', "azumarill 的招式池里没有 SURF"),
        ('species = "azumarill"', 'species = "azumarrill"', "找不到宝可梦：azumarrill"),
        # 普通宝可梦不能带第三个大招
        ('charged = ["ICE_BEAM", "PLAY_ROUGH"]', 'charged = ["ICE_BEAM", "PLAY_ROUGH", "HYDRO_PUMP"]', "不能带第三个大招"),
    ],
)
def test_bad_entry_found_when_preparing(tmp_path: Path, old: str, new: str, message: str) -> None:
    config = load_matchup_config(_write(tmp_path, SMALL_CONFIG.replace(old, new)))
    with pytest.raises(MatchupConfigError, match=f"对手第 1 项.*{message}"):
        prepare_matchups(config)


def test_move_kind_checked_even_outside_movepool(tmp_path: Path) -> None:
    """outside_movepool 只放宽招式池，快招 / 大招的区分照样检查。"""
    text = SMALL_CONFIG.replace('fast = "BUBBLE"', 'fast = "ICE_BEAM"\noutside_movepool = true')
    with pytest.raises(MatchupConfigError, match="对手第 1 项.*ICE_BEAM 不是快速技能"):
        prepare_matchups(load_matchup_config(_write(tmp_path, text)))


def test_outside_movepool_allowed_when_flagged(tmp_path: Path) -> None:
    text = SMALL_CONFIG.replace(
        'charged = ["ICE_BEAM", "PLAY_ROUGH"]', 'charged = ["ICE_BEAM", "SURF"]\noutside_movepool = true'
    )
    matchups = prepare_matchups(load_matchup_config(_write(tmp_path, text)))
    assert matchups.opponents[0].outside_movepool == ("SURF",)
    report = format_report(matchups, run_all(matchups))
    assert "| Froslass (Mega) | " in report and "Azumarill* |" in report
    assert "（招式池外：SURF）" in report


def test_duplicate_labels(tmp_path: Path) -> None:
    text = SMALL_CONFIG + '\n[[opponent]]\nspecies = "azumarill"\nfast = "BUBBLE"\ncharged = ["PLAY_ROUGH"]\n'
    with pytest.raises(MatchupConfigError, match="对手里有重名的 Azumarill"):
        prepare_matchups(load_matchup_config(_write(tmp_path, text)))


# ---- 网页用的几个函数（4g） ----


def test_parse_dict_same_as_file() -> None:
    """读进来的 dict 和配置文件走同一套检查（网页发来的配置走 parse_matchup_config）。"""
    raw = load_toml(EXAMPLE_CONFIG)
    assert parse_matchup_config(raw, EXAMPLE_CONFIG.name) == load_matchup_config(EXAMPLE_CONFIG)
    with pytest.raises(MatchupConfigError, match="^网页：配置要写成表（键值对），得到 list$"):
        parse_matchup_config([1], "网页")
    with pytest.raises(MatchupConfigError, match="^网页：缺少 subject$"):
        parse_matchup_config({"league": 1500, "season": "pvpoke"}, "网页")


def test_battle_names_and_outcome(tmp_path: Path) -> None:
    matchups = prepare_matchups(load_matchup_config(_write(tmp_path, SMALL_CONFIG)))
    subject, opponent = matchups.subjects[0], matchups.opponents[0]
    assert battle_names(subject, opponent) == ("Froslass (Mega)", "Azumarill")
    # 镜像对局：名字后面加上是哪一方
    assert battle_names(subject, subject) == ("Froslass (Mega)（测试对象）", "Froslass (Mega)（对手）")

    result = fight(matchups, make_sides(matchups, subject, opponent, 2, 2))
    assert result.winner == 0 and result.ratings[0] == 578  # 同 test_report_for_small_config
    hp = (result.snapshots[-1].sides[0].hp, result.snapshots[-1].sides[1].hp)
    assert format_outcome(("A", "B"), result) == (
        f"A 赢。评分 578 对 {result.ratings[1]}；剩余 HP {hp[0]} 对 {hp[1]}；"
        f"{result.turns} 回合，对战时间 {result.elapsed_ms / 1000:g} 秒。"
    )
