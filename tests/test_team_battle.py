"""3v3 配置文件与报告（pogo_sim/team_battle.py，docs/mechanics.md 13.8）。"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import make_combatant
from pogo_sim.config import REPO_ROOT, ConfigError
from pogo_sim.evaluation import MatchupEvaluator
from pogo_sim.report import format_result
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.simple_policy import SimplePolicyConfig
from pogo_sim.team import Team
from pogo_sim.team_battle import (
    format_outcome,
    format_team_battle_report,
    load_team_battle_config,
    make_policies,
    make_teams,
    member_summaries,
    opening_matchups,
    prepare_team_battle,
    run_team_battle,
    timeline_names,
)
from pogo_sim.team_policy import TeamPolicy, TeamPolicyConfig
from pogo_sim.timeline import SwitchEvent, format_timeline

EXAMPLE = REPO_ROOT / "experiments" / "gl_3v3_example.toml"
EXAMPLE_TEXT = EXAMPLE.read_text(encoding="utf-8")


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "battle.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _variant(tmp_path: Path, old: str, new: str) -> Path:
    """把示例配置里的 old 换成 new（old 必须在里面，而且只换第一处）。"""
    assert old in EXAMPLE_TEXT
    return _write(tmp_path, EXAMPLE_TEXT.replace(old, new, 1))


# ---- 示例配置 ----


def test_example_config() -> None:
    config = load_team_battle_config(EXAMPLE)
    assert config.league == 1500
    assert config.rules == PVPOKE_COMPAT
    assert [team.name for team in config.teams] == ["Team A", "Team B"]
    assert [team.shields for team in config.teams] == [2, 2]
    assert all(team.policy == TeamPolicyConfig() for team in config.teams)
    assert [entry.species_id for entry in config.teams[0].members] == ["azumarill", "medicham", "registeel"]


def test_example_result() -> None:
    """回归：示例配置的结果（IV 排名第 1，所以和 README 里 PvPoke 默认 IV 的那一场不同）。"""
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    result = run_team_battle(battle)
    assert format_outcome(battle, result) == (
        "Team B 赢。评分 221 对 778；剩余 0 只对 3 只；剩余盾 0 对 0；100 回合，对战时间 145 秒（大招每次按 10 秒算）。"
    )
    assert [(e.turn, e.actor, e.kind, e.to_slot) for e in result.events if isinstance(e, SwitchEvent)] == [
        (31, 1, "zero_turn", 2),
        (56, 0, "replacement", 2),
        (87, 0, "replacement", 1),
    ]


def test_same_as_running_the_battle_directly() -> None:
    """配置文件只是换个写法：和直接用这些配置、TeamPolicy 打一场完全相同。"""
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    from_config = run_team_battle(battle)

    teams = tuple(
        Team(tuple(make_combatant(battle.gm, p.build, side) for p in team.members), shields=2)
        for side, team in enumerate(battle.teams)
    )
    direct = Battle((teams[0], teams[1]), (TeamPolicy(), TeamPolicy())).run()
    assert direct.events == from_config.events
    assert format_result(direct, ("Team A", "Team B")) == format_result(from_config, ("Team A", "Team B"))


def test_policies_share_the_evaluator_when_possible(tmp_path: Path) -> None:
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    a, b = make_policies(battle)
    assert a.evaluator is b.evaluator

    path = _variant(tmp_path, 'name = "Team B"', 'name = "Team B"\n[team.policy.evaluation]\nbait_shields = false')
    a, b = make_policies(prepare_team_battle(load_team_battle_config(path)))
    assert a.evaluator is not b.evaluator
    assert b.config.evaluation == SimplePolicyConfig(bait_shields=False)


# ---- 策略和规则参数 ----


def test_policy_shared_and_per_team(tmp_path: Path) -> None:
    """[policy] 两队都用；[team.policy] 逐项覆盖它（子表也逐项合并）。"""
    text = EXAMPLE_TEXT.replace(
        '[[team]]\nname = "Team A"',
        '[policy]\nswitch_below = 400\n[policy.moves]\nshielding = "when_low"\n\n[[team]]\nname = "Team A"',
        1,
    ).replace(
        'name = "Team B"',
        'name = "Team B"\n[team.policy]\nswitching = "never"\n[team.policy.moves]\nbait_shields = false',
        1,
    )
    config = load_team_battle_config(_write(tmp_path, text))
    a, b = (team.policy for team in config.teams)
    assert a == TeamPolicyConfig(switch_below=400, moves=SimplePolicyConfig(shielding="when_low"))
    assert b == TeamPolicyConfig(
        switch_below=400,
        switching="never",
        moves=SimplePolicyConfig(shielding="when_low", bait_shields=False),
    )

    battle = prepare_team_battle(config)
    report = format_team_battle_report(battle, run_team_battle(battle), include_timeline=False)
    # 按 TeamPolicyConfig 里字段的顺序
    assert '- 策略：TeamPolicy，和默认不同的参数：moves.shielding = "when_low", switch_below = 400' in report
    assert (
        '- 策略：TeamPolicy，和默认不同的参数：moves.bait_shields = false, moves.shielding = "when_low", '
        'switching = "never", switch_below = 400'
    ) in report


def test_policy_from_config_is_used(tmp_path: Path) -> None:
    """一队不主动换人：和直接用 TeamPolicy(switching="never") 打的一样。"""
    path = _variant(tmp_path, 'name = "Team B"', 'name = "Team B"\n[team.policy]\nswitching = "never"')
    battle = prepare_team_battle(load_team_battle_config(path))
    result = run_team_battle(battle)
    direct = Battle(make_teams(battle), (TeamPolicy(), TeamPolicy(TeamPolicyConfig(switching="never")))).run()
    assert result.events == direct.events
    assert not any(isinstance(e, SwitchEvent) and e.actor == 1 and e.kind != "replacement" for e in result.events)


def test_rules_from_config(tmp_path: Path) -> None:
    path = _variant(
        tmp_path,
        'season = "pvpoke"',
        'season = "pvpoke"\n[rules]\ntimeout_result = "more_remaining"\nswitch_cooldown_ms = 30000\nshadow_attack = 1.25',
    )
    config = load_team_battle_config(path)
    assert config.rules == replace(
        PVPOKE_COMPAT, timeout_result="more_remaining", switch_cooldown_ms=30000, shadow_attack=1.25
    )
    battle = prepare_team_battle(config)
    report = format_team_battle_report(battle, run_team_battle(battle), include_timeline=False)
    assert (
        '- 机制规则：和 PvPoke 默认不同的：shadow_attack = 1.25, switch_cooldown_ms = 30000, '
        'timeout_result = "more_remaining"'
    ) in report


def test_shields_per_team(tmp_path: Path) -> None:
    path = _variant(tmp_path, 'name = "Team B"', 'name = "Team B"\nshields = 1')
    battle = prepare_team_battle(load_team_battle_config(path))
    teams = make_teams(battle)
    assert [team.shields for team in teams] == [2, 1]
    assert "**Team B**（第 1 方，1 盾）" in format_team_battle_report(battle, run_team_battle(battle))


# ---- 名字 ----


def test_mirror_names_get_team_suffix(tmp_path: Path) -> None:
    """两队都有的宝可梦，名字后面加队名，时间线里才分得清。"""
    text = EXAMPLE_TEXT.replace('species = "swampert"\nfast = "MUD_SHOT"\ncharged = ["HYDRO_CANNON", "EARTHQUAKE"]',
                                'species = "azumarill"\nfast = "BUBBLE"\ncharged = ["ICE_BEAM", "PLAY_ROUGH"]')
    battle = prepare_team_battle(load_team_battle_config(_write(tmp_path, text)))
    assert timeline_names(battle) == (
        ("Azumarill (Team A)", "Medicham", "Registeel"),
        ("Azumarill (Team B)", "Altaria", "Trevenant"),
    )
    result = run_team_battle(battle)
    timeline = format_timeline(result.events, timeline_names(battle), True)
    assert "T   1  Azumarill (Team A)  decides fast BUBBLE" in timeline  # 长名字后面也空两格


def test_labels(tmp_path: Path) -> None:
    path = _variant(tmp_path, 'species = "azumarill"', 'species = "azumarill"\nlabel = "Azu (Play Rough)"')
    battle = prepare_team_battle(load_team_battle_config(path))
    assert battle.teams[0].names[0] == "Azu (Play Rough)"
    assert "- 首发 Azu (Play Rough)：Azumarill，" in format_team_battle_report(battle, run_team_battle(battle))


# ---- 报告 ----


def test_member_summaries_add_up() -> None:
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    result = run_team_battle(battle)
    summaries = member_summaries(battle, result)
    assert [(s.side, s.slot) for s in summaries] == [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
    for side in (0, 1):
        mine = [s for s in summaries if s.side == side]
        theirs = [s for s in summaries if s.side != side]
        assert sum(s.damage_dealt for s in mine) == sum(s.damage_taken for s in theirs)
        # 盾：开局的盾 = 用掉的 + 剩下的
        assert sum(s.charged_shielded for s in mine) + result.shields_left[side] == 2
    for s in summaries:
        assert s.hp == max(0, s.max_hp - s.damage_taken)  # 没有回血；倒下时的溢出伤害也算
        assert (s.hp == 0) == (s.fainted_turn is not None)
    trevenant = summaries[5]
    assert (trevenant.hp, trevenant.damage_dealt, trevenant.fast_moves) == (9, 465, 29)
    assert trevenant.charged_moves == ("SEED_BOMB", "SEED_BOMB", "SHADOW_BALL", "SHADOW_BALL", "SHADOW_BALL")


def test_opening_matchups() -> None:
    """开局对位评分：就是 TeamPolicy 用的对位评估，双方满 HP、0 能量、两队开局的盾数。"""
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    (opening,) = opening_matchups(battle)  # 两队评估配置相同，只算第 0 方的
    assert opening.side == 0
    assert opening.ratings == ((452, 680, 421), (493, 379, 198), (269, 689, 334))
    azumarill = make_combatant(battle.gm, battle.teams[0].members[0].build, 0)
    swampert = make_combatant(battle.gm, battle.teams[1].members[0].build, 1)
    assert MatchupEvaluator().evaluate(azumarill, swampert, 2, 2, PVPOKE_COMPAT).rounded == 452


def test_opening_matchups_from_both_sides_when_evaluation_differs(tmp_path: Path) -> None:
    path = _variant(tmp_path, 'name = "Team B"', 'name = "Team B"\n[team.policy.evaluation]\nbait_shields = false')
    openings = opening_matchups(prepare_team_battle(load_team_battle_config(path)))
    assert [o.side for o in openings] == [0, 1]


def test_report_contents() -> None:
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    result = run_team_battle(battle)
    report = format_team_battle_report(battle, result, source="experiments/gl_3v3_example.toml")
    for line in [
        "- 配置文件：`experiments/gl_3v3_example.toml`",
        "- 机制规则：与 PvPoke 一致（默认）",
        "**Team A**（第 0 方，2 盾）",
        "- 首发 Azumarill：Azumarill，CP 1499，45.5 级，IV 0/15/15，BUBBLE / ICE_BEAM, PLAY_ROUGH",
        "- 后备 Trevenant：Trevenant，CP 1497，22 级，IV 0/15/15，SHADOW_CLAW / SEED_BOMB, SHADOW_BALL",
        "- 策略：TeamPolicy，默认参数",
        "队伍检查通过：每队 3 只；没有同一种宝可梦（按图鉴编号）；Mega 不超过 1 只。",
        format_outcome(battle, result),
        "| Team A | Azumarill | 0 / 196 | 55 | 80 | 219 | 15 | ICE_BEAM ×2 | 2 / 0 | 第 55 回合 |",
        "| Team A \\ Team B | Swampert | Altaria | Trevenant |",
        "| Azumarill | 452 | 680 | 421 |",
        "| 31 | Team B | Swampert → Trevenant | 0 回合换人 | switch: matchup vs Azumarill 424 < 450, "
        "Trevenant 644 >= 524 (Trevenant 644, Altaria 338) |",
        "| 56 | Team A | Azumarill → Registeel | 倒下后换人 | best matchup vs Trevenant: Registeel 398, Medicham 172 |",
        "| 21 | Swampert | HYDRO_CANNON | Azumarill | 开盾挡下 | always shield (2 left); with a shield, "
        "matchup vs Swampert 555 |",
        "| 45 | Trevenant | SEED_BOMB | Azumarill | 64 伤害，剩 HP 61 | 没有盾 |",
        "## 时间线",
    ]:
        assert line in report.splitlines(), line
    # 时间线就是 format_timeline 的输出（带原因）
    assert format_timeline(result.events, timeline_names(battle), show_decisions=True) in report
    assert "## 时间线" not in format_team_battle_report(battle, result, include_timeline=False)


def test_saved_shield_shows_in_report(tmp_path: Path) -> None:
    """不开盾、把盾留给后面时，"没开"那一栏和原因都写出来。用 README 的 PvPoke 默认 IV 那一场（第 30 回合留盾）。"""
    ivs = {
        "azumarill": "ivs = [4, 15, 13]\nlevel = 43", "medicham": "ivs = [7, 15, 14]\nlevel = 49",
        "registeel": "ivs = [8, 15, 14]\nlevel = 22.5", "swampert": "ivs = [6, 15, 12]\nlevel = 18.5",
        "altaria": "ivs = [4, 12, 13]\nlevel = 28.5", "trevenant": "ivs = [3, 13, 12]\nlevel = 22",
    }
    text = EXAMPLE_TEXT
    for species, extra in ivs.items():
        text = text.replace(f'species = "{species}"', f'species = "{species}"\n{extra}', 1)
    battle = prepare_team_battle(load_team_battle_config(_write(tmp_path, text)))
    result = run_team_battle(battle)
    # 和 README 那一场（tests/test_team_policy.py test_full_3v3）相同
    assert format_result(result, ("Team A", "Team B")) == (
        "Team B wins: rating 387 vs 612, Pokemon left 0 vs 2, shields left 0 vs 0, 126 turns"
    )
    report = format_team_battle_report(battle, result)
    rows = [line for line in report.splitlines() if line.startswith("| 30 | Swampert | HYDRO_CANNON |")]
    assert rows == [
        "| 30 | Swampert | HYDRO_CANNON | Azumarill | 36 伤害，剩 HP 115 | save shield for the bench: "
        "even with a shield, matchup vs Swampert 464 < 500 |"
    ]


# ---- 写错的配置 ----


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("league = 1500", "league = 1500\nleage = 2500", "不认识的字段 leage"),
        ("league = 1500\n", "", "缺少 league"),
        ('season = "pvpoke"', 'season = "s27"', "不认识的赛季规则 's27'"),
        ('name = "Team B"', 'name = "Team A"', "两队不能同名（Team A）"),
        ('name = "Team B"', 'name = ""', "第 2 队：name 要写非空的字符串"),
        ('name = "Team B"\n', "", "第 2 队：缺少 name"),
        ('name = "Team B"', 'name = "Team B"\nshield = 2', "第 2 队（Team B）：不认识的字段 shield"),
        ('name = "Team B"', 'name = "Team B"\nshields = 3', "shields 要写 0 到 2 的整数，得到 3"),
        ('name = "Team B"', 'name = "Team B"\nshields = "2"', "shields 要写 0 到 2 的整数"),
        ('name = "Team B"', 'name = "Team B"\npolicy = "never"', "policy 要写成表"),
        ('fast = "BUBBLE"', 'fast = "BUBBLE"\nshields = 2', "第 1 队（Team A）第 1 只：不认识的字段 shields"),
        ('fast = "BUBBLE"\n', "", "第 1 队（Team A）第 1 只：缺少 fast"),
        ('season = "pvpoke"', 'season = "pvpoke"\n[rules]\ntimeout = "draw"', "不认识的规则参数 timeout"),
        ('season = "pvpoke"', 'season = "pvpoke"\n[rules]\ntimeout_result = "win"',
         "规则参数 timeout_result 要写 'draw' / 'more_remaining' / 'rating'"),
        ('season = "pvpoke"', 'season = "pvpoke"\n[rules]\nswitch_cooldown_ms = 1.5',
         "规则参数 switch_cooldown_ms 要写 整数"),
        ('season = "pvpoke"', 'season = "pvpoke"\n[rules]\nmega_move_bonus = [1, 1, 1, 1]',
         "规则参数 mega_move_bonus 不能在配置文件里改"),
        ('season = "pvpoke"', 'season = "pvpoke"\n[policy]\nswitch_below = "low"', "策略参数 switch_below 要写 数字"),
        ('season = "pvpoke"', 'season = "pvpoke"\n[policy.moves]\nbait = true', "不认识的策略参数 moves.bait"),
        ('season = "pvpoke"', 'season = "pvpoke"\n[policy]\nmoves = 1', "策略参数 moves 要写成表"),
        ('name = "Team B"', 'name = "Team B"\n[team.policy]\nswitching = "always"',
         "第 2 队（Team B）：策略参数 switching 要写 'threshold' / 'never'"),
    ],
)
def test_bad_config_file(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_team_battle_config(_variant(tmp_path, old, new))


def test_team_count(tmp_path: Path) -> None:
    one_team = EXAMPLE_TEXT[: EXAMPLE_TEXT.index('[[team]]\nname = "Team B"')]
    with pytest.raises(ConfigError, match=r"要正好写两队（\[\[team\]\]），得到 1"):
        load_team_battle_config(_write(tmp_path, one_team))
    team_b = EXAMPLE_TEXT[EXAMPLE_TEXT.index('[[team]]\nname = "Team B"'):]
    three_teams = EXAMPLE_TEXT + "\n" + team_b.replace("Team B", "Team C")
    with pytest.raises(ConfigError, match="得到 3"):
        load_team_battle_config(_write(tmp_path, three_teams))


def test_team_size(tmp_path: Path) -> None:
    """每队要正好 BattleRules.max_team_size 只（默认 3）。"""
    two = EXAMPLE_TEXT.replace(
        '[[team.member]]\nspecies = "registeel"\nfast = "LOCK_ON"\ncharged = ["FOCUS_BLAST", "ZAP_CANNON"]\n', ""
    )
    with pytest.raises(ConfigError, match=r"第 1 队（Team A）：每队要正好 3 只（\[\[team.member\]\]），得到 2"):
        load_team_battle_config(_write(tmp_path, two))
    # 规则改成每队 2 只时，两队都要是 2 只
    two_rule = two.replace('season = "pvpoke"', 'season = "pvpoke"\n[rules]\nmax_team_size = 2')
    with pytest.raises(ConfigError, match="第 2 队（Team B）：每队要正好 2 只"):
        load_team_battle_config(_write(tmp_path, two_rule))


def test_bad_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="不是合法的 TOML"):
        load_team_battle_config(_write(tmp_path, EXAMPLE_TEXT + "\n[[team]\n"))


def test_same_species_twice(tmp_path: Path) -> None:
    """同一种宝可梦不能带两只：按图鉴编号判断，暗影也算同一种。"""
    path = _variant(
        tmp_path,
        'species = "medicham"\nfast = "COUNTER"\ncharged = ["ICE_PUNCH", "PSYCHIC"]',
        'species = "registeel_shadow"\nfast = "LOCK_ON"\ncharged = ["FOCUS_BLAST", "ZAP_CANNON"]',
    )
    config = load_team_battle_config(path)
    with pytest.raises(ConfigError, match="Team A：同一种宝可梦不能带两只（图鉴编号 #379 相同.*registeel_shadow、registeel"):
        prepare_team_battle(config)


def test_two_megas(tmp_path: Path) -> None:
    text = EXAMPLE_TEXT.replace('species = "swampert"', 'species = "swampert_mega"', 1).replace(
        'species = "altaria"', 'species = "altaria_mega"', 1
    )
    config = load_team_battle_config(_write(tmp_path, text))
    with pytest.raises(ConfigError, match="Team B：每队最多 1 只 Mega.*swampert_mega、altaria_mega"):
        prepare_team_battle(config)


def test_unknown_species(tmp_path: Path) -> None:
    config = load_team_battle_config(_variant(tmp_path, 'species = "medicham"', 'species = "medichamm"'))
    with pytest.raises(ConfigError, match="Team A 第 2 只（medichamm）：找不到宝可梦：medichamm"):
        prepare_team_battle(config)


def test_duplicate_labels_in_a_team(tmp_path: Path) -> None:
    text = EXAMPLE_TEXT.replace('species = "azumarill"', 'species = "azumarill"\nlabel = "X"', 1).replace(
        'species = "medicham"', 'species = "medicham"\nlabel = "X"', 1
    )
    with pytest.raises(ConfigError, match="Team A 里有重名的 X"):
        prepare_team_battle(load_team_battle_config(_write(tmp_path, text)))
