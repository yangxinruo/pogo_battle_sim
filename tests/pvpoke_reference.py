"""读取 PvPoke 参考数据（tests/fixtures/ 下的 JSON）。

这些 JSON 由 tools/pvpoke_ref/ 里的脚本用 PvPoke 源码生成，入库保存，所以跑测试不需要 Node。
重新生成的方法见 README。
"""

import json
from functools import cache
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DAMAGE_REFERENCE_PATH = FIXTURES_DIR / "pvpoke_damage_reference.json"
BATTLE_REFERENCE_PATH = FIXTURES_DIR / "pvpoke_battle_reference.json"
SWITCH_REFERENCE_PATH = FIXTURES_DIR / "pvpoke_switch_reference.json"


@cache
def load_damage_reference() -> dict:
    """CPM 表、属性克制表和伤害用例。"""
    with DAMAGE_REFERENCE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@cache
def load_battle_reference() -> dict:
    """整场对战：配置、剧本、逐回合状态、招式事件、结果。"""
    with BATTLE_REFERENCE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@cache
def load_switch_reference() -> dict:
    """按剧本打的队伍对战（含换人）：配置、剧本、逐回合全队状态、招式 / 换人 / 倒下事件、结果。"""
    with SWITCH_REFERENCE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


IV_REFERENCE_PATH = FIXTURES_DIR / "pvpoke_iv_reference.json"


@cache
def load_iv_reference() -> dict:
    """IV 排名：每个用例的完整名次顺序和前几名的详细数值。"""
    with IV_REFERENCE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def decode_iv_order(order: str) -> list[tuple[int, int, int]]:
    """解码排名顺序：每个组合 3 个十六进制字符（攻、防、HP IV）。"""
    return [
        (int(order[i], 16), int(order[i + 1], 16), int(order[i + 2], 16))
        for i in range(0, len(order), 3)
    ]


def decode_iv_levels(levels: str) -> list[float]:
    """解码等级：每个组合 2 个十六进制字符（等级 × 2）。"""
    return [int(levels[i : i + 2], 16) / 2 for i in range(0, len(levels), 2)]
