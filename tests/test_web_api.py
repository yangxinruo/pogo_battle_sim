"""网页界面的接口（pogo_sim/web_api.py，docs/mechanics.md 第 14 节）。

接口只做转换，所以这里主要核对：网页发来的配置和配置文件走同一套检查、打出同一场；
返回的数据和引擎、报告用的是同一批数字；覆盖文件只能从 data/custom/ 里选。
"""

import copy
import json
import re
import tomllib
from dataclasses import asdict, fields

import pytest

from pogo_sim import team_library, team_matrix, web_api
from pogo_sim.battle_summary import lane_items
from pogo_sim.best_response import format_best_response_report, search_best_response
from pogo_sim.config import REPO_ROOT, ConfigError, load_toml, parse_entry, prepare_entry
from pogo_sim.damage import calculate_damage
from pogo_sim.gamemaster import load_gamemaster
from pogo_sim.manual import parse_decisions, play_manual
from pogo_sim.matchups import (
    battle_names,
    fight,
    format_csv,
    format_report,
    load_matchup_config,
    make_sides,
    parse_matchup_config,
    pool_summary,
    prepare_matchups,
    run_all,
    run_pools,
)
from pogo_sim.season import PVPOKE_SEASON, SEASON_PRESETS
from pogo_sim.simple_policy import SimplePolicyConfig
from pogo_sim.team_battle import (
    SWITCH_KINDS,
    format_team_battle_report,
    load_team_battle_config,
    make_teams,
    max_hps,
    member_summaries,
    parse_team_battle_config,
    prepare_team_battle,
    run_team_battle,
    segments,
    timeline_names,
)
from pogo_sim.timeline import MoveEvent, SwitchEvent, describe_event, event_actor, format_event
from tests.test_manual import _auto_choices
from tests.test_matchup_pools import EXPLICIT_OPPONENT, POOL_CONFIG

EXAMPLE = REPO_ROOT / "experiments" / "gl_3v3_example.toml"


@pytest.fixture(scope="module")
def engine_battle():
    """直接用配置文件打的那一场（对照用）。"""
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    return battle, run_team_battle(battle)


@pytest.fixture(scope="module")
def payload():
    """网页打的同一场，转成 JSON 再读回来（浏览器拿到的就是这样：tuple 变成 list）。"""
    return json.loads(json.dumps(web_api.team_battle(web_api.example_config())))


def _example() -> dict:
    return copy.deepcopy(web_api.example_config())


# ---- 配置：dict 和文件走同一套检查 ----


def test_parse_dict_same_as_file():
    raw = load_toml(EXAMPLE)
    assert parse_team_battle_config(raw, EXAMPLE.name) == load_team_battle_config(EXAMPLE)


def test_parse_rejects_non_table():
    with pytest.raises(ConfigError, match="网页：配置要写成表"):
        parse_team_battle_config(["not", "a", "table"], "网页")
    with pytest.raises(ConfigError, match="网页：配置要写成表"):
        web_api.team_battle("league = 1500")


def test_config_errors_same_messages_as_file():
    raw = _example()
    del raw["team"]
    with pytest.raises(ConfigError, match="^网页：缺少 team$"):
        web_api.team_battle(raw)

    raw = _example()
    raw["team"][0]["member"][1]["species"] = "not_a_pokemon"
    with pytest.raises(ConfigError, match="Team A 第 2 只（not_a_pokemon）"):
        web_api.team_battle(raw)

    raw = _example()
    raw["team"][0]["policy"] = {"switching": "sometimes"}
    with pytest.raises(ConfigError, match="网页：第 1 队（Team A）"):
        web_api.team_battle(raw)


def test_example_config_is_the_example_file():
    raw = load_toml(EXAMPLE)
    example = web_api.example_config()
    assert "description" not in example  # 网页不编辑说明文字
    assert example["custom_files"] == []
    assert example["team"] == raw["team"]
    assert (example["league"], example["season"]) == (raw["league"], raw["season"])


# ---- 打一场：和引擎、报告用同一批数字 ----


def test_team_battle_same_as_config_file(payload, engine_battle):
    battle, result = engine_battle
    assert payload["result"] == {
        "winner": result.winner,
        "ratings": list(result.ratings),
        "turns": result.turns,
        "elapsed_ms": result.elapsed_ms,
        "timed_out": result.timed_out,
        "remaining": list(result.remaining),
        "shields_left": list(result.shields_left),
    }
    # docs/mechanics.md 13.8 的例子：B 赢，评分 221 对 778，100 回合
    assert (payload["result"]["winner"], payload["result"]["ratings"], payload["result"]["turns"]) == (1, [221, 778], 100)
    assert payload["members"] == json.loads(json.dumps([asdict(s) for s in member_summaries(battle, result)]))
    # 网页的配置不带说明文字，报告里就少了开头那一段，其余逐字相同
    assert format_team_battle_report(battle, result) == f"{battle.config.description}\n\n{payload['report_markdown']}"
    assert payload["outcome"].startswith("Team B 赢。评分 221 对 778")


def test_payload_is_plain_json():
    raw = web_api.team_battle(web_api.example_config())
    text = json.dumps(raw, ensure_ascii=False, allow_nan=False)  # 有不能转的值（Path、NaN 等）会报错
    assert json.loads(text)["result"]["winner"] == 1


def test_teams_in_payload(payload, engine_battle):
    battle, _ = engine_battle
    assert [team["name"] for team in payload["teams"]] == ["Team A", "Team B"]
    first = payload["teams"][0]["members"][0]
    assert first["species"] == "azumarill"
    assert (first["cp"], first["level"], first["ivs"]) == (1499, 45.5, [0, 15, 15])
    assert first["fast"] == "BUBBLE" and first["charged"] == ["ICE_BEAM", "PLAY_ROUGH"]
    assert [team["names"] for team in payload["teams"]] == [list(n) for n in timeline_names(battle)]
    assert payload["teams"][0]["policy"] == "TeamPolicy，默认参数"


def test_switches_and_charged_moves(payload, engine_battle):
    _, result = engine_battle
    switches = [e for e in result.events if isinstance(e, SwitchEvent)]
    charged = [e for e in result.events if isinstance(e, MoveEvent) and e.is_charged]
    assert [(s["turn"], s["side"], s["to_slot"]) for s in payload["switches"]] == [
        (e.turn, e.actor, e.to_slot) for e in switches
    ]
    assert all(s["reason"] and s["kind_text"] == SWITCH_KINDS[s["kind"]] for s in payload["switches"])
    assert [(c["turn"], c["move_id"], c["damage"]) for c in payload["charged"]] == [
        (e.turn, e.move_id, e.damage) for e in charged
    ]
    # 例子里第 21 回合 Swampert 的 Hydro Cannon 被 Azumarill 开盾挡下
    assert payload["charged"][0] == {
        "turn": 21, "side": 1, "attacker_slot": 0, "move_id": "HYDRO_CANNON", "target_slot": 0,
        "damage": 1, "shielded": True, "hp_after": 165,
        "shield_reason": payload["charged"][0]["shield_reason"],
    }


def test_opening_matchups(payload):
    # 两队的评估配置相同，只列第 0 方的：3 × 3
    assert len(payload["opening"]) == 1
    assert payload["opening"][0]["side"] == 0
    assert [len(row) for row in payload["opening"][0]["ratings"]] == [3, 3, 3]


def test_timeline_has_every_event_and_snapshot(payload, engine_battle):
    battle, result = engine_battle
    timeline = payload["timeline"]
    turns = [entry["turn"] for entry in timeline]
    assert turns == sorted(set(turns))
    assert sum(len(entry["events"]) for entry in timeline) == len(result.events)
    assert {s.turn for s in result.snapshots} <= set(turns)

    names = timeline_names(battle)
    flat = [event for entry in timeline for event in entry["events"]]
    for sent, event in zip(flat, result.events):
        assert sent["data"]["turn"] == event.turn
        assert (sent["side"], sent["slot"]) == event_actor(event)
        assert format_event(event, names).endswith(sent["text"])

    last = timeline[-1]
    assert last["sides"][1]["member_hp"] == list(result.snapshots[-1].sides[1].member_hp)


def test_event_text_is_format_event_without_prefix(engine_battle):
    battle, result = engine_battle
    names = timeline_names(battle)
    for event in result.events:
        side, slot = event_actor(event)
        prefix = f"T{event.turn:>4}  {names[side][slot]}"
        line = format_event(event, names)
        assert line.startswith(prefix)
        assert line[len(prefix):].strip() == describe_event(event, names)


