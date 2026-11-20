"""配招：一只宝可梦带的快招和大招，以及这些招式在不在它的招式池里。

招式池以 gamemaster（含覆盖文件）为准：
- 快招：fastMoves；
- 第 1、2 个大招：chargedMoves（含 eliteMoves 里的限定招式，PvPoke 的 chargedMoves 已经包括它们）；
- 第 3 个大招：只有带 extraChargedMoves 的 Mega 能带，只能从 extraChargedMoves 里选
  （combatant.check_charged_moves 检查，这里不重复）。

想试招式池外的招（例如正作里超梦会、GO 里不会的 Avalanche），有两种办法：
1. 覆盖文件里用 patch_pokemon 改招式池：适合"假设以后会加这个招"，所有对局都生效；
2. 对战配置（matchups.py）里给这一套配招写 outside_movepool = true：只对这一套生效，报告里会标出来。

招式本身的数值（例如每个赛季的平衡调整）用覆盖文件的 patch_moves 改，见 docs/mechanics.md 第 10 节。
"""

from dataclasses import dataclass

from pogo_sim.gamemaster import Species


@dataclass(frozen=True)
class Moveset:
    """一套配招：1 个快招，1 到 3 个大招（招式 ID，如 "PSYCHO_CUT"）。"""

    fast: str
    charged: tuple[str, ...]

    def describe(self) -> str:
        """例如 "PSYCHO_CUT / PSYSTRIKE, ICE_BEAM, FUTURE_SIGHT_PLUS"。"""
        return f"{self.fast} / {', '.join(self.charged)}"


def moves_outside_movepool(species: Species, moveset: Moveset) -> list[str]:
    """配招里不在招式池中的招式 ID，按配招里的顺序；都在时返回空列表。

    第 3 个大招不在这里检查（规则更严，见模块说明）。Mega 专属招式放在第 1、2 个位置算在招式池外。
    """
    outside = []
    if moveset.fast not in species.fast_move_ids:
        outside.append(moveset.fast)
    for move_id in moveset.charged[:2]:
        if move_id not in species.charged_move_ids:
            outside.append(move_id)
    return outside
