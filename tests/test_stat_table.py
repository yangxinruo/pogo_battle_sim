"""能力值表（pogo_sim/stat_table.py，4d）。

核对：每只的等级和 IV 和按赛季规则建配置（season_build）时一样；攻防乘暗影倍率；脱壳忍者 HP 10；
没有合法配置的单独列出；缓存（第二次不再算、数据变了重算那一只、代码改了全部重算、坏文件当没有）；多进程和单进程结果相同。
为了快，只算几只（species_ids），缓存放在临时目录。
"""

import json

import pytest

from pogo_sim import stat_table as st
from pogo_sim.config import REPO_ROOT
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.rules import PVPOKE_COMPAT
from pogo_sim.season import SEASON_PRESETS, season_build
from pogo_sim.stats import calculate_battle_stats

IDS = ["azumarill", "medicham", "bastiodon_shadow", "shedinja", "sableye_mega", "darkrai"]
FROSLASS_FILE = REPO_ROOT / "data" / "custom" / "mega_froslass.toml"


@pytest.fixture(scope="module")
def gm():
    return load_gamemaster()


def make_table(cache_dir, species_ids=IDS, **kwargs):
    return st.stat_table(1500, "pvpoke", cache_dir=cache_dir, workers=1, species_ids=species_ids, **kwargs)


def test_rows_match_season_build(gm, tmp_path):
    rows = {row.species_id: row for row in make_table(tmp_path).rows}
    assert set(rows) == set(IDS) - {"darkrai"}
    for species_id in ["azumarill", "medicham", "sableye_mega"]:  # Mega 按赛季规则自动降等级
        build = season_build(gm, species_id, 1500, "", (), season=SEASON_PRESETS["pvpoke"])
        assert (rows[species_id].level, rows[species_id].ivs) == (build.level, build.ivs)
        assert rows[species_id].cp <= 1500
    azumarill = rows["azumarill"]
    assert (azumarill.cp, azumarill.level) == (1499, 45.5)
    assert azumarill.bulk == azumarill.def_ * azumarill.hp
    assert azumarill.stat_product == azumarill.atk * azumarill.def_ * azumarill.hp


def test_shadow_multipliers_and_shedinja(gm, tmp_path):
    rows = {row.species_id: row for row in make_table(tmp_path).rows}
    shadow = rows["bastiodon_shadow"]
    raw = calculate_battle_stats(gm.species["bastiodon_shadow"].base_stats, shadow.ivs, shadow.level)
    assert shadow.atk == pytest.approx(raw.atk * PVPOKE_COMPAT.shadow_attack)
    assert shadow.def_ == pytest.approx(raw.def_ * PVPOKE_COMPAT.shadow_defense)
    assert shadow.hp == raw.hp
    # 不是暗影的不乘
    plain = rows["azumarill"]
    assert plain.def_ == calculate_battle_stats(gm.species["azumarill"].base_stats, plain.ivs, plain.level).def_
    assert rows["shedinja"].hp == 10


def test_skipped(tmp_path):
    table = make_table(tmp_path)
    assert [item.species_id for item in table.skipped] == ["darkrai"]
    assert "15 级时 CP 就超过 1500" in table.skipped[0].reason


def test_unknown_season(tmp_path):
    with pytest.raises(ValueError, match="不认识的赛季规则"):
        st.stat_table(1500, "nope", cache_dir=tmp_path, species_ids=IDS)


def test_cache(tmp_path, monkeypatch):
    first = make_table(tmp_path)
    assert first.computed == len(IDS)
    assert (tmp_path / "1500_pvpoke.json").exists()

    # 第二次全部读缓存：算等级和 IV 的函数一次也不调用
    def must_not_compute(*args):
        raise AssertionError("应该读缓存")

    monkeypatch.setattr(st, "level_and_ivs", must_not_compute)
    second = make_table(tmp_path)
    assert second.computed == 0
    assert (second.rows, second.skipped) == (first.rows, first.skipped)


def test_cache_recomputes_new_or_changed_species(tmp_path):
    make_table(tmp_path)
    # 覆盖文件新加的 Mega 雪妖女：只算它
    table = make_table(tmp_path, species_ids=[*IDS, "froslass_mega"], custom_files=[FROSLASS_FILE])
    assert table.computed == 1
    assert table.rows[-1].species_id == "froslass_mega"

    # 缓存里一只的数据和现在的对不上（比如覆盖文件改过种族值）：重算这一只
    cache_file = tmp_path / "1500_pvpoke.json"
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    data["species"]["azumarill"]["inputs"][0] += 1
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    assert make_table(tmp_path).computed == 1


def test_cache_invalid_when_code_changes_or_file_broken(tmp_path, monkeypatch):
    first = make_table(tmp_path)
    monkeypatch.setattr(st, "_code_version", lambda: "changed")
    second = make_table(tmp_path)
    assert second.computed == len(IDS) and second.rows == first.rows

    (tmp_path / "1500_pvpoke.json").write_text("{not json", encoding="utf-8")
    assert make_table(tmp_path).computed == len(IDS)


def test_parallel_same_as_single_process(monkeypatch):
    ids = ["azumarill", "medicham", "darkrai", "sableye_mega"]
    single = st._compute(ids, [], 1500, "pvpoke", workers=1)
    monkeypatch.setattr(st, "PARALLEL_MIN", 1)
    parallel = st._compute(ids, [], 1500, "pvpoke", workers=2)
    assert sorted(parallel) == sorted(single)