def test_team_battle_settings(payload):
    assert payload["settings"] == {
        "league": 1500, "league_name": "超级联盟", "season": "PvPoke 兼容", "custom_log": [],
    }


# ---- 覆盖文件只能从 data/custom/ 里选 ----


def test_custom_files_listed():
    files = web_api.available_custom_files()
    assert list(files) == sorted(p.name for p in (REPO_ROOT / "data" / "custom").glob("*.toml"))
    assert files["mega_froslass.toml"].startswith("Mega 雪妖女")


@pytest.mark.parametrize("names", [
    ["../gamemaster.json"],
    ["data/custom/mega_froslass.toml"],
    ["/etc/passwd"],
    ["nope.toml"],
])
def test_custom_files_outside_data_custom_rejected(names):
    raw = _example() | {"custom_files": names}
    with pytest.raises(ConfigError, match="data/custom/ 里没有覆盖文件"):
        web_api.team_battle(raw)


def test_custom_files_must_be_a_list():
    with pytest.raises(ConfigError, match="custom_files 要写覆盖文件名的列表"):
        web_api.team_battle(_example() | {"custom_files": "mega_froslass.toml"})


def test_team_battle_with_custom_file():
    raw = _example() | {"custom_files": ["mega_froslass.toml"]}
    raw["team"][0]["member"][2] = {
        "species": "froslass_mega", "fast": "POWDER_SNOW", "charged": ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"],
    }
    payload = web_api.team_battle(raw)
    assert any("mega_froslass.toml" in line for line in payload["settings"]["custom_log"])
    froslass = payload["teams"][0]["members"][2]
    assert froslass["species_name"] == "Froslass (Mega)"
    assert froslass["charged"] == ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"]
    assert froslass["mega_level"] == 4


# ---- 一只宝可梦 ----


def test_build_member_same_as_engine():
    member = {"species": "azumarill", "fast": "BUBBLE", "charged": ["ICE_BEAM", "PLAY_ROUGH"]}
    info = web_api.build_member({"league": 1500, "season": "pvpoke", "member": member})
    gm = load_gamemaster()
    participant = prepare_entry(gm, parse_entry(member, "x"), 1500, PVPOKE_SEASON)
    assert (info["cp"], info["level"], info["ivs"]) == (1499, 45.5, [0, 15, 15])
    assert info["level"] == participant.build.level
    assert info["notes"] == list(participant.build.notes)
    assert info["hp"] == 196
    assert info["label"] == "Azumarill"


def test_build_member_with_ivs_level_and_label():
    member = {
        "species": "medicham", "fast": "COUNTER", "charged": ["ICE_PUNCH"],
        "ivs": [15, 15, 15], "level": 40, "label": "Hundo",
    }
    info = web_api.build_member({"league": 1500, "season": "pvpoke", "member": member})
    assert (info["ivs"], info["level"], info["label"]) == ([15, 15, 15], 40.0, "Hundo")


def test_build_member_errors():
    outside = {"species": "azumarill", "fast": "MUD_SHOT", "charged": ["ICE_BEAM"]}
    with pytest.raises(ConfigError, match="^网页：azumarill 的招式池里没有 MUD_SHOT"):
        web_api.build_member({"league": 1500, "season": "pvpoke", "member": outside})
    # 写了 outside_movepool 就可以
    info = web_api.build_member({"league": 1500, "season": "pvpoke", "member": outside | {"outside_movepool": True}})
    assert info["outside_movepool"] == ["MUD_SHOT"]

    with pytest.raises(ConfigError, match="缺少 member"):
        web_api.build_member({"league": 1500, "season": "pvpoke"})
    with pytest.raises(ConfigError, match="不认识的字段 extra"):
        web_api.build_member({"league": 1500, "season": "pvpoke", "member": outside, "extra": 1})
    with pytest.raises(ConfigError, match="不认识的赛季规则"):
        web_api.build_member({"league": 1500, "season": "nope", "member": outside})
    with pytest.raises(ConfigError, match="缺少 fast"):
        web_api.build_member({"league": 1500, "season": "pvpoke", "member": {"species": "azumarill", "charged": []}})


# ---- 选项和宝可梦列表 ----


def test_options():
    options = web_api.options()
    assert [s["key"] for s in options["seasons"]] == list(SEASON_PRESETS)
    assert [s["key"] for s in options["switching"]] == ["threshold", "never"]
    assert [league["cp"] for league in options["leagues"]] == [500, 1500, 2500, 10000]
    assert (options["max_shields"], options["team_size"]) == (2, 3)
    assert [f["name"] for f in options["custom_files"]] == list(web_api.available_custom_files())
    assert options["example"] == web_api.example_config()


def test_species_catalog():
    catalog = web_api.species_catalog([], "1500")
    species = {s["id"]: s for s in catalog["species"]}
    azumarill = species["azumarill"]
    assert "BUBBLE" in azumarill["fast"] and "PLAY_ROUGH" in azumarill["charged"]
    assert azumarill["types"] == ["water", "fairy"]
    assert azumarill["recommended"] == ["BUBBLE", "ICE_BEAM", "PLAY_ROUGH"]
    assert not azumarill["custom"] and azumarill["released"]
    assert "froslass_mega" not in species
    # Mega 的推荐配招来自 Mega 版排名，可能带第三个大招
    assert len(species["sableye_mega"]["recommended"]) == 4
    assert catalog["moves"]["BUBBLE"]["fast"] is True
    assert catalog["moves"]["HYDRO_CANNON"]["energy"] == 40  # 大招是要花的能量


def test_species_catalog_search_and_rank():
    species = {s["id"]: s for s in web_api.species_catalog([], "1500")["species"]}
    # 搜索用的文字：网页把输入拆成词，每个词都要在这里出现（不分先后）
    def words(species_id):
        return species[species_id]["search"].split()

    assert {"zygarde", "complete", "forme", "100", "legendary"} <= set(words("zygarde_complete"))
    assert {"venusaur", "mega"} <= set(words("venusaur_mega"))
    assert "mega" in words("kyogre_primal")  # 原始回归也算 Mega
    assert "mega" not in words("meganium")
    assert {"mr", "mime", "mrmime"} <= set(words("mr_mime"))
    # 名次：普通排名；Mega 不在普通排名里，另给 Mega 版排名的名次
    assert (species["melmetal"]["rank"], species["melmetal"]["mega_rank"]) == (1, None)
    assert (species["sableye_mega"]["rank"], species["sableye_mega"]["mega_rank"]) == (None, 1)
    assert species["zygarde_complete"]["rank"] is None  # 排名里没有


def test_normalize_search():
    # 和网页 app.js 的 normalizeSearch 一样：小写、去掉重音、标点换成空格
    assert web_api.normalize_search("Flabébé") == "flabebe"
    assert web_api.normalize_search("Mr. Mime (Galarian)") == "mr mime galarian"
    assert web_api.normalize_search("Zygarde 100% complete form") == "zygarde 100 complete form"
    assert web_api.normalize_search("  ") == ""


def test_species_catalog_with_custom_file():
    catalog = web_api.species_catalog(["mega_froslass.toml"])
    species = {s["id"]: s for s in catalog["species"]}
    froslass = species["froslass_mega"]
    assert froslass["custom"] and froslass["mega"] and not froslass["released"]
    assert froslass["extra_charged"] == ["AVALANCHE_PLUS"]
    assert froslass["recommended"] is None  # 没给联盟
    assert "AVALANCHE_PLUS" in catalog["moves"]
    assert not species["froslass"]["custom"]


def test_species_catalog_league():
    # 小小杯没有排名文件：没有推荐配招，但宝可梦照样列出
    catalog = web_api.species_catalog([], "500")
    assert catalog["species"] and all(s["recommended"] is None for s in catalog["species"])
    assert all(s["rank"] is None and s["mega_rank"] is None for s in catalog["species"])
    with pytest.raises(ConfigError, match="league 要写正整数"):
        web_api.species_catalog([], "abc")
    with pytest.raises(ConfigError, match="data/custom/ 里没有覆盖文件"):
        web_api.species_catalog(["../gamemaster.json"])


# ---- 能力值排序（4d） ----


