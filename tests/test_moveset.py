"""配招与招式池检查。"""

import pytest

from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.moveset import Moveset, moves_outside_movepool


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def test_describe() -> None:
    moveset = Moveset("PSYCHO_CUT", ("PSYSTRIKE", "ICE_BEAM", "FUTURE_SIGHT_PLUS"))
    assert moveset.describe() == "PSYCHO_CUT / PSYSTRIKE, ICE_BEAM, FUTURE_SIGHT_PLUS"


@pytest.mark.parametrize(
    ("fast", "charged", "outside"),
    [
        # 都在招式池里（PSYSTRIKE 是限定招式，也算）；第三个是专属招式
        ("PSYCHO_CUT", ("PSYSTRIKE", "ICE_BEAM", "FUTURE_SIGHT_PLUS"), []),
        # 正作里超梦会 Avalanche，GO 里不会
        ("PSYCHO_CUT", ("PSYSTRIKE", "AVALANCHE", "FUTURE_SIGHT_PLUS"), ["AVALANCHE"]),
        # 快招也检查，按配招里的顺序列出
        ("WATERFALL", ("AVALANCHE", "PSYSTRIKE"), ["WATERFALL", "AVALANCHE"]),
        # 专属招式放在第 1、2 个位置不算招式池里
        ("CONFUSION", ("FUTURE_SIGHT_PLUS", "PSYSTRIKE"), ["FUTURE_SIGHT_PLUS"]),
        # 第三个大招不在这里检查（由 make_combatant 按 extraChargedMoves 检查）
        ("CONFUSION", ("PSYSTRIKE", "ICE_BEAM", "AVALANCHE"), []),
    ],
)
def test_moves_outside_movepool(
    gm: GameMaster, fast: str, charged: tuple[str, ...], outside: list[str]
) -> None:
    species = gm.get_species("mewtwo_mega_y")
    assert moves_outside_movepool(species, Moveset(fast, charged)) == outside
