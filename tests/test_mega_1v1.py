"""第 2 步的完整流程：覆盖文件里的 Mega 雪妖女 → 按赛季规则建配置 → 简单规则策略 1v1 → 文字报告。

引擎本身（Mega 专属招式加成、Mega 带三个大招的对战）已经和 PvPoke 核对过
（tests/test_damage.py、tests/test_battle_pvpoke.py 的 mewtwo_mega_x）。这里检查的是各部分接起来以后：
配置说明进了报告、第三个大招真的被用上、伤害吃到了 Mega 加成。
结果数值来自本项目自己的引擎，不是 PvPoke；策略改动后如果变了，要确认变化合理再更新。
"""

from dataclasses import replace

import pytest

from pogo_sim.battle import Battle, BattleResult
from pogo_sim.combatant import Combatant, league_build, make_combatant
from pogo_sim.custom import CUSTOM_DATA_DIR
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.report import format_combatant, format_result, format_setup
from pogo_sim.season import season_build
from pogo_sim.simple_policy import SimplePolicy
from pogo_sim.team import Team
from pogo_sim.timeline import MoveEvent, SideSnapshot, TurnSnapshot, format_timeline

MEGA_FROSLASS_FILE = CUSTOM_DATA_DIR / "mega_froslass.toml"
FROSLASS_MOVES = ("AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS")


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster(custom_files=[MEGA_FROSLASS_FILE])


def _froslass_vs_azumarill(gm: GameMaster) -> tuple[Team, Team]:
    """各 2 盾。"""
    froslass = make_combatant(gm, season_build(gm, "froslass_mega", 1500, "POWDER_SNOW", FROSLASS_MOVES), 0)
    azumarill = make_combatant(gm, season_build(gm, "azumarill", 1500, "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")), 1)
    return Team((froslass,), shields=2), Team((azumarill,), shields=2)


def test_setup_shows_build_and_notes(gm: GameMaster) -> None:
    teams = _froslass_vs_azumarill(gm)
    froslass = teams[0].active_member
    assert format_combatant(froslass, shields=2).splitlines() == [
        "[0] Froslass (Mega)  CP 1498  level 14.5  IV 4/15/15  Mega level 4  shields 2",
        f"    HP 95  atk {froslass.stats.atk:.2f}  def {froslass.stats.def_:.2f}",
        "    fast POWDER_SNOW  charged AVALANCHE, SHADOW_BALL, AVALANCHE_PLUS",
        "    build notes:",
        *(f"      {note}" for note in froslass.build.notes),
    ]
    setup = format_setup(teams)
    assert "\n\n[1] Azumarill  CP 1499  level 45.5  IV 0/15/15  shields 2\n" in setup
    assert "      等级 45.5：CP 不超过 1500 的最高等级（CP 1499）" in setup


def test_build_without_notes_has_no_notes_section(gm: GameMaster) -> None:
    medicham = make_combatant(gm, league_build(gm, "medicham", 1500, "COUNTER", ("ICE_PUNCH", "PSYCHIC")), 1)
    text = format_combatant(medicham, shields=1)
    assert "build notes" not in text
    assert "Mega level" not in text  # 不是 Mega
    assert text.splitlines()[0].endswith("shields 1")


def test_mega_froslass_1v1(gm: GameMaster) -> None:
    teams = _froslass_vs_azumarill(gm)
    froslass, azumarill = teams[0].active_member, teams[1].active_member
    names = (froslass.name, azumarill.name)
    # 对战前记下双方状态，用来算"没被挡下时应有的伤害"（对战中能力等级不变：这几个招式都没有能力变化）
    froslass_side, azumarill_side = froslass.damage_side(), azumarill.damage_side()

    result = Battle(teams, (SimplePolicy(), SimplePolicy())).run()

    # 本项目引擎的结果（回归用，不是 PvPoke 的结果）
    assert format_result(result, names) == (
        "Froslass (Mega) wins: rating 578 vs 421, HP left 15 vs 0, 49 turns"
    )

    # 第三个大招被用上了：两次骗盾（被挡下，1 点伤害），最后一次收尾
    avalanche_plus = [
        e for e in result.events
        if isinstance(e, MoveEvent) and e.actor == 0 and e.move_id == "AVALANCHE_PLUS"
    ]
    assert [(e.turn, e.shielded, e.damage) for e in avalanche_plus] == [
        (15, True, 1),
        (30, True, 1),
        (49, False, 52),
    ]

    # 收尾的 52 点吃到了 Mega 等级 4 的 1.3 倍加成；Mega 等级 1 没有加成，只有 40 点
    move = gm.get_move("AVALANCHE_PLUS")
    assert calculate_damage(move, froslass_side, azumarill_side) == 52
    assert calculate_damage(move, replace(froslass_side, mega_level=1), azumarill_side) == 40

    timeline = format_timeline(result.events, names, show_decisions=True)
    assert timeline.splitlines()[-1] == "T  49  Azumarill       FAINTS"


def test_format_result_draw_and_timeout() -> None:
    snapshot = SideSnapshot(hp=10, energy=0, cooldown=0, atk_stage=0, def_stage=0, shields=0)
    result = BattleResult(
        winner=None,
        ratings=(500, 500),
        turns=480,
        elapsed_ms=240_500,
        timed_out=True,
        remaining=(1, 1),
        shields_left=(0, 0),
        events=[],
        snapshots=[TurnSnapshot(480, (snapshot, snapshot))],
    )
    assert format_result(result, ("A", "B")) == (
        "Draw: rating 500 vs 500, HP left 10 vs 10, 480 turns (time limit reached)"
    )
