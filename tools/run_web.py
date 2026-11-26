"""本地网页界面（第 4 步）：启动一个只给本机用的服务器，在浏览器里选队伍、打 3v3、搜索应对、存队伍、看时间线、
跑 1v1 九宫格、队伍对队伍、排能力值。

用法（在仓库根目录）：
    .venv/bin/python -m tools.run_web                  # 启动后自动打开 http://127.0.0.1:8000
    .venv/bin/python -m tools.run_web --port 8001 --no-browser

只监听本机（127.0.0.1），同一网络里的其他设备打不开。服务器用 Python 标准库的 http.server，
只适合本机一个人用。按 Ctrl+C 停止。

这里只做转发：网页的文件在 web/，接口的逻辑在 pogo_sim/web_api.py。接口都回 JSON：
    GET  /api/options                  联盟、赛季规则、覆盖文件、例子配置
    GET  /api/species?league=1500&custom=a.toml
                                       全部宝可梦和招式，以及 PvPoke 在这个联盟推荐的配招
                                       （custom 可以写几次，是 data/custom/ 里的文件名）
    GET  /api/stats?league=1500&season=pvpoke&custom=a.toml
                                       能力值排序：每只的 CP、等级、IV、实际能力值、坦度
                                       （一个联盟第一次打开时要算几秒，之后读 .cache/ 里的缓存）
    POST /api/build                    一只宝可梦按赛季规则建配置
    POST /api/team-battle              打一场 3v3
    POST /api/manual-battle            手动对战：按玩家到现在的决定重打到下一个要玩家决定的地方
    POST /api/best-response            对另一队的固定策略，搜索一队的打法（逐步试探，0.5–2 秒）
    GET  /api/team-library             队伍库（仓库的 teams/）里的全部队伍
    POST /api/team-library/save        把一队存进队伍库（同名的要带 overwrite 才覆盖；网页不能删除）
    POST /api/export-config            把页面上的配置写成 3v3 配置文件（TOML）
    POST /api/import-config            从 3v3 配置文件（TOML 文本）导入
    GET  /api/matchup-options          1v1 九宫格页的选项：策略参数、环境前 N 能选什么、例子配置
    POST /api/matchups                 跑 1v1 九宫格（每个测试对象对手写的对手和环境前 N，0–2 盾对 0–2 盾）
    POST /api/matchup-battle           九宫格里的一场：过程图和逐回合时间线
    POST /api/export-matchups          把页面上的九宫格配置写成配置文件（TOML）
    POST /api/import-matchups          从九宫格的配置文件（TOML 文本）导入
    GET  /api/matrix-options           队伍对队伍页的选项：随机抽能选什么、默认值、例子配置
    POST /api/team-matrix              队伍对队伍：边打边发进度（NDJSON，一行一项，见 web_api.team_matrix_stream）；
                                       网页断开请求（点"停止"）就不再打
    POST /api/matrix-battle            队伍对队伍里的一场：完整的 3v3 结果（同 /api/team-battle）
    POST /api/matrix-pairing           把那一场写成"打一场"页的配置
    POST /api/export-matrix            把页面上的队伍对队伍配置写成配置文件（TOML）
    POST /api/import-matrix            从队伍对队伍的配置文件（TOML 文本）导入
配置写错时回 400 和 {"error": "中文说明"}；服务器里的意外错误回 500，详细信息打印在终端。
边打边发的接口在开始发之前照样这样回；发到一半出了意外错误时，最后一行是 {"type": "error", "error": ...}。
"""

import argparse
import json
import sys
import traceback
import webbrowser
from collections.abc import Callable, Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pogo_sim import web_api
from pogo_sim.config import REPO_ROOT, ConfigError

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
WEB_DIR = REPO_ROOT / "web"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}