def test_stat_table_payload(tmp_path):
    ids = ["azumarill", "bastiodon_shadow", "darkrai", "froslass_mega"]
    data = web_api.stat_table_payload("1500", "pvpoke", ["mega_froslass.toml"], cache_dir=tmp_path, species_ids=ids)
    json.dumps(data)  # 能转成 JSON
    assert (data["league"], data["season"], data["computed"]) == (1500, "pvpoke", 4)
    rows = {row["id"]: row for row in data["rows"]}
    assert set(rows) == {"azumarill", "bastiodon_shadow", "froslass_mega"}

    azumarill = rows["azumarill"]
    build = web_api.build_member({"league": 1500, "season": "pvpoke", "member": {
        "species": "azumarill", "fast": "BUBBLE", "charged": ["ICE_BEAM"]}})
    # 和网页上不填 IV、等级时建的配置一样
    assert (azumarill["cp"], azumarill["level"], azumarill["ivs"], azumarill["hp"]) == (
        build["cp"], build["level"], build["ivs"], build["hp"])
    assert azumarill["def"] == pytest.approx(build["def"])
    assert azumarill["bulk"] == azumarill["def"] * azumarill["hp"]
    assert azumarill["stat_product"] == azumarill["atk"] * azumarill["def"] * azumarill["hp"]
    assert azumarill["base"] == [112, 152, 225]
    # 宝可梦的说明和宝可梦列表一样
    catalog = {s["id"]: s for s in web_api.species_catalog(["mega_froslass.toml"], "1500")["species"]}
    for key in ("name", "types", "tags", "released", "custom", "mega", "rank", "mega_rank", "search"):
        assert azumarill[key] == catalog["azumarill"][key]
        assert rows["froslass_mega"][key] == catalog["froslass_mega"][key]
    assert rows["froslass_mega"]["custom"] and rows["bastiodon_shadow"]["shadow"]

    assert [s["id"] for s in data["skipped"]] == ["darkrai"]
    assert data["skipped"][0]["name"] == "Darkrai" and "CP 就超过 1500" in data["skipped"][0]["reason"]
    assert data["shadow_multipliers"] == {"atk": 1.2, "def": 0.83333331}

    # 第二次读缓存
    again = web_api.stat_table_payload("1500", "pvpoke", ["mega_froslass.toml"], cache_dir=tmp_path, species_ids=ids)
    assert again["computed"] == 0 and again["rows"] == data["rows"]


@pytest.mark.parametrize("league, season, custom, message", [
    ("1234", "pvpoke", [], "league 要是 500 / 1500 / 2500 / 10000"),
    (None, "pvpoke", [], "league 要是"),
    ("1500", "nope", [], "season 要是 pvpoke"),
    ("1500", None, [], "season 要是"),
    ("1500", "pvpoke", ["../gamemaster.json"], "data/custom/ 里没有覆盖文件"),
])
def test_stat_table_payload_errors(tmp_path, league, season, custom, message):
    with pytest.raises(ConfigError, match=message):
        web_api.stat_table_payload(league, season, custom, cache_dir=tmp_path, species_ids=["azumarill"])


# ---- 对位分段和过程图（4b） ----


def test_segments_payload(payload, engine_battle):
    battle, result = engine_battle
    expected = json.loads(json.dumps([asdict(s) for s in segments(battle, result)]))
    sent = [{k: v for k, v in s.items() if k not in ("charged_text", "end_text")} for s in payload["segments"]]
    assert sent == expected
    assert [s["end_text"] for s in payload["segments"]] == [
        "Team B 0 回合换人", "Azumarill 倒下", "Registeel 倒下", "Medicham 倒下",
    ]
    assert payload["segments"][0]["charged_text"] == ["ICE_BEAM 挡下", "HYDRO_CANNON 挡下、HYDRO_CANNON 挡下"]


def test_chart_payload(payload, engine_battle):
    battle, result = engine_battle
    chart = payload["chart"]
    turns = result.turns
    assert chart["turns"] == turns
    assert len(chart["elapsed_ms"]) == turns + 1 and chart["elapsed_ms"][0] == 0
    assert chart["elapsed_ms"][-1] == result.elapsed_ms
    lanes = lane_items(result, battle.gm)
    for side in (0, 1):
        data = chart["sides"][side]
        assert data["max_hp"] == list(max_hps(battle)[side])
        assert len(data["active"]) == turns + 1 and data["active"][0] == 0
        for slot, series in enumerate(data["hp"]):
            assert len(series) == turns + 1
            assert series[0] == data["max_hp"][slot]
            assert series[1:] == [s.sides[side].member_hp[slot] for s in result.snapshots]
        for slot, series in enumerate(data["energy"]):
            assert series[0] == 0
            assert series[1:] == [s.sides[side].member_energy[slot] for s in result.snapshots]
        assert data["active"][1:] == [s.sides[side].active for s in result.snapshots]
        assert data["lane"] == json.loads(json.dumps([asdict(item) for item in lanes[side]]))
    assert chart["move_names"]["HYDRO_CANNON"] == "Hydro Cannon"
    assert "switch" not in chart["move_names"]


def test_timeline_has_elapsed_time(payload, engine_battle):
    _, result = engine_battle
    by_turn = {entry["turn"]: entry for entry in payload["timeline"]}
    assert by_turn[result.turns]["elapsed_ms"] == result.elapsed_ms


# ---- 手动对战（4c） ----


def _manual(decisions, side=0):
    return web_api.manual_battle({"config": web_api.example_config(), "side": side, "decisions": decisions})


def _auto_decisions(side=0):
    """自动对战里 TeamPolicy 的每个选择，写成网页发来的样子。"""
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    return [asdict(d) for d in _auto_choices(run_team_battle(battle), side)]


def test_manual_first_question():
    data = json.loads(json.dumps(_manual([])))
    assert data["status"] == "decide" and data["side"] == 0
    question = data["question"]
    assert (question["index"], question["turn"], question["kind"], question["kind_text"]) == (0, 1, "action", "出招")
    assert [o["label"] for o in question["options"]] == ["快招 Bubble", "什么都不做", "换上 Medicham", "换上 Registeel"]
    assert data["events"] == []
    me, them = data["sides"]
    assert (me["name"], me["active"], me["shields"]) == ("Team A", 0, 2)
    azumarill = me["members"][0]
    assert (azumarill["hp"], azumarill["max_hp"], azumarill["energy"]) == (196, 196, 0)
    ice_beam = next(c for c in azumarill["charged"] if c["id"] == "ICE_BEAM")
    assert (ice_beam["energy"], ice_beam["ready"], ice_beam["fast_needed"]) == (55, False, 5)  # Bubble 每次 +11
    hydro = next(c for c in them["members"][0]["charged"] if c["id"] == "HYDRO_CANNON")
    assert (hydro["energy"], hydro["fast_needed"]) == (40, 5)  # Mud Shot 每次 +9


def test_manual_damage_preview():
    damage = _manual([])["damage"]
    assert damage["percents"] == list(range(25, 101))
    assert damage["target_hp"] == 139
    ice_beam = damage["my_charged"]["ICE_BEAM"]
    assert len(ice_beam["damage"]) == 76
    assert ice_beam["damage"] == sorted(ice_beam["damage"])
    # 满 HP 的 Swampert 一个 Ice Beam 打不死
    assert ice_beam["ko_min"] is None and ice_beam["survive_max"] == 100
    assert damage["their_charged"]["HYDRO_CANNON"] == 35


def test_manual_damage_preview_ko_threshold():
    gm = load_gamemaster()
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    a, b = make_teams(battle)
    me, them = a.members[0], b.members[0]
    them.hp = 40
    preview = web_api.damage_preview(me, them, battle.config.rules)
    play_rough = preview["my_charged"]["PLAY_ROUGH"]
    ko, alive = play_rough["ko_min"], play_rough["survive_max"]
    assert ko == alive + 1
    move = gm.get_move("PLAY_ROUGH")
    assert calculate_damage(move, me.damage_side(), them.damage_side(), battle.config.rules, ko / 100) >= 40
    assert calculate_damage(move, me.damage_side(), them.damage_side(), battle.config.rules, alive / 100) < 40


def test_manual_events_hide_decisions_and_reasons():
    decisions = _auto_decisions()[:20]
    data = _manual(decisions)
    assert data["question"]["index"] == 20
    assert data["events"]
    assert all(e["type"] != "decision" for e in data["events"])
    # 开盾的原因（对方的打算）也不给：这时已经有过两次开盾
    shielded = [e for e in data["events"] if e["type"] == "move" and e["data"]["shielded"]]
    assert shielded
    assert all(e["data"].get("shield_reason") is None and "[shield:" not in e["text"] for e in data["events"])


