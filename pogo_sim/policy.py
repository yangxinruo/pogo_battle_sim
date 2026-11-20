"""策略：替一方做决定（这回合出什么招、要不要开盾、换不换人、倒下后换谁）。

引擎（battle.py）只负责规则，从不自己做决定；每次需要决定时都问双方的策略。
每个决定都要带一句原因，原因会原样写进时间线，方便看出输赢是哪些选择造成的。

引擎会问策略四种问题（Policy）：
1. decide_action：可以行动的回合，出快招、放大招，还是换人。
2. decide_shield：对手的大招打过来、自己队伍还有盾时，开不开盾。
3. decide_zero_turn_switch：不花回合的换人机会（大招后的空回合等，见该方法的说明），换不换。
4. choose_replacement：在场的倒下了，换谁上、选人时等几秒。

这里的剧本策略（ScriptedPolicy）按事先给定的动作表行动，用来逐回合对照 PvPoke 和写单项测试。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from pogo_sim.combatant import Combatant
from pogo_sim.gamemaster import Move
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.team import Team


@dataclass(frozen=True)
class FastAction:
    """用快速技能。"""


@dataclass(frozen=True)
class ChargedAction:
    """放一个大招。

    force_effect：这次大招的概率性能力变化是否触发。None 表示按规则（BattleRules.chance_effects）决定；
    只有剧本策略会指定 True / False（复现 PvPoke 某一场的实际结果时需要）。
    必定触发的效果（概率 100%）不受这个字段影响。
    """

    move_id: str
    force_effect: bool | None = None


@dataclass(frozen=True)
class SwitchAction:
    """主动换人：换上队伍里的第 to 只（Team.members 的下标）。占用这一回合的行动。

    只有 BattleView.can_switch 为 True 时才能换（换人冷却为 0、后备里有没倒下的），否则引擎报错。
    """

    to: int


Action = FastAction | ChargedAction | SwitchAction


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


@dataclass(frozen=True)
class ShieldDecision:
    use_shield: bool
    reason: str


@dataclass(frozen=True)
class SwitchDecision:
    """不花回合的换人机会，换不换：to 是换上第几只，None 表示不换。"""

    to: int | None
    reason: str


@dataclass(frozen=True)
class Replacement:
    """在场的倒下后换谁上。

    wait_ms：选人时等多久（毫秒）。游戏里选人时计时照走，所以等待会消耗双方的换人冷却和对战时间
    （PvPoke 的困难 AI 会故意拖时间，等自己的换人冷却走完）。0 到 BattleRules.max_replacement_wait_ms。
    """

    to: int
    wait_ms: int
    reason: str


@dataclass(frozen=True)
class BattleView:
    """策略做决定时能看到的信息：双方的队伍。这些是对战状态本身，只读，不要修改。

    双方的全部状态都看得见（HP、能量、盾数、冷却、换人计时，以及后备的状态）——和 PvPoke 一样假设完全信息。
    盾数在队伍上：my_team.shields、opponent_team.shields。
    rules 是引擎正在用的规则，策略估算伤害时要用同一套。
    """

    turn: int
    my_team: Team
    opponent_team: Team
    rules: BattleRules = PVPOKE_COMPAT

    @property
    def me(self) -> Combatant:
        """自己在场的那只。"""
        return self.my_team.active_member

    @property
    def opponent(self) -> Combatant:
        """对手在场的那只。"""
        return self.opponent_team.active_member

    @property
    def can_switch(self) -> bool:
        """现在能不能主动换人：换人冷却为 0，而且后备里有没倒下的。"""
        return self.my_team.can_switch


class Policy(Protocol):
    def decide_action(self, view: BattleView) -> Decision:
        """本回合可以行动时调用：返回快招、某个能量足够的大招，或者换人（view.can_switch 时）。"""
        ...

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        """对手的大招打过来、自己队伍还有盾时调用。damage 是不开盾时会受到的伤害。"""
        ...

    def decide_zero_turn_switch(self, view: BattleView) -> SwitchDecision:
        """有不花回合的换人机会、而且 view.can_switch 时调用。两种情况：
        - 大招后的空回合（双方都可以，Q15）；
        - 对手倒下、正在换人的那一回合（BattleRules.switch_during_opponent_replacement 打开时）。
        """
        ...

    def choose_replacement(self, view: BattleView) -> Replacement:
        """自己在场的倒下了、后备还有时调用：换谁上。view.me 是倒下的那只。"""
        ...


def first_available(team: Team) -> int:
    """队伍里排在最前、没倒下、不在场的那只（倒下后的默认人选）。"""
    return team.bench_slots()[0]


@dataclass(frozen=True)
class ScriptedCharged:
    """剧本里的一次大招：在第 turn 回合放 move_id。"""

    turn: int
    move_id: str
    apply_effect: bool | None = None  # 见 ChargedAction.force_effect


@dataclass(frozen=True)
class ScriptedReplacement:
    """剧本里倒下后的换人：换上第 to 只，选人时等 wait_ms 毫秒。"""

    to: int
    wait_ms: int = 0


@dataclass
class ScriptedPolicy:
    """照剧本行动，和 PvPoke 沙盒模式（sandbox mode）的规则相同：

    - 剧本指定的回合放指定的大招（能量不够就改用快招，和 PvPoke 一样）；
    - 剧本指定的回合换人（switches）：普通回合是主动换人；大招后的空回合等不花回合的机会是 0 回合换人；
    - 其他回合一律用快招；
    - 开盾：剧本里写了"对手第 N 回合的大招要挡"就挡，没写就不挡；
    - 倒下后：剧本里写了这一回合换谁（replacements）就换谁，没写就换上队伍里排在最前的。

    注意：引擎只在这只宝可梦"可以行动"的回合才问策略。排在其他回合的大招或换人永远不会被用到，
    而且不会报错（PvPoke 沙盒模式也一样）。跑完之后可以用 unused_charged()、unused_switches() 检查。
    """

    charged: Mapping[int, ScriptedCharged] = field(default_factory=dict)  # 键是回合
    shields: Mapping[int, bool] = field(default_factory=dict)  # 键是对手大招所在的回合
    switches: Mapping[int, int] = field(default_factory=dict)  # 回合 → 换上第几只
    replacements: Mapping[int, ScriptedReplacement] = field(default_factory=dict)  # 换人的回合 → 换谁
    _asked_turns: set[int] = field(default_factory=set, init=False, repr=False)

    def unused_charged(self) -> list[ScriptedCharged]:
        """剧本里那些从没被问到的大招（排在了不能行动的回合）。"""
        return [step for turn, step in sorted(self.charged.items()) if turn not in self._asked_turns]

    def unused_switches(self) -> list[int]:
        """剧本里那些从没被问到的换人（的回合）。"""
        return [turn for turn in sorted(self.switches) if turn not in self._asked_turns]

    def decide_action(self, view: BattleView) -> Decision:
        self._asked_turns.add(view.turn)
        if view.turn in self.switches:
            to = self.switches[view.turn]
            return Decision(SwitchAction(to), f"script: switch on turn {view.turn}")

        planned = self.charged.get(view.turn)
        if planned is None:
            return Decision(FastAction(), "script: fast move (no charged move scheduled)")

        move = next((m for m in view.me.charged_moves if m.move_id == planned.move_id), None)
        if move is None:
            raise ValueError(f"剧本第 {view.turn} 回合的 {planned.move_id} 不是 {view.me.name} 的招式")
        if view.me.energy < move.energy_cost:
            return Decision(
                FastAction(),
                f"script: {move.move_id} scheduled but energy {view.me.energy} < {move.energy_cost}",
            )
        return Decision(
            ChargedAction(move.move_id, force_effect=planned.apply_effect),
            f"script: {move.move_id} scheduled on turn {view.turn}",
        )

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        if self.shields.get(view.turn, False):
            return ShieldDecision(True, f"script: shield turn {view.turn}")
        return ShieldDecision(False, f"script: no shield on turn {view.turn}")

    def decide_zero_turn_switch(self, view: BattleView) -> SwitchDecision:
        self._asked_turns.add(view.turn)
        if view.turn in self.switches:
            return SwitchDecision(self.switches[view.turn], f"script: 0-turn switch on turn {view.turn}")
        return SwitchDecision(None, "script: no switch scheduled")

    def choose_replacement(self, view: BattleView) -> Replacement:
        planned = self.replacements.get(view.turn)
        if planned is None:
            return Replacement(first_available(view.my_team), 0, "script: next in team order")
        return Replacement(planned.to, planned.wait_ms, f"script: replacement on turn {view.turn}")
