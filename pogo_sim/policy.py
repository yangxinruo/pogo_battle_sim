"""策略：替一方做决定（这回合出什么招、要不要开盾）。

引擎（battle.py）只负责规则，从不自己做决定；每次需要决定时都问双方的策略。
每个决定都要带一句原因，原因会原样写进时间线，方便看出输赢是哪些选择造成的。

第 3b 步只有剧本策略（ScriptedPolicy）：按事先给定的动作表行动，用来逐回合对照 PvPoke。
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from pogo_sim.combatant import Combatant
from pogo_sim.gamemaster import Move


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


Action = FastAction | ChargedAction


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


@dataclass(frozen=True)
class ShieldDecision:
    use_shield: bool
    reason: str


@dataclass(frozen=True)
class BattleView:
    """策略做决定时能看到的信息。me / opponent 是对战状态本身，只读，不要修改。"""

    turn: int
    me: Combatant
    opponent: Combatant


class Policy(Protocol):
    def decide_action(self, view: BattleView) -> Decision:
        """本回合可以行动时调用：返回快招或某个能量足够的大招。"""
        ...

    def decide_shield(self, view: BattleView, incoming: Move, damage: int) -> ShieldDecision:
        """对手的大招打过来、自己还有盾时调用。damage 是不开盾时会受到的伤害。"""
        ...


@dataclass(frozen=True)
class ScriptedCharged:
    """剧本里的一次大招：在第 turn 回合放 move_id。"""

    turn: int
    move_id: str
    apply_effect: bool | None = None  # 见 ChargedAction.force_effect


@dataclass
class ScriptedPolicy:
    """照剧本行动，和 PvPoke 沙盒模式（sandbox mode）的规则相同：

    - 剧本指定的回合放指定的大招（能量不够就改用快招，和 PvPoke 一样）；
    - 其他回合一律用快招；
    - 开盾：剧本里写了"对手第 N 回合的大招要挡"就挡，没写就不挡。

    注意：引擎只在这只宝可梦"可以行动"的回合（冷却为 0、不是大招后的空回合）才问策略。
    排在其他回合的大招永远不会被用到，而且不会报错（PvPoke 沙盒模式也一样）。
    跑完之后可以用 unused_charged() 检查有没有这种情况。
    """

    charged: Mapping[int, ScriptedCharged] = field(default_factory=dict)  # 键是回合
    shields: Mapping[int, bool] = field(default_factory=dict)  # 键是对手大招所在的回合
    _asked_turns: set[int] = field(default_factory=set, init=False, repr=False)

    def unused_charged(self) -> list[ScriptedCharged]:
        """剧本里那些从没被问到的大招（排在了不能行动的回合）。"""
        return [step for turn, step in sorted(self.charged.items()) if turn not in self._asked_turns]

    def decide_action(self, view: BattleView) -> Decision:
        self._asked_turns.add(view.turn)
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
