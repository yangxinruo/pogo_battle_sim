"""对战时间线：结构化的事件记录，以及逐回合的状态快照。

事件和快照都是普通的 frozen dataclass，以后网页界面可以直接用；
format_timeline() 把它们排成一行一件事的文字日志（英文，方便以后在界面层翻译）。
"""

from dataclasses import dataclass

from pogo_sim.gamemaster import StatChange


@dataclass(frozen=True)
class DecisionEvent:
    """一方做了决定（还没结算）。reason 来自策略。"""

    turn: int
    actor: int
    action: str  # "fast" 或 "charged"
    move_id: str
    reason: str


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


@dataclass(frozen=True)
class CancelledEvent:
    """一个已经排队的行动因为规则而作废（例如被大招打倒后，同回合的快招不生效）。"""

    turn: int
    actor: int
    move_id: str
    reason: str


@dataclass(frozen=True)
class FaintEvent:
    turn: int
    actor: int


Event = DecisionEvent | MoveEvent | CancelledEvent | FaintEvent


@dataclass(frozen=True)
class SideSnapshot:
    hp: int
    energy: int
    cooldown: int
    atk_stage: int
    def_stage: int
    shields: int


@dataclass(frozen=True)
class TurnSnapshot:
    """某一回合结算完之后双方的状态。"""

    turn: int
    sides: tuple[SideSnapshot, SideSnapshot]


def _format_effects(effects: tuple[EffectApplied, ...], names: tuple[str, str]) -> str:
    parts = []
    for effect in effects:
        stats = []
        if effect.change.atk:
            stats.append(f"atk {effect.change.atk:+d}")
        if effect.change.def_:
            stats.append(f"def {effect.change.def_:+d}")
        parts.append(f"{names[effect.target]} {' '.join(stats)}")
    return "; ".join(parts)


def format_event(event: Event, names: tuple[str, str]) -> str:
    """一行文字描述一个事件。names 是双方的名字（下标 0 / 1）。"""
    prefix = f"T{event.turn:>4}  {names[event.actor]:<16}"
    match event:
        case DecisionEvent():
            return f"{prefix}decides {event.action} {event.move_id}  ({event.reason})"
        case MoveEvent():
            kind = "CHARGED" if event.is_charged else "fast"
            line = (
                f"{prefix}{kind} {event.move_id} -> {event.damage} dmg"
                f"{' (shielded)' if event.shielded else ''}"
                f", {names[1 - event.actor]} HP {event.defender_hp_after}"
                f", energy {event.energy_after}"
            )
            if event.shield_reason is not None:
                line += f"  [shield: {event.shield_reason}]"
            if event.effects:
                line += f"  [effects: {_format_effects(event.effects, names)}]"
            return line
        case CancelledEvent():
            return f"{prefix}{event.move_id} cancelled ({event.reason})"
        case FaintEvent():
            return f"{prefix}FAINTS"
    raise TypeError(f"不认识的事件：{event!r}")


def format_timeline(events: list[Event], names: tuple[str, str], show_decisions: bool = False) -> str:
    """把整场的事件排成文字日志。默认不显示"决定"事件（剧本对局里它们没有信息量）。"""
    lines = [
        format_event(event, names)
        for event in events
        if show_decisions or not isinstance(event, DecisionEvent)
    ]
    return "\n".join(lines)
