"""对战时间线：结构化的事件记录，以及逐回合的状态快照。

事件和快照都是普通的 frozen dataclass，以后网页界面可以直接用；
format_timeline() 把它们排成一行一件事的文字日志（英文，方便以后在界面层翻译）。

事件里的 actor 是哪一方（0 或 1），*_slot 是这一方队伍里的第几只（Team.members 的下标）。
1v1 时 slot 都是 0。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pogo_sim.gamemaster import StatChange
from pogo_sim.team import Team


@dataclass(frozen=True)
class DecisionEvent:
    """一方做了决定（还没结算）。reason 来自策略。

    action："fast" / "charged" / "switch"（主动换人）/ "zero_turn_switch"（不花回合的换人）/
    "stay"（有不花回合的换人机会，但不换）/ "replacement"（倒下后换谁）/ "wait"（这一回合什么都不做）。
    """

    turn: int
    actor: int
    action: str
    move_id: str  # 快招 / 大招的招式 ID；换人时为空字符串
    reason: str
    actor_slot: int = 0
    switch_to: int | None = None  # 换人时换上第几只


@dataclass(frozen=True)
class EffectApplied:
    target: int  # 能力变化作用在哪一方身上
    change: StatChange


@dataclass(frozen=True)
class MoveEvent:
    """一次招式结算。"""

    turn: int
    actor: int
    move_id: str
    is_charged: bool
    damage: int  # 实际造成的伤害（被挡下时为 1）
    shielded: bool
    shield_reason: str | None  # 守方有盾时，策略给出的开/不开盾原因；没盾时为 None
    energy_after: int  # 攻方结算后的能量
    defender_hp_after: int
    effects: tuple[EffectApplied, ...]
    actor_slot: int = 0
    target_slot: int = 0  # 挨打的是对方队伍里的第几只
    charge: float = 1.0  # 大招的威力（蓄力比例）；模拟里都是 1，手动对战里玩家可以选


@dataclass(frozen=True)
class CancelledEvent:
    """一个已经排队的行动因为规则而作废（例如被大招打倒后，同回合的快招不生效）。"""

    turn: int
    actor: int
    move_id: str
    reason: str
    actor_slot: int = 0


@dataclass(frozen=True)
class FaintEvent:
    turn: int
    actor: int
    slot: int = 0


SwitchKind = Literal["switch", "zero_turn", "replacement"]


@dataclass(frozen=True)
class SwitchEvent:
    """一次换人结算。

    kind："switch"（主动换人，占用这一回合）/ "zero_turn"（不花回合的换人）/ "replacement"（倒下后换人）。
    换下去的那只如果已经倒下，不开始换人冷却（switch_timer_ms 不变）。
    """

    turn: int
    actor: int
    from_slot: int
    to_slot: int
    kind: SwitchKind
    switch_timer_ms: int  # 换完之后这一方的换人冷却
    wait_ms: int = 0  # 倒下后选人等了多久


Event = DecisionEvent | MoveEvent | CancelledEvent | FaintEvent | SwitchEvent


@dataclass(frozen=True)
class SideSnapshot:
    """一方在某一回合结算完之后的状态。前几项是在场那只的。"""

    hp: int
    energy: int
    cooldown: int
    atk_stage: int
    def_stage: int
    shields: int  # 全队的盾
    active: int = 0  # 在场的是第几只
    switch_timer_ms: int = 0
    member_hp: tuple[int, ...] = ()  # 全队每只的 HP（按 Team.members 的顺序）
    member_energy: tuple[int, ...] = ()


@dataclass(frozen=True)
class TurnSnapshot:
    """某一回合结算完之后双方的状态。"""

    turn: int
    sides: tuple[SideSnapshot, SideSnapshot]
    elapsed_ms: int = 0  # 这一回合结束时的对战时间（同 BattleResult.elapsed_ms 的口径）


# 双方的名字：1v1 时每方一个字符串；3v3 时每方是队伍成员的名字（按 Team.members 的顺序）。
Names = tuple[str | Sequence[str], str | Sequence[str]]


def team_names(teams: Sequence[Team]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """从双方的队伍取出成员名字，给 format_timeline 用。"""
    a, b = (tuple(member.name for member in team.members) for team in teams)
    return a, b


def _name(names: Names, side: int, slot: int) -> str:
    entry = names[side]
    return entry if isinstance(entry, str) else entry[slot]


_NAME_WIDTH = 16


def _column(name: str) -> str:
    """行首的名字一栏：补齐到 16 个字符；更长的名字后面至少空两格，免得和后面的字连在一起。"""
    return name.ljust(_NAME_WIDTH) if len(name) < _NAME_WIDTH else name + "  "


def _format_effects(effects: tuple[EffectApplied, ...], names: Names, event: MoveEvent) -> str:
    parts = []
    for effect in effects:
        stats = []
        if effect.change.atk:
            stats.append(f"atk {effect.change.atk:+d}")
        if effect.change.def_:
            stats.append(f"def {effect.change.def_:+d}")
        slot = event.actor_slot if effect.target == event.actor else event.target_slot
        parts.append(f"{_name(names, effect.target, slot)} {' '.join(stats)}")
    return "; ".join(parts)


_SWITCH_TEXT = {
    "switch": "switches to",
    "zero_turn": "switches (0 turns) to",
    "replacement": "sends in",
}


def event_actor(event: Event) -> tuple[int, int]:
    """事件是哪一方的第几只（时间线里这一行开头的名字）。"""
    match event:
        case FaintEvent():
            return event.actor, event.slot
        case SwitchEvent():
            return event.actor, event.from_slot
        case DecisionEvent() | MoveEvent() | CancelledEvent():
            return event.actor, event.actor_slot
    raise TypeError(f"不认识的事件：{event!r}")


def describe_event(event: Event, names: Names) -> str:
    """一个事件的文字，不带开头的回合数和名字（网页按回合、按方排表时用）。"""
    match event:
        case DecisionEvent():
            if event.switch_to is not None:
                target = _name(names, event.actor, event.switch_to)
                return f"decides {event.action} -> {target}  ({event.reason})"
            if event.action == "stay":
                return f"decides not to switch  ({event.reason})"
            if event.action == "wait":
                return f"decides to wait  ({event.reason})"
            return f"decides {event.action} {event.move_id}  ({event.reason})"
        case MoveEvent():
            kind = "CHARGED" if event.is_charged else "fast"
            charge = f" at {event.charge:.0%}" if event.charge < 1 else ""
            line = (
                f"{kind} {event.move_id}{charge} -> {event.damage} dmg"
                f"{' (shielded)' if event.shielded else ''}"
                f", {_name(names, 1 - event.actor, event.target_slot)} HP {event.defender_hp_after}"
                f", energy {event.energy_after}"
            )
            if event.shield_reason is not None:
                line += f"  [shield: {event.shield_reason}]"
            if event.effects:
                line += f"  [effects: {_format_effects(event.effects, names, event)}]"
            return line
        case CancelledEvent():
            return f"{event.move_id} cancelled ({event.reason})"
        case FaintEvent():
            return "FAINTS"
        case SwitchEvent():
            line = f"{_SWITCH_TEXT[event.kind]} {_name(names, event.actor, event.to_slot)}"
            details = []
            if event.wait_ms:
                details.append(f"waited {event.wait_ms / 1000:g}s")
            if event.switch_timer_ms:
                details.append(f"switch timer {event.switch_timer_ms / 1000:g}s")
            if details:
                line += f"  ({', '.join(details)})"
            return line
    raise TypeError(f"不认识的事件：{event!r}")


def format_event(event: Event, names: Names) -> str:
    """一行文字描述一个事件：回合数、名字、describe_event 的文字。names 见 Names。"""
    side, slot = event_actor(event)
    return f"T{event.turn:>4}  {_column(_name(names, side, slot))}{describe_event(event, names)}"


def format_timeline(events: list[Event], names: Names, show_decisions: bool = False) -> str:
    """把整场的事件排成文字日志。默认不显示"决定"事件（剧本对局里它们没有信息量）。"""
    lines = [
        format_event(event, names)
        for event in events
        if show_decisions or not isinstance(event, DecisionEvent)
    ]
    return "\n".join(lines)
