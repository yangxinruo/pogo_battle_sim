"""能力值表（第 4 步 4d，docs/mechanics.md 14.6）：每只宝可梦在一个联盟里的实际攻击、防御、HP，用来排坦度等。

每只按赛季规则建配置（season.season_build，和网页、配置文件里不填 IV、等级时一样）：
- IV：这个联盟 IV 排名第 1（能力值乘积最大；IV 下限用 PvPoke 的默认值，见 iv_ranking.py）；
- 等级：等级上限内 CP 不超过联盟上限的最高等级（Mega 按赛季规则自动降等级）。
在这个联盟里没有合法配置的（最低等级时 CP 就超过上限）不在表里，单独列出原因。

表里的攻击、防御乘上了暗影倍率（BattleRules.shadow_attack / shadow_defense），和对战里算伤害时一样；HP 不变。
- 坦度 = 防御 × HP
- 能力值乘积 = 攻击 × 防御 × HP（含暗影倍率。IV 排名用的乘积不含暗影倍率，
  但同一只的每个 IV 组合乘的倍率都一样，所以不影响谁排第 1）

找 IV 排名第 1 要把 4096 个 IV 组合都算一遍，一只约 22 毫秒，全部 1700 多只单进程约 40 秒。所以：
- 多进程并行算（标准库 concurrent.futures）；
- 算出来的等级和 IV 存进本地缓存 .cache/stat_table/（不入库），下次直接读。
  缓存按联盟和赛季规则分文件。每只记下算它用到的数据（种族值、levelFloor、tags），
  数据变了（比如覆盖文件改了种族值）就重算这一只；算等级和 IV 的代码改了，整个缓存作废。
"""

import hashlib
import json
import os
import threading
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pogo_sim.combatant import species_stats
from pogo_sim.config import REPO_ROOT
from pogo_sim.damage import DamageSide, effective_attack, effective_defense
from pogo_sim.gamemaster import GameMaster, Species, load_gamemaster
from pogo_sim.rules import PVPOKE_COMPAT, BattleRules
from pogo_sim.season import SEASON_PRESETS, season_build
from pogo_sim.stats import IVs, calculate_cp

CACHE_DIR = REPO_ROOT / ".cache" / "stat_table"
# 算等级和 IV 用到的代码。这些文件改了，缓存作废。
CODE_FILES = ("cpm.py", "stats.py", "iv_ranking.py", "season.py", "combatant.py", "stat_table.py")
# 要算的不到这么多只时不开多进程（开进程本身要一两秒）
PARALLEL_MIN = 40


@dataclass(frozen=True)
class StatRow:
    """一只宝可梦在这个联盟的配置和实际能力值。"""

    species_id: str
    level: float
    ivs: IVs
    cp: int
    atk: float  # 含暗影倍率
    def_: float  # 含暗影倍率
    hp: int

    @property
    def bulk(self) -> float:
        """坦度 = 防御 × HP。"""
        return self.def_ * self.hp

    @property
    def stat_product(self) -> float:
        """能力值乘积 = 攻击 × 防御 × HP。"""
        return self.atk * self.def_ * self.hp


@dataclass(frozen=True)
class SkippedSpecies:
    """在这个联盟里没有合法配置的宝可梦。"""

    species_id: str
    reason: str


@dataclass(frozen=True)
class StatTable:
    cp_limit: int
    season_key: str
    rows: tuple[StatRow, ...]  # gamemaster 的顺序
    skipped: tuple[SkippedSpecies, ...]
    computed: int  # 这次新算了几只（其余的来自缓存）