def test_manual_shield_question_hides_the_move():
    decisions = _auto_decisions()
    first_shield = next(i for i, d in enumerate(decisions) if d["kind"] == "shield")
    data = _manual(decisions[:first_shield])
    assert data["question"]["kind"] == "shield"
    assert [o["label"] for o in data["question"]["options"]] == ["开盾", "不开盾"]
    assert data["damage"] is None
    assert not any(e["data"].get("is_charged") for e in data["events"])
    # 对方在场那只的能量显示这一回合开始时的值（已经扣掉大招能量的值会透露是哪一招）
    battle = prepare_team_battle(load_team_battle_config(EXAMPLE))
    game = play_manual(battle, 0, parse_decisions(decisions[:first_shield]))
    before_turn = game.battle.snapshots[-1].sides[1].member_energy[0]
    live = game.battle.teams[1].members[0].energy
    assert live == before_turn - 40  # Hydro Cannon 的能量已经扣掉了
    assert data["sides"][1]["members"][0]["energy"] == before_turn


def test_manual_finished():
    decisions = _auto_decisions(side=1)
    data = json.loads(json.dumps(_manual(decisions, side=1)))
    assert data["status"] == "finished" and data["decisions"] == len(decisions)
    result = data["result"]
    assert (result["result"]["winner"], result["result"]["ratings"]) == (1, [221, 778])  # 和自动对战那一场相同
    assert result["teams"][1]["policy"] == "玩家手动操作"
    assert "Team B 由玩家手动操作" in result["report_markdown"]
    assert result["chart"]["turns"] == 100


def test_manual_errors():
    with pytest.raises(ConfigError, match="网页：side"):
        web_api.manual_battle({"config": web_api.example_config(), "side": 2})
    with pytest.raises(ConfigError, match="网页：缺少 config"):
        web_api.manual_battle({"side": 0})
    with pytest.raises(ConfigError, match="网页：第 1 个决定（第 1 回合，出招）：这里要回答的是出招"):
        _manual([{"kind": "shield", "shield": True}])
    with pytest.raises(ConfigError, match="网页：decisions 要写成列表"):
        web_api.manual_battle({"config": web_api.example_config(), "side": 0, "decisions": {}})
    with pytest.raises(ConfigError, match="不认识的字段 extra"):
        web_api.manual_battle({"config": web_api.example_config(), "side": 0, "extra": 1})


def test_prepared_battle_is_cached():
    a = web_api.prepared_battle(web_api.example_config())
    b = web_api.prepared_battle(web_api.example_config())
    assert a is b
    other = web_api.example_config()
    other["team"][0]["shields"] = 1
    assert web_api.prepared_battle(other) is not a


# ---- 搜索应对（4e） ----


@pytest.fixture(scope="module")
def best_payload():
    """网页搜 Team A 对 Team B 策略的应对，转成 JSON 再读回来。"""
    return json.loads(json.dumps(web_api.best_response({"config": web_api.example_config(), "side": 0})))


def test_best_response_search_summary(best_payload):
    """和命令行 --best-response 同一个搜索（docs/experiments/gl_3v3_best_response.md）：输 221 → 赢 593。"""
    search = best_payload["search"]
    assert (search["side"], search["team"], search["opponent"]) == (0, "Team A", "Team B")
    assert search["baseline"] == {
        "outcome": 0, "rating": 221, "short": "输 221",
        "text": "Team B 赢。评分 221 对 778；剩余 0 只对 3 只；剩余盾 0 对 0；100 回合，对战时间 145 秒（大招每次按 10 秒算）。",
    }
    assert (search["best"]["outcome"], search["best"]["rating"], search["best"]["short"]) == (2, 593, "赢 593")
    assert (search["decisions"], search["examined"], search["changed"], search["trials"]) == (77, 32, 5, 50)


def test_best_response_tried_points(best_payload):
    """试过的每个决定点都在，按搜索的顺序；选项文字和手动对战的按钮一样。"""
    tried = best_payload["tried"]
    assert len(tried) == 32
    assert [(t["turn"], t["kind_text"], t["policy_choice"], t["chosen"]) for t in tried if t["changed"]] == [
        (1, "出招", "快招 Bubble", "换上 Medicham"),
        (11, "开盾", "开盾", "不开盾"),
        (21, "出招", "快招 Counter", "大招 Ice Punch"),
        (62, "0 回合换人", "不换", "换上 Registeel"),
        (99, "0 回合换人", "不换", "换上 Azumarill"),
    ]
    first = tried[0]
    assert (first["before"]["short"], first["after"]["short"]) == ("输 221", "输 465")
    assert [(o["label"], o["score"]["short"], o["policy"], o["chosen"]) for o in first["options"]] == [
        ("快招 Bubble", "输 221", True, False),
        ("换上 Medicham", "输 465", False, True),
        ("换上 Registeel", "输 237", False, False),
    ]
    replacement = next(t for t in tried if t["kind"] == "replacement")
    assert [o["label"] for o in replacement["options"]] == ["换上 Azumarill", "换上 Registeel"]
    for t in tried:
        assert sum(o["policy"] for o in t["options"]) == sum(o["chosen"] for o in t["options"]) == 1
        if not t["changed"]:
            assert t["chosen"] == t["policy_choice"] and t["before"] == t["after"]


def test_best_response_battles(best_payload, payload):
    """搜索后的这一场：和引擎搜出来的一样，报告是 best-response 的报告；原策略那一场和打一场完全相同。"""
    battle = web_api.prepared_battle(web_api.example_config())
    response = search_best_response(battle, 0)
    result = best_payload["result"]
    assert (result["result"]["ratings"], result["result"]["turns"]) == (list(response.best.result.ratings), 116)
    assert result["teams"][0]["policy"] == "逐步试探搜索出来的打法；原策略（起点）是 TeamPolicy，默认参数"
    assert result["teams"][1]["policy"] == "TeamPolicy，默认参数"
    report = result["report_markdown"]
    expected = format_best_response_report(battle, response)
    seconds = re.compile(r"用时 [\d.]+ 秒")
    assert seconds.sub("", report) == seconds.sub("", expected)  # 只有用时不同
    texts = [e["text"] for entry in result["timeline"] for e in entry["events"]]
    assert sum("best response:" in text for text in texts) == 5  # 4 个决定事件，开盾的原因在对方的大招事件里
    assert best_payload["baseline"] == payload


def test_best_response_other_side():
    data = web_api.best_response({"config": web_api.example_config(), "side": 1})
    assert (data["search"]["team"], data["search"]["baseline"]["short"], data["search"]["best"]["short"]) == (
        "Team B", "赢 778", "赢 785",
    )
    assert [(t["turn"], t["policy_choice"], t["chosen"]) for t in data["tried"] if t["changed"]] == [
        (23, "快招 Mud Shot", "大招 Hydro Cannon"),
    ]
    assert data["result"]["teams"][1]["policy"].startswith("逐步试探搜索出来的打法")


def test_best_response_errors():
    with pytest.raises(ConfigError, match="网页：side（搜索哪一方的打法）要是 0 或 1"):
        web_api.best_response({"config": web_api.example_config(), "side": True})
    with pytest.raises(ConfigError, match="网页：缺少 side"):
        web_api.best_response({"config": web_api.example_config()})
    with pytest.raises(ConfigError, match="不认识的字段 extra"):
        web_api.best_response({"config": web_api.example_config(), "side": 0, "extra": 1})
    with pytest.raises(ConfigError, match="网页：要写成表"):
        web_api.best_response([])
    bad = _example()
    bad["team"][0]["member"][0]["species"] = "nope"
    with pytest.raises(ConfigError, match="Team A 第 1 只（nope）：找不到宝可梦"):
        web_api.best_response({"config": bad, "side": 0})


# ---- 队伍库和导入导出（4f） ----


@pytest.fixture
def library_dir(tmp_path, monkeypatch):
    """队伍库换成临时目录（不碰仓库的 teams/）。"""
    monkeypatch.setattr(team_library, "LIBRARY_DIR", tmp_path)
    return tmp_path


def _save_request(team, **extra):
    return {"league": 1500, "season": "pvpoke", "custom_files": [], "team": team} | extra


