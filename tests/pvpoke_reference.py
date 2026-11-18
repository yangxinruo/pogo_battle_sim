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
