"""一方的队伍：成员、在场的是哪只、全队共用的盾。

1v1 就是每队一只：Team((azumarill,), shields=2)。
盾属于队伍而不是单只宝可梦：3v3 里全队共用 2 个盾（docs/mechanics.md 6.1、13.4）。

队伍的状态只由 battle 模块修改；策略（policy）只读。
"""

from dataclasses import dataclass

from pogo_sim.combatant import Combatant


@dataclass
class Team:
    members: tuple[Combatant, ...]  # 按出场顺序：第一只是首发
    shields: int  # 全队剩余的盾
    active: int = 0  # 在场的是 members 里的第几只

    def __post_init__(self) -> None:
        if not self.members:
            raise ValueError("队伍里至少要有一只宝可梦")
        sides = {member.index for member in self.members}
        if len(sides) != 1:
            raise ValueError(f"队伍成员必须属于同一方，得到 Combatant.index {sorted(sides)}")
        if not 0 <= self.active < len(self.members):
            raise ValueError(f"active 必须是 0 到 {len(self.members) - 1}，得到 {self.active}")

    @property
    def index(self) -> int:
        """哪一方（0 或 1），和成员的 Combatant.index 相同。"""
        return self.members[0].index

    @property
    def active_member(self) -> Combatant:
        """在场的那只。"""
        return self.members[self.active]

    @property
    def remaining(self) -> int:
        """还没倒下的只数。"""
        return sum(1 for member in self.members if not member.is_fainted)

    @property
    def is_defeated(self) -> bool:
        """全队都倒下了。"""
        return self.remaining == 0