def test_save_library_team(library_dir):
    team = _example()["team"][0]
    data = web_api.save_library_team(_save_request(team, note="例子"))
    assert data == {"saved": True, "file": "Team_A.toml", "custom_files": []}
    saved = team_library.load_library().teams[0]
    assert (saved.league, saved.note, saved.team) == (1500, "例子", team)

    # 同名的已经有了：不写，告诉网页已有的那一队；带 overwrite 才覆盖
    other = copy.deepcopy(team)
    other["shields"] = 1
    data = web_api.save_library_team(_save_request(other))
    assert (data["saved"], data["existing"]["note"], data["existing"]["league_name"]) == (False, "例子", "超级联盟")
    assert team_library.load_library().teams[0].team == team
    assert web_api.save_library_team(_save_request(other, overwrite=True))["saved"]
    assert team_library.load_library().teams[0].team == other


def test_save_library_team_records_used_custom_files(library_dir):
    """勾着的覆盖文件里，只记这一队用到的。"""
    team = _example()["team"][0]
    team["name"] = "Team A (Mega Froslass)"
    team["member"][2] = {"species": "froslass_mega", "fast": "POWDER_SNOW", "charged": ["AVALANCHE", "SHADOW_BALL", "AVALANCHE_PLUS"]}
    all_files = [f["name"] for f in web_api.options()["custom_files"]]
    data = web_api.save_library_team(_save_request(team, custom_files=all_files))
    assert (data["file"], data["custom_files"]) == ("Team_A_Mega_Froslass.toml", ["mega_froslass.toml"])
    listed = web_api.library_payload()["teams"][0]
    assert (listed["name"], listed["custom_files"], listed["unsupported"]) == (
        "Team A (Mega Froslass)", ["mega_froslass.toml"], [],
    )


def test_save_library_team_checks_like_a_battle(library_dir):
    """建不了配置的不让存：和打一场同一套检查。"""
    team = _example()["team"][0]
    team["member"][1] = copy.deepcopy(team["member"][0])
    with pytest.raises(ConfigError, match="同一种宝可梦不能带两只"):
        web_api.save_library_team(_save_request(team))
    team = _example()["team"][0]
    team["member"][2] = {"species": "froslass_mega", "fast": "POWDER_SNOW", "charged": ["AVALANCHE"]}
    with pytest.raises(ConfigError, match="找不到宝可梦：froslass_mega"):  # 没勾覆盖文件
        web_api.save_library_team(_save_request(team))
    with pytest.raises(ConfigError, match="网页：缺少 team"):
        web_api.save_library_team({"league": 1500, "season": "pvpoke"})
    with pytest.raises(ConfigError, match="overwrite 要写 true / false"):
        web_api.save_library_team(_save_request(_example()["team"][0], overwrite="yes"))
    assert list(library_dir.iterdir()) == []


def test_library_payload(library_dir):
    assert web_api.library_payload() == {"dir": "teams/", "teams": [], "broken": []}
    team = _example()["team"][1] | {"policy": {"switching": "never", "moves": {"bait_shields": False}}}
    team_library.save_team(team_library.LibraryTeam("B.toml", 2500, (), "", team), library_dir)
    (library_dir / "bad.toml").write_text("league = 1500\n", encoding="utf-8")
    data = json.loads(json.dumps(web_api.library_payload()))
    assert [(t["file"], t["name"], t["league_name"], t["unsupported"]) for t in data["teams"]] == [
        ("B.toml", "Team B", "高级联盟", ["moves"]),
    ]
    assert data["teams"][0]["team"] == team
    assert data["broken"] == [{"file": "bad.toml", "error": "teams/bad.toml：缺少 team"}]


def test_export_runs_on_the_command_line(tmp_path):
    """导出的文件就是命令行的 3v3 配置：读回来和页面上的配置打出来完全相同。"""
    raw = _example()
    raw["custom_files"] = ["mega_froslass.toml"]
    raw["team"][0]["shields"] = 1
    raw["team"][0]["policy"] = {"switching": "never"}
    data = web_api.export_team_battle(raw)
    assert data["filename"] == "3v3_Team_A_vs_Team_B.toml"
    assert data["text"].startswith("# 网页导出的 3v3 配置")
    assert "  .venv/bin/python -m tools.run_team_battle 3v3_Team_A_vs_Team_B.toml" in data["text"]
    path = tmp_path / data["filename"]
    path.write_text(data["text"], encoding="utf-8")
    from_file = prepare_team_battle(load_team_battle_config(path))
    from_page = prepare_team_battle(parse_team_battle_config(web_api._with_custom_paths(raw), "网页"))
    assert from_file.config.custom_files == from_page.config.custom_files
    assert run_team_battle(from_file).events == run_team_battle(from_page).events


def test_export_checks_the_config():
    bad = _example()
    bad["team"][1]["name"] = "Team A"
    with pytest.raises(ConfigError, match="两队不能同名"):
        web_api.export_team_battle(bad)


def test_import_roundtrip():
    """导入例子配置文件，得到的就是网页的例子配置；导出再导入不变。"""
    text = EXAMPLE.read_text(encoding="utf-8")
    data = web_api.import_team_battle({"text": text, "name": "gl_3v3_example.toml"})
    assert data["config"] == web_api.example_config()
    assert data["warnings"] == ["说明文字（description）网页上不显示，没有导入"]
    page = _example()
    page["custom_files"] = ["mega_froslass.toml"]
    page["team"][1]["policy"] = {"switching": "never"}
    again = web_api.import_team_battle({"text": web_api.export_team_battle(page)["text"]})
    assert again == {"config": page, "warnings": []}


