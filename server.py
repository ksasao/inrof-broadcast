# -*- coding: utf-8 -*-
"""
知能ロボットコンテスト 公式配信テロップ システム サーバ

Python 標準ライブラリのみで動作 (依存ゼロ)。
 - 操作画面 (control.html) が状態を POST /api/state で更新
 - オーバーレイ (overlay.html / OBSブラウザソース) が GET /api/events (SSE) で即時受信

起動:  python server.py        (デフォルト http://0.0.0.0:8080 )
       python server.py 9000   (ポート指定)

OBS ブラウザソース URL : http://localhost:8080/overlay
操作画面 URL           : http://localhost:8080/        (同一PC)
                         http://<このPCのIP>:8080/      (別端末/タブレットから操作)
"""
import sys
import os
import json
import time
import threading
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(BASE, "public")
DATA = os.path.join(BASE, "data")

# ---- 共有状態 -------------------------------------------------------------
LOCK = threading.Lock()
SUBSCRIBERS = []  # list[queue.Queue]

# 初期状態。telop=表示中のテロップ, bug=常時表示の隅ロゴ
STATE = {
    "rev": 1,
    "telop": {"type": "none"},
    "bug": {"show": True, "round": ""},
    "showInfo": False,
}


def broadcast():
    payload = json.dumps(STATE, ensure_ascii=False)
    with LOCK:
        subs = list(SUBSCRIBERS)
    for q in subs:
        try:
            q.put_nowait(payload)
        except Exception:
            pass


# ---- HTTP ハンドラ --------------------------------------------------------
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # 静かに

    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/control":
            return self._file(os.path.join(PUBLIC, "control.html"))
        if path == "/overlay":
            return self._file(os.path.join(PUBLIC, "overlay.html"))
        if path == "/api/state":
            with LOCK:
                return self._send(200, json.dumps(STATE, ensure_ascii=False),
                                  CONTENT_TYPES[".json"])
        if path == "/api/data":
            fp = os.path.join(DATA, "competition.json")
            if not os.path.isfile(fp):
                # データ未取得。空構造を返し、操作画面に取得を促す
                empty = {"event": "", "eventShort": "", "rounds": [],
                         "results": {}, "needFetch": True}
                return self._send(200, json.dumps(empty, ensure_ascii=False),
                                  CONTENT_TYPES[".json"])
            return self._file(fp)
        if path == "/api/events":
            return self._sse()
        # 静的ファイル
        if path.startswith("/public/"):
            return self._file(os.path.join(BASE, path.lstrip("/")))
        if path.startswith("/data/"):
            return self._file(os.path.join(BASE, path.lstrip("/")))
        if path.startswith("/docs/"):
            return self._file(os.path.join(BASE, path.lstrip("/")))
        if path.startswith("/images/"):
            return self._file(os.path.join(BASE, path.lstrip("/")))
        return self._send(404, "not found")

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                incoming = json.loads(raw.decode("utf-8"))
            except Exception:
                return self._send(400, "bad json")
            with LOCK:
                # telop / bug を部分更新
                if "telop" in incoming:
                    STATE["telop"] = incoming["telop"]
                if "bug" in incoming:
                    STATE["bug"] = incoming["bug"]
                if "showInfo" in incoming:
                    STATE["showInfo"] = bool(incoming["showInfo"])
                STATE["rev"] += 1
            broadcast()
            return self._send(200, '{"ok":true}', CONTENT_TYPES[".json"])
        if path == "/api/snapshot":
            # 現在ロボットテロップ表示中ならゼッケン番号をファイル名に含める
            with LOCK:
                telop = STATE.get("telop") or {}
            suffix = ""
            if telop.get("type") == "robot" and telop.get("code"):
                suffix = str(telop["code"])
            try:
                import obs_snap
                fpath = obs_snap.take_snapshot(os.path.join(BASE, "snapshots"), suffix)
                body = json.dumps({"ok": True, "file": os.path.basename(fpath)},
                                  ensure_ascii=False)
                return self._send(200, body, CONTENT_TYPES[".json"])
            except Exception as e:
                body = json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
                return self._send(200, body, CONTENT_TYPES[".json"])
        return self._send(404, "not found")

    def _file(self, fpath):
        if not os.path.isfile(fpath):
            return self._send(404, "not found: " + fpath)
        ext = os.path.splitext(fpath)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(fpath, "rb") as f:
            body = f.read()
        return self._send(200, body, ctype)

    def _sse(self):
        q = queue.Queue(maxsize=32)
        with LOCK:
            SUBSCRIBERS.append(q)
            init = json.dumps(STATE, ensure_ascii=False)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 2000\n\n")
            self.wfile.write(("data: " + init + "\n\n").encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(("data: " + msg + "\n\n").encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")  # keep-alive
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with LOCK:
                if q in SUBSCRIBERS:
                    SUBSCRIBERS.remove(q)


def main():
    port = 8080
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("=" * 56)
    print(" 知能ロボコン 配信テロップ システム 起動")
    print("=" * 56)
    print(f"  操作画面          : http://localhost:{port}/")
    print(f"  OBS ブラウザソース : http://localhost:{port}/overlay")
    print(f"  (解像度 1920x1080 / 背景透過 / FPS 30 推奨)")
    print("=" * 56)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました")


if __name__ == "__main__":
    main()
