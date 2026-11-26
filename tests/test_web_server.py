"""本地网页服务器（tools/run_web.py）：起一个真的服务器，用标准库 urllib 请求。

服务器只做转发，这里核对：网页文件能拿到、web/ 以外的文件拿不到、接口回 JSON、
配置写错回 400 和中文说明、只监听本机。
"""

import http.client
import json
import re
import threading
import time
import urllib.error
import urllib.request

import pytest

from pogo_sim import team_library, team_matrix, web_api
from tools.run_web import HOST, WEB_DIR, make_server


@pytest.fixture(scope="module")
def base_url():
    server = make_server(0)  # 系统挑一个空闲端口
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{HOST}:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def request(url: str, body: bytes | None = None) -> tuple[int, str, bytes]:
    """返回（状态码、Content-Type、内容）。body 不是 None 时 POST。"""
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.headers["Content-Type"], response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], e.read()


def post_json(url: str, payload) -> tuple[int, dict]:
    status, content_type, body = request(url, json.dumps(payload).encode("utf-8"))
    assert content_type == "application/json; charset=utf-8"
    return status, json.loads(body)


def test_listens_on_localhost_only():
    server = make_server(0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_static_files(base_url):
    status, content_type, body = request(f"{base_url}/")
    assert status == 200 and content_type.startswith("text/html")
    assert b'<script src="app.js"></script>' in body
    status, content_type, _ = request(f"{base_url}/app.js")
    assert status == 200 and content_type.startswith("text/javascript")
    status, content_type, _ = request(f"{base_url}/style.css")
    assert status == 200 and content_type.startswith("text/css")
    status, content_type, body = request(f"{base_url}/stats.html")
    assert status == 200 and content_type.startswith("text/html")
    assert b'<script src="common.js"></script>' in body and b'<script src="stats.js"></script>' in body
    status, content_type, body = request(f"{base_url}/matchups.html")
    assert status == 200 and content_type.startswith("text/html")
    for name in ("common.js", "editor.js", "battle_view.js", "library.js", "matchups.js"):
        assert f'<script src="{name}"></script>'.encode() in body
    status, content_type, body = request(f"{base_url}/matrix.html")
    assert status == 200 and content_type.startswith("text/html")
    for name in ("common.js", "editor.js", "battle_view.js", "library.js", "matrix.js"):
        assert f'<script src="{name}"></script>'.encode() in body
    for name in ("common.js", "stats.js", "editor.js", "battle_view.js", "library.js", "matchups.js", "matrix.js"):
        status, content_type, _ = request(f"{base_url}/{name}")
        assert status == 200 and content_type.startswith("text/javascript")


PAGES = ("index.html", "matchups.html", "matrix.html", "stats.html")


@pytest.mark.parametrize("page", PAGES)
def test_pages_link_each_other_and_load_existing_scripts(page):
    """每一页的导航都有全部几页（当前页标出来），页面加载的脚本和样式都在 web/ 里。"""
    html = (WEB_DIR / page).read_text(encoding="utf-8")
    nav = re.search(r'<nav class="pages">(.*?)</nav>', html).group(1)
    assert re.findall(r'href="([^"]+)"', nav) == list(PAGES)
    assert re.findall(r'<a class="current" href="([^"]+)"', nav) == [page]
    for src in re.findall(r'<script src="([^"]+)"></script>', html) + re.findall(r'<link rel="stylesheet" href="([^"]+)">', html):
        assert (WEB_DIR / src).is_file(), src


@pytest.mark.parametrize("path", [
    "/missing.js",
    "/../README.md",
    "/%2e%2e/README.md",
    "/..%2fREADME.md",
    "/index.html/../../README.md",
    "/web/app.js",
    "/README.md",
])
def test_files_outside_web_dir_not_served(base_url, path):
    status, _, _ = request(f"{base_url}{path}")
    assert status == 404


def test_options(base_url):
    status, content_type, body = request(f"{base_url}/api/options")
    assert status == 200 and content_type == "application/json; charset=utf-8"
    assert json.loads(body) == web_api.options()


def test_species(base_url):
    status, _, body = request(f"{base_url}/api/species?league=1500&custom=mega_froslass.toml")
    assert status == 200
    species = {s["id"]: s for s in json.loads(body)["species"]}
    assert species["froslass_mega"]["custom"]
    assert species["azumarill"]["recommended"] == ["BUBBLE", "ICE_BEAM", "PLAY_ROUGH"]

    status, _, body = request(f"{base_url}/api/species?custom=../gamemaster.json")
    assert status == 400 and "data/custom/ 里没有覆盖文件" in json.loads(body)["error"]


def test_team_battle(base_url):
    status, data = post_json(f"{base_url}/api/team-battle", web_api.example_config())
    assert status == 200
    assert (data["result"]["winner"], data["result"]["ratings"], data["result"]["turns"]) == (1, [221, 778], 100)


def test_stats_errors(base_url):
    # 正常的请求要算全部宝可梦（或读 .cache/），在 test_web_api.py 里只算几只来测；这里只测写错时回 400
    status, _, body = request(f"{base_url}/api/stats?league=1500&season=nope")
    assert status == 400 and "season 要是" in json.loads(body)["error"]
    status, _, body = request(f"{base_url}/api/stats?league=1234&season=pvpoke")
    assert status == 400 and "league 要是" in json.loads(body)["error"]


def test_build(base_url):
    member = {"species": "azumarill", "fast": "BUBBLE", "charged": ["ICE_BEAM", "PLAY_ROUGH"]}
    status, data = post_json(f"{base_url}/api/build", {"league": 1500, "season": "pvpoke", "member": member})
    assert status == 200 and (data["cp"], data["level"]) == (1499, 45.5)


def test_config_error_is_400_with_message(base_url):
    raw = web_api.example_config()
    raw["team"][1]["name"] = "Team A"
    status, data = post_json(f"{base_url}/api/team-battle", raw)
    assert status == 400
    assert data == {"error": "网页：两队不能同名（Team A）"}


def test_bad_requests(base_url):
    status, _, body = request(f"{base_url}/api/team-battle", b"{not json")
    assert status == 400 and "不是合法的 JSON" in json.loads(body)["error"]

    status, data = post_json(f"{base_url}/api/nope", {})
    assert status == 404 and "POST /api/nope" in data["error"]

    status, _, body = request(f"{base_url}/api/nope")
    assert status == 404 and "GET /api/nope" in json.loads(body)["error"]


def test_manual_battle(base_url):
    status, data = post_json(f"{base_url}/api/manual-battle", {"config": web_api.example_config(), "side": 0, "decisions": []})
    assert status == 200 and data["status"] == "decide" and data["question"]["turn"] == 1
    status, data = post_json(
        f"{base_url}/api/manual-battle",
        {"config": web_api.example_config(), "side": 0, "decisions": [{"kind": "shield", "shield": True}]},
    )
    assert status == 400 and "这里要回答的是出招" in data["error"]


def test_best_response(base_url):
    status, data = post_json(f"{base_url}/api/best-response", {"config": web_api.example_config(), "side": 0})
    assert status == 200 and data["search"]["changed"] == 5 and data["result"]["result"]["winner"] == 0
    status, data = post_json(f"{base_url}/api/best-response", {"config": web_api.example_config(), "side": 3})
    assert status == 400 and "side" in data["error"]


def test_team_library(base_url, tmp_path, monkeypatch):
    monkeypatch.setattr(team_library, "LIBRARY_DIR", tmp_path)  # 不碰仓库的 teams/
    status, _, body = request(f"{base_url}/api/team-library")
    assert status == 200 and json.loads(body)["teams"] == []
    team = web_api.example_config()["team"][0]
    save = {"league": 1500, "season": "pvpoke", "team": team}
    status, data = post_json(f"{base_url}/api/team-library/save", save)
    assert status == 200 and data["saved"] and (tmp_path / "Team_A.toml").is_file()
    status, data = post_json(f"{base_url}/api/team-library/save", save)
    assert status == 200 and not data["saved"] and data["existing"]["name"] == "Team A"
    status, _, body = request(f"{base_url}/api/team-library")
    assert [t["file"] for t in json.loads(body)["teams"]] == ["Team_A.toml"]
    status, data = post_json(f"{base_url}/api/team-library/save", {"league": 1500, "season": "pvpoke"})
    assert status == 400 and "缺少 team" in data["error"]


def test_export_and_import(base_url):
    status, exported = post_json(f"{base_url}/api/export-config", web_api.example_config())
    assert status == 200 and exported["filename"] == "3v3_Team_A_vs_Team_B.toml"
    status, imported = post_json(f"{base_url}/api/import-config", {"text": exported["text"]})
    assert status == 200 and imported == {"config": web_api.example_config(), "warnings": []}
    status, data = post_json(f"{base_url}/api/import-config", {"text": "league = ["})
    assert status == 400 and "不是合法的 TOML" in data["error"]


def test_matchups(base_url):
    """1v1 九宫格（4g）：选项、跑九宫格、看一场、导出再导入、写错回 400。"""
    from tests.test_web_api import _small_matchups

    status, _, body = request(f"{base_url}/api/matchup-options")
    assert status == 200 and json.loads(body)["example"] == web_api.example_matchups()
    raw = _small_matchups()
    status, data = post_json(f"{base_url}/api/matchups", raw)
    assert status == 200 and data["battles"] == 108
    cell = data["pools"][1]["grids"][0][2]["ratings"][1][1]
    battle = {"config": raw, "subject": 0, "pool": 1, "opponent": 2, "shields": [1, 1]}
    status, data = post_json(f"{base_url}/api/matchup-battle", battle)
    assert status == 200 and data["result"]["ratings"][0] == cell
    status, exported = post_json(f"{base_url}/api/export-matchups", raw)
    assert status == 200 and exported["filename"] == "1v1_Mega_Froslass_and_1_more.toml"
    status, imported = post_json(f"{base_url}/api/import-matchups", {"text": exported["text"]})
    assert status == 200 and imported == {"config": raw}
    status, data = post_json(f"{base_url}/api/matchups", {**raw, "league": "1500"})
    assert status == 400 and "league" in data["error"]
    status, data = post_json(f"{base_url}/api/matchup-battle", {**battle, "shields": [3, 1]})
    assert status == 400 and "shields" in data["error"]


def test_team_matrix_stream(base_url):
    """队伍对队伍（4h）：边打边发，NDJSON 一行一项；写错的配置在开始发之前回 400。"""
    from tests.test_web_api import _small_matrix

    status, content_type, body = request(f"{base_url}/api/team-matrix", json.dumps(_small_matrix()).encode("utf-8"))
    assert status == 200 and content_type == "application/x-ndjson; charset=utf-8"
    events = [json.loads(line) for line in body.decode("utf-8").splitlines()]
    assert events[0]["type"] == "start" and events[0]["total"] == 8
    assert events[-1]["type"] == "done" and events[-2]["done"] == 8
    assert events[-1]["report_markdown"] == "".join(
        e["report_markdown"] for e in web_api.team_matrix_stream(_small_matrix()) if e["type"] == "done"
    )
    bad = _small_matrix()
    del bad["team"]
    status, data = post_json(f"{base_url}/api/team-matrix", bad)
    assert status == 400 and data["error"] == "网页：缺少 team"


def test_team_matrix_stops_when_the_page_disconnects(base_url, monkeypatch):
    """网页点"停止"就是断开请求：服务器写不出去，就不再往下打（同一个进程里数打了几场）。"""
    from tests.test_web_api import _small_matrix

    played = []
    original = team_matrix.run_team_battle

    def slow(battle, evaluators=None):
        played.append(1)
        time.sleep(0.02)
        return original(battle, evaluators)

    monkeypatch.setattr(team_matrix, "run_team_battle", slow)
    monkeypatch.setattr(web_api, "MATRIX_PROGRESS_SECONDS", 0)
    raw = _small_matrix()
    raw["opponent_sample"]["count"] = 30  # 我方 2 队 × 对手 31 队 = 62 场
    host, port = base_url.removeprefix("http://").split(":")
    connection = http.client.HTTPConnection(host, int(port), timeout=30)
    connection.request("POST", "/api/team-matrix", json.dumps(raw), {"Content-Type": "application/json"})
    response = connection.getresponse()
    assert json.loads(response.fp.readline())["type"] == "start"
    assert json.loads(response.fp.readline())["done"] == 1
    response.close()  # 浏览器断开请求时 socket 真的关掉（response 自己也拿着 socket）
    connection.close()
    time.sleep(0.5)
    stopped_at = len(played)
    time.sleep(0.5)
    assert len(played) == stopped_at < 62
    # 服务器照常接别的请求
    status, _, _ = request(f"{base_url}/api/matrix-options")
    assert status == 200


def test_matrix_endpoints(base_url):
    from tests.test_web_api import _small_matrix

    raw = _small_matrix()
    status, _, body = request(f"{base_url}/api/matrix-options")
    assert status == 200 and json.loads(body)["example"] == web_api.example_matrix()
    status, data = post_json(f"{base_url}/api/matrix-battle", {"config": raw, "team": 1, "opponent": 0})
    assert status == 200 and data["result"]["ratings"] == [566, 433]
    status, data = post_json(f"{base_url}/api/matrix-pairing", {"config": raw, "team": 1, "opponent": 2})
    assert status == 200 and [t["name"] for t in data["config"]["team"]] == ["Team A (Mega Froslass)", "抽样 2"]
    status, exported = post_json(f"{base_url}/api/export-matrix", raw)
    assert status == 200 and exported["filename"] == "matrix_Team_A_and_1_more.toml"
    status, imported = post_json(f"{base_url}/api/import-matrix", {"text": exported["text"]})
    assert status == 200 and imported == {"config": raw, "warnings": []}
    status, data = post_json(f"{base_url}/api/matrix-battle", {"config": raw, "team": 5, "opponent": 0})
    assert status == 400 and "team" in data["error"]

