"""队伍结构（3v3-a）：盾属于队伍，策略看到双方的队伍；1v1 就是每队一只。

换人还没实现（3v3-b），所以多于一只的队伍现在只能建，不能拿去对战。
"""

import pytest

from pogo_sim.battle import Battle
from pogo_sim.combatant import Combatant, league_build, make_combatant
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.policy import BattleView, ScriptedCharged, ScriptedPolicy
from pogo_sim.team import Team


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _great_league(gm: GameMaster, index: int, species: str, fast: str, charged: tuple[str, ...]) -> Combatant:
    return make_combatant(gm, league_build(gm, species, 1500, fast, charged), index)


def _three(gm: GameMaster, index: int) -> tuple[Combatant, ...]:
    return (
        _great_league(gm, index, "azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH")),
        _great_league(gm, index, "medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC")),
        _great_league(gm, index, "registeel", "LOCK_ON", ("FOCUS_BLAST", "ZAP_CANNON")),
    )


def test_team_basics(gm: GameMaster) -> None:
    members = _three(gm, 1)
    team = Team(members, shields=2)
    assert team.index == 1
    assert team.active == 0 and team.active_member is members[0]  # 第一只是首发
    assert team.remaining == 3 and not team.is_defeated

    members[0].hp = 0
    members[2].hp = 0
    assert team.remaining == 1 and not team.is_defeated
    members[1].hp = 0
    assert team.is_defeated


def test_team_rejects_bad_input(gm: GameMaster) -> None:
    with pytest.raises(ValueError, match="至少要有一只"):
        Team((), shields=2)
    mixed = (_three(gm, 0)[0], _three(gm, 1)[1])
    with pytest.raises(ValueError, match="同一方"):
        Team(mixed, shields=2)
    with pytest.raises(ValueError, match="active"):
        Team(_three(gm, 0), shields=2, active=3)


def test_view_shows_active_members_and_teams(gm: GameMaster) -> None:
    mine, theirs = Team(_three(gm, 0), shields=1, active=2), Team(_three(gm, 1), shields=2)
    view = BattleView(turn=1, my_team=mine, opponent_team=theirs)
    assert view.me is mine.members[2]
    assert view.opponent is theirs.members[0]
    assert (view.my_team.shields, view.opponent_team.shields) == (1, 2)


def test_shields_are_spent_from_the_team(gm: GameMaster) -> None:
    """开盾扣的是队伍的盾。"""
    azumarill = _great_league(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM", "PLAY_ROUGH"))
    medicham = _great_league(gm, 1, "medicham", "COUNTER", ("ICE_PUNCH", "PSYCHIC"))
    azumarill.energy = 100
    teams = (Team((azumarill,), shields=0), Team((medicham,), shields=2))
    policies = (
        ScriptedPolicy(charged={1: ScriptedCharged(1, "ICE_BEAM")}),
        ScriptedPolicy(shields={1: True}),
    )
    battle = Battle(teams, policies)
    battle.play_turn()
    assert teams[1].shields == 1
    assert battle.snapshots[0].sides[1].shields == 1


def test_battle_checks_teams(gm: GameMaster) -> None:
    a = _great_league(gm, 0, "azumarill", "BUBBLE", ("ICE_BEAM",))
    b = _great_league(gm, 1, "medicham", "COUNTER", ("ICE_PUNCH",))
    policies = (ScriptedPolicy(), ScriptedPolicy())

    with pytest.raises(ValueError, match="第 0 方和第 1 方"):
        Battle((Team((b,), 0), Team((a,), 0)), policies)
    with pytest.raises(ValueError, match="盾数必须是 0 到 2"):
        Battle((Team((a,), 3), Team((b,), 0)), policies)
    # 换人在 3v3-b 实现，在那之前多于一只的队伍不能对战
    with pytest.raises(NotImplementedError, match="3v3-b"):
        Battle((Team(_three(gm, 0), 2), Team((b,), 0)), policies)