def test_import_warns_about_settings_the_page_cannot_show():
    text = (
        'league = 1500\nseason = "pvpoke"\n[rules]\ntimeout_result = "rating"\n'
        '[policy]\nswitching = "never"\n[policy.moves]\nbait_shields = false\n'
        + "".join(
            f'[[team]]\nname = "{name}"\n[team.policy]\nstay_hp_fraction = 0.3\n'
            + "".join(f'[[team.member]]\nspecies = "{s}"\nfast = "{f}"\ncharged = ["{c}"]\n' for s, f, c in members)
            for name, members in (
                ("A", [("azumarill", "BUBBLE", "ICE_BEAM"), ("medicham", "COUNTER", "PSYCHIC"), ("registeel", "LOCK_ON", "FOCUS_BLAST")]),
                ("B", [("swampert", "MUD_SHOT", "EARTHQUAKE"), ("altaria", "DRAGON_BREATH", "MOONBLAST"), ("trevenant", "SHADOW_CLAW", "SEED_BOMB")]),
            )
        )
    )
    data = web_api.import_team_battle({"text": text})
    assert [team["policy"] for team in data["config"]["team"]] == [{"switching": "never"}] * 2  # 共用的 switching 合并进来
    assert "rules" not in data["config"] and "policy" not in data["config"]
    assert data["warnings"] == [
        "机制规则 [rules] 网页上改不了，没有导入：timeout_result",
        "A 的策略参数网页上改不了（只能改盾数和主动换不换人），没有导入：moves、stay_hp_fraction",
        "B 的策略参数网页上改不了（只能改盾数和主动换不换人），没有导入：moves、stay_hp_fraction",
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("league = [", "导入的文件 x.toml：不是合法的 TOML"),
        ('league = 1500\nseason = "pvpoke"\n', "导入的文件 x.toml：缺少 team"),
        (
            'custom_files = ["experiments/x.toml"]\n'
            + EXAMPLE.read_text(encoding="utf-8").split("description")[0]
            + 'league = 1500\nseason = "pvpoke"\n' + EXAMPLE.read_text(encoding="utf-8").split('season = "pvpoke"', 1)[1],
            "网页只能用 data/custom/ 里的覆盖文件",
        ),
    ],
)
def test_import_errors(text, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        web_api.import_team_battle({"text": text, "name": "x.toml"})


# ---- 1v1 九宫格和环境前 N（4g） ----

MATCHUP_EXAMPLE = REPO_ROOT / "experiments" / "gl_mega_froslass_top.toml"


def _small_matchups() -> dict:
    """小配置（网页的格式）：两个测试对象，一个手写的对手，Mega 前 2、非 Mega 前 3（同 tests/test_matchup_pools.py）。"""
    raw = tomllib.loads(POOL_CONFIG + EXPLICIT_OPPONENT)
    raw["custom_files"] = ["mega_froslass.toml"]
    return raw


@pytest.fixture(scope="module")
def cli_matchups(tmp_path_factory):
    """同一个配置写成文件、用命令行的读法跑一遍（对照用）。"""
    path = tmp_path_factory.mktemp("matchups") / "small.toml"
    path.write_text(POOL_CONFIG + EXPLICIT_OPPONENT, encoding="utf-8")
    prepared = prepare_matchups(load_matchup_config(path))
    return prepared, run_all(prepared), run_pools(prepared)


@pytest.fixture(scope="module")
def matchup_payload():
    """网页跑的同一个配置，转成 JSON 再读回来。"""
    return json.loads(json.dumps(web_api.matchups(_small_matchups())))


def test_matchup_options():
    options = web_api.matchup_options()
    assert [(p["key"], p["default"]) for p in options["policy"]] == [
        (f.name, f.default) for f in fields(SimplePolicyConfig)
    ]
    types = {p["key"]: p["type"] for p in options["policy"]}
    assert types == {
        "charged_move_choice": "choice", "optimize_timing": "bool", "bait_shields": "bool",
        "shielding": "choice", "shield_hp_fraction": "number",
    }
    shielding = next(p for p in options["policy"] if p["key"] == "shielding")
    assert [c["key"] for c in shielding["choices"]] == ["always", "never", "when_low"]
    assert options["pool"]["available"] == {500: [], 1500: ["all", "mega"], 2500: ["all", "mega"], 10000: ["all", "mega"]}
    assert [k["key"] for k in options["pool"]["kinds"]] == ["mega", "non_mega"]
    assert options["shield_counts"] == [0, 1, 2] and options["win_rating"] == 500
    # 例子配置：网页的格式（覆盖文件写文件名），检查以后和配置文件完全相同
    example = options["example"]
    assert example["custom_files"] == ["mega_froslass.toml"]
    assert parse_matchup_config(web_api._with_custom_paths(example), "网页") == load_matchup_config(MATCHUP_EXAMPLE)


def test_matchups_same_as_command_line(matchup_payload, cli_matchups):
    """网页跑出来的九宫格、报告、CSV 和命令行完全相同。"""
    prepared, grids, pool_grids = cli_matchups
    data = matchup_payload
    assert data["report_markdown"] == format_report(prepared, grids, pool_grids=pool_grids)
    assert data["csv"] == format_csv(prepared, grids, pool_grids)
    assert data["battles"] == 9 * 2 * (1 + 2 + 3)
    # 手写的对手：grids[测试对象][对手]
    assert [[cell["ratings"] for cell in row] for row in data["grids"]] == [
        [[list(r) for r in g.ratings]] for g in grids
    ]
    assert data["grids"][0][0]["wins"] == grids[0].wins
    assert data["grids"][0][0]["average"] == pytest.approx(grids[0].average)
    for pool, pg in zip(data["pools"], pool_grids):
        assert pool["name"] == pg.pool.spec.name
        assert pool["description"] == pg.pool.spec.describe(1500)
        assert [m["rank"] for m in pool["members"]] == [m.ranked.rank for m in pg.pool.members]
        assert [m["label"] for m in pool["members"]] == [p.label for p in pg.pool.participants]
        for subject_cells, subject_grids, summary in zip(pool["grids"], pg.by_subject, pool["summary"]):
            assert [cell["ratings"] for cell in subject_cells] == [[list(r) for r in g.ratings] for g in subject_grids]
            assert summary == json.loads(json.dumps(asdict(pool_summary(subject_grids))))


def test_matchups_participants(matchup_payload, cli_matchups):
    prepared, _, _ = cli_matchups
    subjects = matchup_payload["subjects"]
    assert [s["marked"] for s in subjects] == ["Mega Froslass", "Froslass"]
    expected = web_api._member_info(prepared.gm, prepared.subjects[0])
    assert subjects[0] == json.loads(json.dumps(expected | {"marked": "Mega Froslass"}))
    assert [o["label"] for o in matchup_payload["opponents"]] == ["Azumarill"]
    assert matchup_payload["settings"]["policy"] == asdict(SimplePolicyConfig())
    assert matchup_payload["pools"][0]["members"][0]["score"] > 0


def test_pools_are_cached(monkeypatch):
    """建好的环境前 N 缓存起来：改测试对象、改这一组的名字都不用重建；改了这一组的设置才重建。"""
    built = []
    original = web_api.prepare_pool

    def counting(gm, spec, league, season):
        built.append(spec.top)
        return original(gm, spec, league, season)

    monkeypatch.setattr(web_api, "prepare_pool", counting)
    monkeypatch.setattr(web_api, "_POOL_CACHE", web_api.OrderedDict())
    web_api._matchups_from_key.cache_clear()

    raw = _small_matchups()
    web_api.matchups(raw)
    assert built == [2, 3]
    raw["subject"] = raw["subject"][:1]
    web_api.matchups(raw)
    raw["opponent_pool"][0]["name"] = "新名字"
    data = web_api.matchups(raw)
    assert built == [2, 3]
    assert data["pools"][0]["name"] == "新名字" and "## 环境前 N：新名字" in data["report_markdown"]
    raw["opponent_pool"][1]["top"] = 4
    web_api.matchups(raw)
    assert built == [2, 3, 4]
    web_api._matchups_from_key.cache_clear()


def test_prepared_matchups_is_cached():
    a = web_api.prepared_matchups(_small_matchups())
    assert web_api.prepared_matchups(_small_matchups()) is a
    other = _small_matchups()
    other["subject"][0]["ivs"] = [0, 15, 15]
    assert web_api.prepared_matchups(other) is not a


def _battle(pool, opponent, shields, subject=0, raw=None):
    request = {"config": raw or _small_matchups(), "subject": subject, "pool": pool, "opponent": opponent, "shields": shields}
    return json.loads(json.dumps(web_api.matchup_battle(request)))


@pytest.mark.parametrize(("pool", "opponent", "shields"), [(None, 0, [2, 2]), (0, 1, [1, 0]), (1, 2, [0, 2])])
def test_matchup_battle_is_that_cell(matchup_payload, cli_matchups, pool, opponent, shields):
    """点一格看的一场：评分就是那一格；过程图、时间线和直接打这一场相同。"""
    prepared, _, _ = cli_matchups
    data = _battle(pool, opponent, shields)
    cells = matchup_payload["grids"] if pool is None else matchup_payload["pools"][pool]["grids"]
    assert data["result"]["ratings"][0] == cells[0][opponent]["ratings"][shields[0]][shields[1]]

    group = prepared.opponents if pool is None else prepared.pools[pool].participants
    subject, other = prepared.subjects[0], group[opponent]
    sides = make_sides(prepared, subject, other, *shields)
    hps = ((sides[0].active_member.stats.hp,), (sides[1].active_member.stats.hp,))
    result = fight(prepared, sides)
    names = battle_names(subject, other)
    assert data["result"] == json.loads(json.dumps(web_api.result_payload(result)))
    assert data["chart"] == json.loads(json.dumps(web_api.chart_payload(prepared.gm, hps, result)))
    assert data["timeline"] == json.loads(json.dumps(web_api.timeline_payload(result, ((names[0],), (names[1],)))))
    assert [t["name"] for t in data["teams"]] == list(names)
    assert [t["shields"] for t in data["teams"]] == shields
    assert data["teams"][1]["members"][0]["label"] == other.label
    assert data["outcome"].startswith(("Mega Froslass 赢", f"{other.label} 赢", "平局"))


def test_matchup_battle_mirror_names():
    raw = _small_matchups()
    raw["opponent"][0] = {"species": "froslass", "fast": "POWDER_SNOW", "charged": ["AVALANCHE", "SHADOW_BALL"]}
    data = _battle(None, 0, [1, 1], subject=1, raw=raw)
    assert [t["name"] for t in data["teams"]] == ["Froslass（测试对象）", "Froslass（对手）"]
    assert data["chart"]["sides"][0]["max_hp"] == data["chart"]["sides"][1]["max_hp"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"subject": 2}, "subject 要写第几个测试对象（0 到 1），得到 2"),
        ({"subject": True}, "subject 要写第几个测试对象"),
        ({"pool": 2}, "pool 要写第几个环境前 N（0 到 1），得到 2"),
        ({"opponent": 1}, "opponent 要写第几个对手（0 到 0），得到 1"),
        ({"pool": 1, "opponent": -1}, "opponent 要写第几个对手（0 到 2）"),
        ({"shields": [3, 0]}, "shields 要写 [测试对象的盾数, 对手的盾数]"),
        ({"shields": [True, 0]}, "shields 要写"),
        ({"shields": [1.0, 0]}, "shields 要写"),
        ({"shields": 1}, "shields 要写"),
        ({"extra": 1}, "不认识的字段 extra"),
    ],
)
def test_matchup_battle_errors(change, message):
    request = {"config": _small_matchups(), "subject": 0, "pool": None, "opponent": 0, "shields": [1, 1]} | change
    with pytest.raises(ConfigError, match=re.escape(message)):
        web_api.matchup_battle(request)


