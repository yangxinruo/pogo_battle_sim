"""本地网页界面（第 4 步）：启动一个只给本机用的服务器，在浏览器里选队伍、打 3v3、看时间线。

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
    POST /api/build                    一只宝可梦按赛季规则建配置
    POST /api/team-battle              打一场 3v3
配置写错时回 400 和 {"error": "中文说明"}；服务器里的意外错误回 500，详细信息打印在终端。
"""

import argparse
import json
import sys
import traceback
import webbrowser
from collections.abc import Callable
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
    "/api/species": lambda query: web_api.species_catalog(query.get("custom", []), query.get("league", [None])[0]),
}
POST_API: dict[str, Callable[[Any], Any]] = {
    "/api/build": web_api.build_member,
    "/api/team-battle": web_api.team_battle,
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
        if url.path not in POST_API:
            self._json(HTTPStatus.NOT_FOUND, {"error": f"没有这个接口：POST {url.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"请求不是合法的 JSON：{e}"})
            return
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