# 路径 → 处理函数。GET 的参数是查询字符串（每个键一个列表），POST 的参数是请求体里的 JSON。
GET_API: dict[str, Callable[[dict[str, list[str]]], Any]] = {
    "/api/options": lambda query: web_api.options(),
    "/api/matchup-options": lambda query: web_api.matchup_options(),
    "/api/matrix-options": lambda query: web_api.matrix_options(),
    "/api/team-library": lambda query: web_api.library_payload(),
    "/api/species": lambda query: web_api.species_catalog(query.get("custom", []), query.get("league", [None])[0]),
    "/api/stats": lambda query: web_api.stat_table_payload(
        query.get("league", [None])[0], query.get("season", [None])[0], query.get("custom", [])
    ),
}
POST_API: dict[str, Callable[[Any], Any]] = {
    "/api/build": web_api.build_member,
    "/api/team-battle": web_api.team_battle,
    "/api/manual-battle": web_api.manual_battle,
    "/api/best-response": web_api.best_response,
    "/api/team-library/save": web_api.save_library_team,
    "/api/export-config": web_api.export_team_battle,
    "/api/import-config": web_api.import_team_battle,
    "/api/matchups": web_api.matchups,
    "/api/matchup-battle": web_api.matchup_battle,
    "/api/export-matchups": web_api.export_matchups,
    "/api/import-matchups": web_api.import_matchups,
    "/api/matrix-battle": web_api.matrix_battle,
    "/api/matrix-pairing": web_api.matrix_pairing_config,
    "/api/export-matrix": web_api.export_matrix,
    "/api/import-matrix": web_api.import_matrix,
}
# 边打边发的接口：处理函数返回一个迭代器，每一项写成 NDJSON 的一行（_stream）
STREAM_API: dict[str, Callable[[Any], Iterator[Any]]] = {
    "/api/team-matrix": web_api.team_matrix_stream,
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path in GET_API:
            query = parse_qs(url.query)
            self._call(lambda: GET_API[url.path](query))
        elif url.path.startswith("/api/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": f"没有这个接口：GET {url.path}"})
        else:
            self._static(url.path)

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        if url.path not in POST_API and url.path not in STREAM_API:
            self._json(HTTPStatus.NOT_FOUND, {"error": f"没有这个接口：POST {url.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"请求不是合法的 JSON：{e}"})
            return
        if url.path in STREAM_API:
            self._stream(lambda: STREAM_API[url.path](body))
        else:
            self._call(lambda: POST_API[url.path](body))

    def _call(self, handler: Callable[[], Any]) -> None:
        try:
            payload = handler()
        except ConfigError as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        except Exception as e:  # 引擎里的意外错误：信息给网页，详细的打印在终端
            traceback.print_exc()
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"服务器出错：{type(e).__name__}: {e}"})
        else:
            self._json(HTTPStatus.OK, payload)

    def _stream(self, handler: Callable[[], Iterator[Any]]) -> None:
        """边算边发：迭代器的每一项写成一行 JSON（NDJSON），写完一项就发出去。

        handler() 先检查配置（写错的回 400，和其他接口一样），返回迭代器以后才开始发。响应没有 Content-Length，
        发完就关连接。浏览器断开（网页点"停止"）时写不出去，就关掉迭代器，后面的也就不再算。
        """
        try:
            events = handler()
        except ConfigError as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
            return
        except Exception as e:
            traceback.print_exc()
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"服务器出错：{type(e).__name__}: {e}"})
            return
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            for event in events:
                self.wfile.write(json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # 网页断开了（点了"停止"）：不再往下算
        except Exception as e:  # 算到一半的意外错误：最后一行告诉网页，详细的打印在终端
            traceback.print_exc()
            error = {"type": "error", "error": f"服务器出错：{type(e).__name__}: {e}"}
            try:
                self.wfile.write(json.dumps(error, ensure_ascii=False).encode("utf-8") + b"\n")
            except OSError:
                pass
        finally:
            close = getattr(events, "close", None)
            if close is not None:
                close()

    def _static(self, path: str) -> None:
        """web/ 下的文件。只认这一层的 .html / .js / .css，不进子目录，所以不会读到 web/ 以外的文件。"""
        name = "index.html" if path == "/" else path.removeprefix("/")
        file = WEB_DIR / name
        if "/" in name or "\\" in name or file.suffix not in STATIC_TYPES or not file.is_file():
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", f"没有这个文件：{path}".encode())
            return
        self._send(HTTPStatus.OK, STATIC_TYPES[file.suffix], file.read_bytes())

    def _json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # 改了网页文件，刷新就能看到
        self.end_headers()
        self.wfile.write(body)


def make_server(port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    """只监听本机。port = 0 时由系统挑一个空闲端口（测试用），实际端口见 server.server_address。"""
    return ThreadingHTTPServer((HOST, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    try:
        server = make_server(args.port)
    except OSError as e:
        sys.exit(f"端口 {args.port} 用不了（{e}）。换一个：--port 8001")
    url = f"http://{HOST}:{server.server_address[1]}/"
    print(f"网页界面：{url}  （Ctrl+C 停止）")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
