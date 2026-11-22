"""PvPoke 的排名文件和环境前 N（pogo_sim/rankings.py）。"""

import hashlib
import re

import pytest

import pogo_sim.rankings as rankings_module
from pogo_sim.combatant import league_build
from pogo_sim.config import REPO_ROOT, ConfigError, Entry, prepare_entry
from pogo_sim.gamemaster import GameMaster, load_gamemaster
from pogo_sim.moveset import Moveset
from pogo_sim.rankings import (
    RANKING_CUPS,
    PoolSpec,
    format_pool_members,
    format_skipped,
    load_rankings,
    parse_pool_spec,
    prepare_pool,
    rankings_path,
    top_ranked,
)
from pogo_sim.season import MEGA_CAP_52, PVPOKE_SEASON

LEAGUES = (1500, 2500, 10000)
SOURCE_MD = REPO_ROOT / "data" / "SOURCE.md"


@pytest.fixture(scope="module")
def gm() -> GameMaster:
    return load_gamemaster()


def _source_table() -> dict[str, tuple[int, str]]:
    """data/SOURCE.md 里排名文件的表：文件 → (条目数, SHA-256)。"""
    rows = re.findall(r"^\| `(\w+/overall/rankings-\d+\.json)` \| (\d+) \| `([0-9a-f]{64})` \|$", SOURCE_MD.read_text(), re.M)
    return {path: (int(count), sha) for path, count, sha in rows}


# ---- 排名文件 ----


def test_snapshot_matches_source_md() -> None:
    """六个文件都在，SHA-256 和条目数与 data/SOURCE.md 记录的一致（原样保存，没有改过）。"""
    table = _source_table()
    assert len(table) == len(RANKING_CUPS) * len(LEAGUES)
    for cup in RANKING_CUPS:
        for league in LEAGUES:
            relative = f"{cup}/overall/rankings-{league}.json"
            count, sha = table[relative]
            path = rankings_path(cup, league)
            assert hashlib.sha256(path.read_bytes()).hexdigest() == sha, relative
            assert len(load_rankings(cup, league)) == count, relative


def test_load_rankings() -> None:
    ranking = load_rankings("mega", 1500)
    assert [r.rank for r in ranking[:3]] == [1, 2, 3]
    first = ranking[0]
    assert first.species_id == "sableye_mega"
    assert first.moveset == Moveset("SHADOW_CLAW", ("FOUL_PLAY", "DAZZLING_GLEAM", "NIGHT_SHADE_PLUS"))
    assert first.score == 94
    assert load_rankings("all", 1500)[0].species_id == "melmetal"