def test_matchup_battle_without_handwritten_opponents():
    raw = _small_matchups()
    del raw["opponent"]
    with pytest.raises(ConfigError, match="没有手写的对手"):
        web_api.matchup_battle({"config": raw, "subject": 0, "pool": None, "opponent": 0, "shields": [1, 1]})
    with pytest.raises(ConfigError, match="缺少 config"):
        web_api.matchup_battle({"subject": 0})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda raw: raw.pop("subject"), "^网页：缺少 subject$"),
        (lambda raw: raw.update(custom_files=["../x.toml"]), "data/custom/ 里没有覆盖文件"),
        (lambda raw: raw["subject"][0].update(species="nope"), "测试对象第 1 项（Mega Froslass）"),
        (lambda raw: raw.update(policy={"shielding": "sometimes"}), "shielding"),
        (lambda raw: raw.update(league=500), "环境前 N（Mega 前 2）"),
    ],
)
def test_matchups_errors(change, message):
    raw = _small_matchups()
    change(raw)
    with pytest.raises(ConfigError, match=message):
        web_api.matchups(raw)


def test_export_matchups_runs_on_the_command_line(tmp_path, cli_matchups):
    """导出的文件就是命令行的九宫格配置：读回来和页面上的配置相同，跑出来的报告也相同。"""
    raw = _small_matchups()
    data = web_api.export_matchups(raw)
    assert data["filename"] == "1v1_Mega_Froslass_and_1_more.toml"
    assert data["text"].startswith("# 网页导出的 1v1 九宫格配置（格式见 pogo_sim/matchups.py 开头）")
    assert "  .venv/bin/python -m tools.run_matchups 1v1_Mega_Froslass_and_1_more.toml" in data["text"]
    assert "[policy]" not in data["text"]  # 没写策略参数时不写空表
    path = tmp_path / data["filename"]
    path.write_text(data["text"], encoding="utf-8")
    assert load_matchup_config(path) == parse_matchup_config(web_api._with_custom_paths(raw), "网页")
    prepared, grids, pool_grids = cli_matchups
    from_file = prepare_matchups(load_matchup_config(path))
    assert format_report(from_file, run_all(from_file), pool_grids=run_pools(from_file)) == format_report(
        prepared, grids, pool_grids=pool_grids
    )

    raw["policy"] = {"bait_shields": False}
    raw["subject"] = raw["subject"][1:]
    data = web_api.export_matchups(raw)
    assert data["filename"] == "1v1_Froslass.toml"
    assert "\n[policy]\nbait_shields = false\n" in data["text"]


def test_export_matchups_checks_the_config():
    raw = _small_matchups()
    raw["subject"][1]["label"] = "Mega Froslass"
    with pytest.raises(ConfigError, match="测试对象里有重名的 Mega Froslass"):
        web_api.export_matchups(raw)


def test_import_matchups_roundtrip():
    """导入例子配置文件，得到的就是网页的例子配置；导出再导入不变。"""
    text = MATCHUP_EXAMPLE.read_text(encoding="utf-8")
    assert web_api.import_matchups({"text": text, "name": MATCHUP_EXAMPLE.name}) == {"config": web_api.example_matchups()}
    page = _small_matchups()
    page["policy"] = {"shielding": "when_low", "shield_hp_fraction": 0.3}
    assert web_api.import_matchups({"text": web_api.export_matchups(page)["text"]}) == {"config": page}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("league = [", "导入的文件 x.toml：不是合法的 TOML"),
        ('league = 1500\nseason = "pvpoke"\n', "导入的文件 x.toml：缺少 subject"),
        (
            'custom_files = ["experiments/x.toml"]\n' + POOL_CONFIG.replace('custom_files = ["data/custom/mega_froslass.toml"]', ""),
            "网页只能用 data/custom/ 里的覆盖文件",
        ),
    ],
)
def test_import_matchups_errors(text, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        web_api.import_matchups({"text": text, "name": "x.toml"})


# ---- 队伍对队伍（4h） ----

MATRIX_EXAMPLE = REPO_ROOT / "experiments" / "gl_team_matrix_example.toml"


def _small_matrix() -> dict:
    """例子配置（网页的格式），只抽 3 队：我方 2 队 × 对手 4 队（Team B 和抽样 1–3），同 tests/test_team_matrix.py。"""
    raw = web_api.example_matrix()
    raw["opponent_sample"]["count"] = 3
    return raw


@pytest.fixture(scope="module")
def cli_matrix(tmp_path_factory):
    """同一个配置写成文件、用命令行的读法跑一遍（对照用）。"""
    path = tmp_path_factory.mktemp("matrix") / "small.toml"
    path.write_text(MATRIX_EXAMPLE.read_text(encoding="utf-8").replace("count = 50", "count = 3", 1), encoding="utf-8")
    matrix = team_matrix.prepare_team_matrix(team_matrix.load_team_matrix_config(path))
    return matrix, team_matrix.run_team_matrix(matrix)


@pytest.fixture(scope="module")
def matrix_events():
    """网页跑的同一个配置：每一项转成 JSON 再读回来（浏览器收到的就是这样）。"""
    return [json.loads(json.dumps(event)) for event in web_api.team_matrix_stream(_small_matrix())]


def test_matrix_options():
    options = web_api.matrix_options()
    assert options["pool"] == web_api.matchup_options()["pool"]
    example = options["example"]
    assert example["custom_files"] == ["mega_froslass.toml"]
    from_page = team_matrix.parse_team_matrix_config(web_api._with_custom_paths(example), "网页")
    assert from_page == team_matrix.load_team_matrix_config(MATRIX_EXAMPLE)
    # 打开"随机抽"时先填的值本身就是一个能用的 [opponent_sample]
    raw = example | {"opponent_sample": options["sample_defaults"]}
    assert team_matrix.parse_team_matrix_config(web_api._with_custom_paths(raw), "网页").sample == from_page.sample


def test_matrix_stream_same_as_command_line(matrix_events, cli_matrix):
    """边打边发的结果和命令行完全相同：每一场、总表、报告、CSV。"""
    matrix, results = cli_matrix
    start, *progress, done = matrix_events
    assert start["type"] == "start" and done["type"] == "done"
    assert {e["type"] for e in progress} == {"progress"}
    assert start["total"] == 8
    assert [t["name"] for t in start["teams"]] == ["Team A", "Team A (Mega Froslass)"]
    assert [t["name"] for t in start["opponents"]] == ["Team B", "抽样 1", "抽样 2", "抽样 3"]
    assert [t["group"] for t in start["opponents"]] == ["手写", "抽样", "抽样", "抽样"]
    assert start["opponents"][1]["member_names"] == ["Corsola (Galarian) #11", "Rillaboom #26", "Malamar (Mega) #32"]
    assert start["opponents"][1]["members"][0] == json.loads(json.dumps(
        web_api._member_info(matrix.gm, matrix.opponents[1].members[0])))
    assert start["sample"]["description"] == matrix.sample.spec.describe(1500, 3)
    assert [c["name"] for c in start["sample"]["candidates"]] == ["非 Mega 前 30", "Mega 前 10"]

    sent = [r for e in progress for r in e["results"]]
    assert [(r["team"], r["opponent"]) for r in sent] == [(i, j) for i in range(2) for j in range(4)]
    assert progress[-1]["done"] == 8 and all(a["done"] < b["done"] for a, b in zip(progress, progress[1:]))
    for r in sent:
        expected = web_api.matrix_result_payload(results[r["team"]][r["opponent"]])
        assert {k: v for k, v in r.items() if k not in ("team", "opponent")} == json.loads(json.dumps(expected))
    assert sent[4]["outcome"] == "赢" and sent[4]["ratings"] == [566, 433]

    assert done["report_markdown"] == team_matrix.format_report(matrix, results)
    assert done["csv"] == team_matrix.format_csv(matrix, results)
    assert done["summary"][0] == {"team": 0, "group": "手写", "battles": 1, "wins": 0, "draws": 0, "losses": 1,
                                  "mean_rating": 221.0, "mean_remaining": [0.0, 3.0]}
    assert [(s["team"], s["group"]) for s in done["summary"]] == [
        (i, g) for i in range(2) for g in ("手写", "抽样", "全部")
    ]


def test_matrix_stream_batches(monkeypatch):
    """每隔 MATRIX_PROGRESS_SECONDS 发一批；设成 0 就一场一批。"""
    monkeypatch.setattr(web_api, "MATRIX_PROGRESS_SECONDS", 0)
    events = list(web_api.team_matrix_stream(_small_matrix()))
    assert [len(e["results"]) for e in events if e["type"] == "progress"] == [1] * 8


def test_matrix_stream_stops_when_closed(monkeypatch):
    """不再往下取（网页点"停止"、服务器关掉迭代器）就不再打。"""
    played = []
    original = team_matrix.run_team_battle

    def counting(battle, evaluators=None):
        played.append(battle.teams[1].setup.name)
        return original(battle, evaluators)

    monkeypatch.setattr(team_matrix, "run_team_battle", counting)
    monkeypatch.setattr(web_api, "MATRIX_PROGRESS_SECONDS", 0)
    events = web_api.team_matrix_stream(_small_matrix())
    assert next(events)["type"] == "start"
    assert next(events)["done"] == 1
    events.close()
    assert played == ["Team B"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda raw: raw.pop("team"), "^网页：缺少 team$"),
        (lambda raw: raw["team"][1].update(name="Team B"), "队伍名字不能重复：Team B"),
        (lambda raw: raw["opponent_sample"].update(count=0), "count 要写正整数"),
        (lambda raw: raw.update(league=500), "opponent_sample"),
        (lambda raw: raw["team"][0]["member"][0].update(species="nope"), "Team A 第 1 只（nope）"),
    ],
)
def test_matrix_stream_config_errors(change, message):
    """写错的配置在开始发之前就报错（服务器回 400）。"""
    raw = _small_matrix()
    change(raw)
    with pytest.raises(ConfigError, match=message):
        web_api.team_matrix_stream(raw)


