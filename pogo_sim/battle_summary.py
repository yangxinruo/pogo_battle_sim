"""一场对战的概括（第 4 步 4b，docs/mechanics.md 14.4）：对位分段，以及过程图的招式带。

都从 BattleResult 的事件和逐回合快照算出来，不重新打。

对位分段：在场的两只不变的一段时间算一段，任一方换人（主动、0 回合、倒下后）就开始新的一段。
- 按事件发生的顺序切：换人之前结算的招式算前一段。例如大招后的空回合里先结算的漂浮快招，
  打的是换下去的那只，算前一段；所以前一段的最后一回合可能就是后一段的第一回合。
- 同一回合、还没有招式结算时的几次换人（例如双方同时倒下后各自换上）只算一次切换。
- 倒下算在那一只在场的那一段：换下去的那只先被漂浮快招打倒时（13.5 的特例），
  倒下的事件记在换人之后，但仍算前一段。
- 每一段记双方在场那只开始和结束时的 HP、能量，快招次数，放的大招，造成的伤害，用掉的盾，
  以及这一段是怎么结束的（谁倒下了、谁换人了）。

招式带（过程图上每方一条）：快招是一段时间（从决定的回合到结算的回合），大招、换人、倒下是某一回合上的标记。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pogo_sim.battle import BattleResult
from pogo_sim.gamemaster import GameMaster
from pogo_sim.timeline import CancelledEvent, DecisionEvent, Event, FaintEvent, MoveEvent, SwitchEvent

# ---- 对位分段 ----


@dataclass(frozen=True)
class ChargedUse:
    """一段里放的一个大招。"""

    turn: int
    move_id: str
    damage: int  # 被挡下时为 1
    shielded: bool


@dataclass(frozen=True)
class SegmentSide:
    """一段里一方在场那只的情况。"""

    slot: int  # 队伍里的第几只
    hp_start: int  # 这一段开始之前的 HP
    hp_end: int  # 这一段最后一回合结束时的 HP
    energy_start: int
    energy_end: int
    fast_moves: int  # 快招结算了几次
    charged: tuple[ChargedUse, ...]
    damage_dealt: int  # 造成的伤害（被挡下的算 1）
    shields_used: int  # 开盾挡下对方大招的次数


@dataclass(frozen=True)
class Segment:
    start_turn: int
    end_turn: int
    sides: tuple[SegmentSide, SegmentSide]
    fainted: tuple[int, ...]  # 这一段里倒下的是哪几方（在场的那只）
    # 结束这一段的换人：(哪一方, 种类 "switch" / "zero_turn")。倒下后的换人不列（已经由 fainted 说明）。
    switched: tuple[tuple[int, str], ...]


@dataclass
class _OpenSegment:
    start_turn: int
    slots: list[int]
    plays: list[Event] = field(default_factory=list)  # 招式、作废、倒下（不含决定）
    opened_by: list[SwitchEvent] = field(default_factory=list)


def battle_segments(
    result: BattleResult,
    start_hp: Sequence[Sequence[int]],
    start_energy: Sequence[Sequence[int]] | None = None,
) -> list[Segment]:
    """把一场对战切成对位分段（见模块说明）。

    start_hp[方][第几只]：第 1 回合之前的 HP（一般就是最大 HP）；start_energy 同样，不给时都是 0。
    """
    snapshots = {snapshot.turn: snapshot for snapshot in result.snapshots}

    def before(turn: int, side: int, slot: int) -> tuple[int, int]:
        """第 turn 回合开始之前这一只的 HP 和能量。"""
        if turn - 1 in snapshots:
            snapshot = snapshots[turn - 1].sides[side]
            return snapshot.member_hp[slot], snapshot.member_energy[slot]
        return start_hp[side][slot], start_energy[side][slot] if start_energy is not None else 0

    def after(turn: int, side: int, slot: int) -> tuple[int, int]:
        snapshot = snapshots[turn].sides[side]
        return snapshot.member_hp[slot], snapshot.member_energy[slot]

    opened: list[_OpenSegment] = [_OpenSegment(1, [0, 0])]  # 首发是队伍里的第 0 只
    for event in result.events:
        current = opened[-1]
        if isinstance(event, SwitchEvent):
            if current.plays or event.turn != current.start_turn:
                current = _OpenSegment(event.turn, list(current.slots))
                opened.append(current)
            current.slots[event.actor] = event.to_slot
            current.opened_by.append(event)
        elif isinstance(event, FaintEvent):
            # 算在倒下的那只最后在场的那一段
            owner = next(s for s in reversed(opened) if s.slots[event.actor] == event.slot)
            owner.plays.append(event)
        elif not isinstance(event, DecisionEvent):
            current.plays.append(event)

    segments = []
    for i, segment in enumerate(opened):
        following = opened[i + 1] if i + 1 < len(opened) else None
        last_play = max((event.turn for event in segment.plays), default=segment.start_turn)
        end_turn = following.start_turn - 1 if following else result.turns
        end_turn = max(end_turn, last_play, segment.start_turn)
        sides = tuple(
            _segment_side(segment, side, before(segment.start_turn, side, segment.slots[side]),
                          after(end_turn, side, segment.slots[side]))
            for side in (0, 1)
        )
        fainted = tuple(
            event.actor for event in segment.plays
            if isinstance(event, FaintEvent) and event.slot == segment.slots[event.actor]
        )
        switched = tuple(
            (event.actor, event.kind) for event in (following.opened_by if following else [])
            if event.kind != "replacement"
        )
        segments.append(Segment(segment.start_turn, end_turn, (sides[0], sides[1]), fainted, switched))
    return segments


def _segment_side(
    segment: _OpenSegment, side: int, start: tuple[int, int], end: tuple[int, int]
) -> SegmentSide:
    moves = [event for event in segment.plays if isinstance(event, MoveEvent)]
    mine = [event for event in moves if event.actor == side]
    return SegmentSide(
        slot=segment.slots[side],
        hp_start=start[0],
        hp_end=end[0],
        energy_start=start[1],
        energy_end=end[1],
        fast_moves=sum(1 for event in mine if not event.is_charged),
        charged=tuple(
            ChargedUse(event.turn, event.move_id, event.damage, event.shielded) for event in mine if event.is_charged
        ),
        damage_dealt=sum(event.damage for event in mine),
        shields_used=sum(1 for event in moves if event.actor != side and event.shielded),
    )


# ---- 招式带 ----


@dataclass(frozen=True)
class LaneItem:
    """过程图上一方招式带里的一项。

    kind："fast"（快招，start_turn 到 end_turn）/ "cancelled"（排了队但作废的快招或大招）/
    "charged"（大招）/ "switch"（换人，slot 是换上的那只）/ "faint"（倒下）。
    除了快招和作废的快招，start_turn 和 end_turn 相同。
    """

    kind: str
    start_turn: int
    end_turn: int
    slot: int  # 出招 / 倒下 / 换上的是第几只
    move_id: str = ""
    damage: int = 0
    shielded: bool = False
    target_slot: int | None = None  # 招式打的是对方的第几只
    from_slot: int | None = None  # 换人：换下去的那只
    switch_kind: str = ""  # 换人："switch" / "zero_turn" / "replacement"


def lane_items(result: BattleResult, gm: GameMaster) -> tuple[list[LaneItem], list[LaneItem]]:
    """双方的招式带，按事件发生的顺序。

    快招从决定它的那一回合画到结算的那一回合；找不到决定时（不应该发生），按招式的回合数往前推。
    """
    lanes: tuple[list[LaneItem], list[LaneItem]] = ([], [])
    fast_decided: dict[int, int] = {}  # 每方最近一次决定放快招的回合
    for event in result.events:
        match event:
            case DecisionEvent(action="fast"):
                fast_decided[event.actor] = event.turn
            case MoveEvent(is_charged=False):
                start = fast_decided.pop(event.actor, event.turn - gm.get_move(event.move_id).turns + 1)
                lanes[event.actor].append(LaneItem(
                    "fast", start, event.turn, event.actor_slot, event.move_id, event.damage,
                    target_slot=event.target_slot,
                ))
            case MoveEvent(is_charged=True):
                lanes[event.actor].append(LaneItem(
                    "charged", event.turn, event.turn, event.actor_slot, event.move_id, event.damage,
                    event.shielded, target_slot=event.target_slot,
                ))
            case CancelledEvent():
                start = event.turn
                move = gm.moves.get(event.move_id)  # 作废的也可能是换人（move_id 是 "switch"）
                if move is not None and move.is_fast:  # 快招：从决定的回合画起
                    start = fast_decided.pop(event.actor, event.turn)
                lanes[event.actor].append(LaneItem("cancelled", start, event.turn, event.actor_slot, event.move_id))
            case SwitchEvent():
                lanes[event.actor].append(LaneItem(
                    "switch", event.turn, event.turn, event.to_slot,
                    from_slot=event.from_slot, switch_kind=event.kind,
                ))
            case FaintEvent():
                lanes[event.actor].append(LaneItem("faint", event.turn, event.turn, event.slot))
    return lanes