@pytest.mark.parametrize(
    ("cup", "league", "message"),
    [
        ("great", 1500, "不认识的排名 'great'（可用：all, mega）"),
        ("mega", 500, "没有小小杯的 mega 排名（data/rankings/mega/overall/rankings-500.json）"),
    ],
)
def test_missing_rankings(cup: str, league: int, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        load_rankings(cup, league)


def test_top_ranked_splits_mega_and_non_mega(gm: GameMaster) -> None:
    """D5：Mega 和非 Mega 分开取前 N，名次是排名文件里的名次（两类一起排）。"""
    megas = top_ranked(gm, "mega", 1500, "mega", 3)
    assert [(r.rank, r.species_id) for r in megas] == [
        (1, "sableye_mega"), (32, "malamar_mega"), (177, "audino_mega"),
    ]
    others = top_ranked(gm, "mega", 1500, "non_mega", 3)
    assert [(r.rank, r.species_id) for r in others] == [(2, "melmetal"), (3, "altaria"), (4, "ninetales_shadow")]
    # 普通联盟的排名不含 Mega
    assert top_ranked(gm, "all", 1500, "mega", 10) == ()


def test_top_ranked_unknown_kind(gm: GameMaster) -> None:
    with pytest.raises(ValueError, match="不认识的类别 'megas'"):
        top_ranked(gm, "mega", 1500, "megas", 3)


@pytest.mark.parametrize("cup", list(RANKING_CUPS))
@pytest.mark.parametrize("league", LEAGUES)
def test_top_entries_build(gm: GameMaster, cup: str, league: int) -> None:
    """排名和 gamemaster 是同一个 commit：前 10 只（Mega、非 Mega 各取）都能按默认赛季规则建配置，名字不重复。

    （一次性扫过：六个文件、两类各前 100 只、四种赛季规则、两种 IV 规则，都没有建不了的。测试里只查前 10，省时间。）
    """
    for kind in ("mega", "non_mega"):
        pool = prepare_pool(gm, PoolSpec("x", cup, kind, 10), league, PVPOKE_SEASON)
        assert pool.skipped == ()
        expected = 0 if cup == "all" and kind == "mega" else 10
        assert len(pool.members) == expected
        labels = [p.label for p in pool.participants]
        assert len(set(labels)) == len(labels)


# ---- 配置里的环境前 N ----


def test_parse_pool_spec_defaults() -> None:
    spec = parse_pool_spec({"rankings": "mega", "kind": "non_mega", "top": 50}, "x")
    assert spec == PoolSpec(name="非 Mega 前 50（mega 排名）", rankings="mega", kind="non_mega", top=50, ivs="rank1")
    assert spec.describe(1500) == (
        "PvPoke 的 mega 排名（Mega 版，Mega 和非 Mega 一起排），超级联盟，非 Mega 前 50 只；"
        "IV 排名第 1，等级按赛季规则（和配置文件不写 IV 时一样）"
    )


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("mega", "x：要写成表，得到 'mega'"),
        ({"rankings": "mega", "kind": "mega"}, "x：缺少 top"),
        ({"rankings": "mega", "kind": "mega", "top": 5, "count": 3}, "x：不认识的字段 count"),
        ({"rankings": "great", "kind": "mega", "top": 5}, "x：rankings 要写 'all' / 'mega'，得到 'great'"),
        ({"rankings": "mega", "kind": "megas", "top": 5}, "x：kind 要写 'mega' / 'non_mega'，得到 'megas'"),
        ({"rankings": "mega", "kind": "mega", "top": 0}, "x：top 要写正整数，得到 0"),
        ({"rankings": "mega", "kind": "mega", "top": True}, "x：top 要写正整数，得到 True"),
        ({"rankings": "mega", "kind": "mega", "top": 5, "ivs": "max"}, "x：ivs 要写 'rank1' / 'pvpoke_default'，得到 'max'"),
        ({"rankings": "mega", "kind": "mega", "top": 5, "name": ""}, "x：name 要写非空的字符串"),
    ],
)
def test_bad_pool_spec(raw: object, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        parse_pool_spec(raw, "x")


def test_pool_rank1_ivs(gm: GameMaster) -> None:
    """默认 IV 排名第 1：和配置文件里只写种类和配招、不写 IV 时完全一样。"""
    pool = prepare_pool(gm, PoolSpec("x", "mega", "mega", 2), 1500, PVPOKE_SEASON)
    for member in pool.members:
        entry = Entry(None, member.ranked.species_id, member.ranked.moveset)
        assert member.participant == prepare_entry(gm, entry, 1500, PVPOKE_SEASON)
    assert pool.members[0].participant.label == "Sableye (Mega)"


def test_pool_pvpoke_default_ivs(gm: GameMaster) -> None:
    """PvPoke 默认 IV：等级和 IV 与 combatant.league_build 相同。"""
    pool = prepare_pool(gm, PoolSpec("x", "mega", "non_mega", 3, ivs="pvpoke_default"), 1500, PVPOKE_SEASON)
    for member in pool.members:
        moveset = member.ranked.moveset
        expected = league_build(gm, member.ranked.species_id, 1500, moveset.fast, moveset.charged)
        assert (member.participant.build.ivs, member.participant.build.level) == (expected.ivs, expected.level)
    # 大师联盟：50 级 15/15/15
    pool = prepare_pool(gm, PoolSpec("x", "all", "non_mega", 2, ivs="pvpoke_default"), 10000, PVPOKE_SEASON)
    assert {(m.participant.build.level, m.participant.build.ivs.atk) for m in pool.members} == {(50.0, 15)}


def test_pool_follows_season_rules(gm: GameMaster) -> None:
    """IV 排名第 1 时等级按赛季规则：Mega 上限 52 的赛季，大师联盟的 Mega 是 52 级。"""
    pool = prepare_pool(gm, PoolSpec("x", "mega", "mega", 1), 10000, MEGA_CAP_52)
    assert pool.members[0].participant.build.level == 52


def test_pool_skips_entries_that_cannot_be_built(gm: GameMaster, monkeypatch: pytest.MonkeyPatch) -> None:
    """前 N 名里建不了配置的跳过，记下原因，不往后补。"""
    real_prepare = rankings_module.prepare_entry

    def fake_prepare(gm_, entry, league, season):
        if entry.species_id == "altaria":
            raise ValueError("假装建不了")
        return real_prepare(gm_, entry, league, season)

    monkeypatch.setattr(rankings_module, "prepare_entry", fake_prepare)
    pool = prepare_pool(gm, PoolSpec("x", "mega", "non_mega", 3), 1500, PVPOKE_SEASON)
    assert [m.ranked.species_id for m in pool.members] == ["melmetal", "ninetales_shadow"]
    assert [(s.ranked.rank, s.reason) for s in pool.skipped] == [(3, "假装建不了")]
    assert format_skipped(pool.skipped) == ["- 第 3 名 altaria：假装建不了"]


def test_format_pool_members(gm: GameMaster) -> None:
    pool = prepare_pool(gm, PoolSpec("x", "mega", "mega", 1), 1500, PVPOKE_SEASON)
    assert format_pool_members(gm, pool).splitlines() == [
        "| 名次 | 宝可梦 | PvPoke 分 | CP | 等级 | IV | 配招 |",
        "|---|---|---|---|---|---|---|",
        "| 1 | Sableye (Mega) | 94 | 1499 | 30 | 0/15/12 | SHADOW_CLAW / FOUL_PLAY, DAZZLING_GLEAM, NIGHT_SHADE_PLUS |",
    ]