def test_prepared_matrix_is_cached():
    a = web_api.prepared_matrix(_small_matrix())
    assert web_api.prepared_matrix(_small_matrix()) is a
    other = _small_matrix()
    other["opponent_sample"]["seed"] = 2
    assert web_api.prepared_matrix(other) is not a


@pytest.mark.parametrize(("team", "opponent"), [(0, 0), (1, 3)])
def test_matrix_battle(cli_matrix, team, opponent):
    """点一场看的就是命令行 --battle 打的那一场：结果、完整报告。"""
    matrix, results = cli_matrix
    data = json.loads(json.dumps(web_api.matrix_battle({"config": _small_matrix(), "team": team, "opponent": opponent})))
    battle = team_matrix.pairing(matrix, matrix.teams[team], matrix.opponents[opponent])
    assert data["result"] == json.loads(json.dumps(web_api.result_payload(results[team][opponent])))
    assert data["report_markdown"] == format_team_battle_report(battle, results[team][opponent])
    assert [t["name"] for t in data["teams"]] == [matrix.teams[team].name, matrix.opponents[opponent].name]
    assert data["chart"]["turns"] == results[team][opponent].turns


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"team": 2}, "team 要写第几个我方队伍（0 到 1），得到 2"),
        ({"opponent": 4}, "opponent 要写第几个对手队伍（0 到 3），得到 4"),
        ({"opponent": None}, "opponent 要写第几个对手队伍"),
        ({"extra": 1}, "不认识的字段 extra"),
    ],
)
def test_matrix_battle_errors(change, message):
    request = {"config": _small_matrix(), "team": 0, "opponent": 0} | change
    with pytest.raises(ConfigError, match=re.escape(message)):
        web_api.matrix_battle(request)
    with pytest.raises(ConfigError, match="缺少 config"):
        web_api.matrix_pairing_config({"team": 0, "opponent": 0})


@pytest.mark.parametrize("opponent", [0, 1, 2, 3])
def test_matrix_pairing_config_replays_the_same_battle(cli_matrix, opponent):
    """送到"打一场"页的配置（随机抽的队伍也写成每只的配置）打出来和队伍对队伍里的那一场完全相同。"""
    matrix, results = cli_matrix
    data = web_api.matrix_pairing_config({"config": _small_matrix(), "team": 1, "opponent": opponent})
    assert data["warnings"] == []
    config = data["config"]
    assert (config["league"], config["season"], config["custom_files"]) == (1500, "pvpoke", ["mega_froslass.toml"])
    assert [t["name"] for t in config["team"]] == ["Team A (Mega Froslass)", matrix.opponents[opponent].name]
    battle = prepare_team_battle(parse_team_battle_config(web_api._with_custom_paths(config), "网页"))
    assert run_team_battle(battle).events == results[1][opponent].events


def test_matrix_pairing_config_warns_about_policies():
    raw = _small_matrix()
    raw["team"][0]["policy"] = {"switching": "never", "stay_hp_fraction": 0.3}
    data = web_api.matrix_pairing_config({"config": raw, "team": 0, "opponent": 0})
    assert data["config"]["team"][0]["policy"] == {"switching": "never"}
    assert data["warnings"] == ["Team A 的策略参数“打一场”页上改不了（只能改盾数和主动换不换人），没有带过去"]


def test_export_matrix_runs_on_the_command_line(tmp_path):
    raw = _small_matrix()
    raw["team"][0]["policy"] = {"switching": "never"}
    data = web_api.export_matrix(raw)
    assert data["filename"] == "matrix_Team_A_and_1_more.toml"
    assert data["text"].startswith("# 网页导出的队伍对队伍配置（格式见 pogo_sim/team_matrix.py 开头）")
    assert "  .venv/bin/python -m tools.run_team_matrix matrix_Team_A_and_1_more.toml" in data["text"]
    path = tmp_path / data["filename"]
    path.write_text(data["text"], encoding="utf-8")
    assert team_matrix.load_team_matrix_config(path) == team_matrix.parse_team_matrix_config(
        web_api._with_custom_paths(raw), "网页")


def test_import_matrix_roundtrip():
    """导入例子配置文件，得到的就是网页的例子配置；导出再导入不变。"""
    text = MATRIX_EXAMPLE.read_text(encoding="utf-8")
    assert web_api.import_matrix({"text": text}) == {"config": web_api.example_matrix(), "warnings": []}
    page = _small_matrix()
    page["opponent_sample"]["policy"] = {"switching": "never"}
    page["opponent_team"][0]["shields"] = 1
    assert web_api.import_matrix({"text": web_api.export_matrix(page)["text"]}) == {"config": page, "warnings": []}


def test_import_matrix_warns_about_settings_the_page_cannot_show():
    text = MATRIX_EXAMPLE.read_text(encoding="utf-8").replace(
        "seed = 1", 'seed = 1\n[opponent_sample.policy]\nstay_hp_fraction = 0.3', 1
    ) + '\n[rules]\ntimeout_result = "rating"\n[policy]\nswitching = "never"\n'
    data = web_api.import_matrix({"text": text, "name": "x.toml"})
    config = data["config"]
    assert "rules" not in config and "policy" not in config
    assert [t["policy"] for t in config["team"]] == [{"switching": "never"}] * 2  # 共用的 switching 合并进来
    assert config["opponent_sample"]["policy"] == {"switching": "never"}
    assert data["warnings"] == [
        "机制规则 [rules] 网页上改不了，没有导入：timeout_result",
        "随机抽的队伍 的策略参数网页上改不了（只能改盾数和主动换不换人），没有导入：stay_hp_fraction",
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("league = [", "导入的文件 x.toml：不是合法的 TOML"),
        ('league = 1500\nseason = "pvpoke"\n', "导入的文件 x.toml：缺少 team"),
        (MATRIX_EXAMPLE.read_text(encoding="utf-8").replace("data/custom/mega_froslass.toml", "experiments/x.toml"),
         "网页只能用 data/custom/ 里的覆盖文件"),
    ],
)
def test_import_matrix_errors(text, message):
    with pytest.raises(ConfigError, match=re.escape(message)):
        web_api.import_matrix({"text": text, "name": "x.toml"})