def stat_table(
    cp_limit: int,
    season_key: str,
    custom_files: Sequence[Path | str] = (),
    *,
    rules: BattleRules = PVPOKE_COMPAT,
    cache_dir: Path = CACHE_DIR,
    workers: int | None = None,
    species_ids: Sequence[str] | None = None,
) -> StatTable:
    """全部宝可梦（加载覆盖文件后）在这个联盟、这个赛季规则下的能力值表。

    workers：并行算的进程数，默认是 CPU 核数；1 表示不开多进程。
    species_ids：只算这几只（测试用），默认全部。
    """
    if season_key not in SEASON_PRESETS:
        raise ValueError(f"不认识的赛季规则 {season_key!r}（可用：{', '.join(SEASON_PRESETS)}）")
    gm = load_gamemaster(custom_files=custom_files)
    ids = list(gm.species) if species_ids is None else list(species_ids)

    cache_file = cache_dir / f"{cp_limit}_{season_key}.json"
    cache = _read_cache(cache_file)
    todo = [sid for sid in ids if cache.get(sid, {}).get("inputs") != _inputs(gm.species[sid])]
    if todo:
        for sid, result in _compute(todo, custom_files, cp_limit, season_key, workers):
            cache[sid] = {"inputs": _inputs(gm.species[sid]), **result}
        _write_cache(cache_file, cache)

    rows = []
    skipped = []
    for sid in ids:
        entry = cache[sid]
        if "error" in entry:
            skipped.append(SkippedSpecies(sid, entry["error"]))
        else:
            rows.append(make_row(gm.species[sid], entry["level"], IVs(*entry["ivs"]), rules))
    return StatTable(cp_limit, season_key, tuple(rows), tuple(skipped), len(todo))


def make_row(species: Species, level: float, ivs: IVs, rules: BattleRules = PVPOKE_COMPAT) -> StatRow:
    """按等级和 IV 算一行：CP、实际能力值（攻击、防御乘暗影倍率，和对战里算伤害时一样）。"""
    stats = species_stats(species, ivs, level)
    side = DamageSide(types=species.types, stats=stats, is_shadow=species.is_shadow)
    return StatRow(
        species_id=species.species_id,
        level=level,
        ivs=ivs,
        cp=calculate_cp(species.base_stats, ivs, level),
        atk=effective_attack(side, rules),
        def_=effective_defense(side, rules),
        hp=stats.hp,
    )


def level_and_ivs(gm: GameMaster, species_id: str, cp_limit: int, season_key: str) -> dict[str, Any]:
    """按赛季规则选的等级和 IV：{"level": 45.5, "ivs": [0, 15, 13]}；没有合法配置时是 {"error": 原因}。

    招式和等级、IV 无关，这里不给（season_build 只在 make_combatant 里检查招式）。
    """
    try:
        build = season_build(gm, species_id, cp_limit, "", (), season=SEASON_PRESETS[season_key])
    except ValueError as e:
        return {"error": str(e)}
    return {"level": build.level, "ivs": [build.ivs.atk, build.ivs.def_, build.ivs.hp]}


# ---- 并行计算 ----


def _compute(
    species_ids: list[str],
    custom_files: Sequence[Path | str],
    cp_limit: int,
    season_key: str,
    workers: int | None,
) -> list[tuple[str, dict[str, Any]]]:
    """算这几只的等级和 IV。只数多时分给几个进程，每个进程自己读 gamemaster。"""
    files = [str(path) for path in custom_files]
    workers = workers or os.cpu_count() or 1
    if workers <= 1 or len(species_ids) < PARALLEL_MIN:
        return _compute_chunk(files, species_ids, cp_limit, season_key)
    chunks = [species_ids[i::workers] for i in range(workers)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_compute_chunk, files, chunk, cp_limit, season_key) for chunk in chunks]
        return [item for future in futures for item in future.result()]


def _compute_chunk(
    custom_files: list[str], species_ids: list[str], cp_limit: int, season_key: str
) -> list[tuple[str, dict[str, Any]]]:
    gm = load_gamemaster(custom_files=custom_files)
    return [(sid, level_and_ivs(gm, sid, cp_limit, season_key)) for sid in species_ids]


# ---- 缓存 ----


def _inputs(species: Species) -> list[Any]:
    """算等级和 IV 用到的这只的数据（写进缓存；变了就重算）。tags 决定 IV 下限和是不是 Mega。"""
    base = species.base_stats
    return [base.atk, base.def_, base.hp, species.level_floor, sorted(species.tags)]


def _code_version() -> str:
    """算等级和 IV 的代码的指纹（CODE_FILES 的内容）。"""
    digest = hashlib.sha256()
    for name in CODE_FILES:
        digest.update((Path(__file__).parent / name).read_bytes())
    return digest.hexdigest()[:16]


def _read_cache(path: Path) -> dict[str, dict[str, Any]]:
    """读缓存；没有、读不了、或者代码改过时为空。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("code") != _code_version():
        return {}
    return data.get("species", {})


def _write_cache(path: Path, species: dict[str, dict[str, Any]]) -> None:
    """先写临时文件再改名：两个请求同时写也不会留下写了一半的文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps({"code": _code_version(), "species": species}), encoding="utf-8")
    tmp.replace(path)
