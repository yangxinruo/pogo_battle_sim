"""对战报告的文字部分：双方配置、结果。时间线本身见 timeline.format_timeline。

和时间线一样，标签用英文（以后在界面层翻译）；build.notes 是建立配置时写的中文说明，原样输出。

用法（teams 是双方的队伍，见 team.Team）：
    print(format_setup(teams))   # 要在对战开始前调用：盾数、HP 会在对战中变化
    result = Battle(teams, policies).run()
    print(format_result(result, (a.name, b.name)))
    print(format_timeline(result.events, (a.name, b.name), show_decisions=True))
"""

import textwrap
from collections.abc import Sequence

from pogo_sim.battle import BattleResult
from pogo_sim.combatant import Combatant
from pogo_sim.team import Team

# 说明文字前的缩进
_INDENT = "    "


def format_combatant(combatant: Combatant, shields: int | None = None) -> str:
    """一只宝可梦的配置，几行文字。

    shields 是它所在队伍的盾数（盾属于队伍）；给了就写在第一行末尾。
    盾数和 HP 都是调用时的值，所以要在对战开始前调用。
    """
    build = combatant.build
    ivs = build.ivs
    first = (
        f"[{combatant.index}] {combatant.name}  CP {combatant.cp}  level {build.level:g}"
        f"  IV {ivs.atk}/{ivs.def_}/{ivs.hp}"
    )
    if combatant.mega_level is not None:
        first += f"  Mega level {combatant.mega_level}"
    if shields is not None:
        first += f"  shields {shields}"

    stats = combatant.stats
    charged = ", ".join(move.move_id for move in combatant.charged_moves)
    lines = [
        first,
        f"{_INDENT}HP {stats.hp}  atk {stats.atk:.2f}  def {stats.def_:.2f}",
        f"{_INDENT}fast {combatant.fast_move.move_id}  charged {charged}",
    ]
    if build.notes:
        lines.append(f"{_INDENT}build notes:")
        lines.extend(f"{_INDENT}  {note}" for note in build.notes)
    return "\n".join(lines)


def format_team(team: Team) -> str:
    """一方的配置。每队一只（1v1）时就是那一只；多于一只时先写全队的盾，再按出场顺序写每一只。"""
    if len(team.members) == 1:
        return format_combatant(team.members[0], team.shields)
    lines = [f"[{team.index}] team  shields {team.shields}"]
    for slot, member in enumerate(team.members):
        role = "lead" if slot == 0 else f"bench {slot}"
        lines.append(textwrap.indent(f"{role}: {format_combatant(member)}", _INDENT))
    return "\n".join(lines)


def format_setup(teams: Sequence[Team]) -> str:
    """双方的配置，中间空一行。要在对战开始前调用。"""
    return "\n\n".join(format_team(team) for team in teams)


def format_result(result: BattleResult, names: tuple[str, str]) -> str:
    """一行结果：谁赢、对战评分、剩余 HP（1v1）或剩余只数（3v3）、回合数。

    names 是双方的名字（1v1 用宝可梦名，3v3 用队伍名）。
    对战评分是本项目的口径（battle.team_rating，每队一只时就是 PvPoke 的评分），不是游戏规则。
    回合数不含大招暂停的时间，所以不换算成秒。
    """
    if result.winner is None:
        outcome = "Draw"
    else:
        outcome = f"{names[result.winner]} wins"
    last = result.snapshots[-1].sides if result.snapshots else None
    hp_text = ""
    if last is not None and len(last[0].member_hp) > 1:
        hp_text = (
            f", Pokemon left {result.remaining[0]} vs {result.remaining[1]}"
            f", shields left {result.shields_left[0]} vs {result.shields_left[1]}"
        )
    elif last is not None:
        hp_text = f", HP left {last[0].hp} vs {last[1].hp}"
    timeout = " (time limit reached)" if result.timed_out else ""
    return (
        f"{outcome}: rating {result.ratings[0]} vs {result.ratings[1]}{hp_text}, "
        f"{result.turns} turns{timeout}"
    )
