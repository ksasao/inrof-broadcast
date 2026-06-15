# -*- coding: utf-8 -*-
"""
OBS WebSocket (obs-websocket v5, OBS 28+ 標準搭載) 経由で
カメラソースの静止画を JPEG 保存するモジュール。標準ライブラリのみで動作。

OBS 側の準備:
  ツール → WebSocketサーバー設定 → 「WebSocketサーバーを有効にする」にチェック
  (ポート既定 4455。パスワードを設定した場合は OBS_WS_PASSWORD 環境変数で渡す)

カメラソースの特定:
  既定では入力種別/名前に "droidcam" を含むソースを自動検出する。
  別のソースを使う場合は環境変数 SNAPSHOT_SOURCE にソース名を設定。
"""
import os
import json
import base64
import hashlib
import socket
import struct
import uuid

OBS_HOST = os.environ.get("OBS_WS_HOST", "127.0.0.1")
OBS_PORT = int(os.environ.get("OBS_WS_PORT", "4455"))
OBS_PASSWORD = os.environ.get("OBS_WS_PASSWORD", "")
SNAPSHOT_SOURCE = os.environ.get("SNAPSHOT_SOURCE", "")  # 空なら自動検出


class OBSError(Exception):
    pass


# ---- 最小限の WebSocket クライアント (RFC6455, クライアント側) ------------
class _WS:
    def __init__(self, host, port, timeout=5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        # ハンドシェイク応答を読み捨てる(\r\n\r\n まで)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OBSError("WebSocket handshake failed")
            buf += chunk
        if b"101" not in buf.split(b"\r\n", 1)[0]:
            raise OBSError("WebSocket upgrade rejected: " + buf.split(b"\r\n", 1)[0].decode("latin1"))

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise OBSError("connection closed")
            buf += chunk
        return buf

    def send_text(self, text):
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = b"\x81"  # FIN + text frame
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv_text(self):
        # 制御フレーム(ping等)はスキップしつつテキストフレームを返す
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(n) if n else b""
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:        # ping -> pong
                self.send_pong(payload)
                continue
            if opcode == 0x8:        # close
                raise OBSError("connection closed by OBS")
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8")

    def send_pong(self, payload):
        mask = os.urandom(4)
        header = bytes([0x8A, 0x80 | len(payload)])
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ---- obs-websocket v5 プロトコル -------------------------------------------
def _connect():
    ws = _WS(OBS_HOST, OBS_PORT)
    hello = json.loads(ws.recv_text())          # op:0 Hello
    identify = {"op": 1, "d": {"rpcVersion": 1}}
    auth = hello.get("d", {}).get("authentication")
    if auth:
        if not OBS_PASSWORD:
            ws.close()
            raise OBSError("OBSのWebSocketにパスワードが設定されています。"
                           "環境変数 OBS_WS_PASSWORD を設定してください")
        secret = base64.b64encode(hashlib.sha256(
            (OBS_PASSWORD + auth["salt"]).encode()).digest()).decode()
        authstr = base64.b64encode(hashlib.sha256(
            (secret + auth["challenge"]).encode()).digest()).decode()
        identify["d"]["authentication"] = authstr
    ws.send_text(json.dumps(identify))
    resp = json.loads(ws.recv_text())           # op:2 Identified を期待
    if resp.get("op") != 2:
        ws.close()
        raise OBSError("OBS WebSocket 認証に失敗しました")
    return ws


def _request(ws, req_type, req_data=None):
    rid = str(uuid.uuid4())
    msg = {"op": 6, "d": {"requestType": req_type, "requestId": rid}}
    if req_data:
        msg["d"]["requestData"] = req_data
    ws.send_text(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv_text())
        if resp.get("op") == 7 and resp["d"].get("requestId") == rid:
            st = resp["d"]["requestStatus"]
            if not st.get("result"):
                raise OBSError(f"{req_type} failed: {st.get('comment') or st.get('code')}")
            return resp["d"].get("responseData", {})
        # op:5 (イベント) などは無視して次を待つ


def _find_camera_source(ws):
    """ SNAPSHOT_SOURCE 指定があればそれ、無ければ droidcam を含む入力を自動検出 """
    if SNAPSHOT_SOURCE:
        return SNAPSHOT_SOURCE
    inputs = _request(ws, "GetInputList").get("inputs", [])
    for inp in inputs:
        kind = (inp.get("inputKind") or "").lower()
        name = (inp.get("inputName") or "")
        if "droidcam" in kind or "droidcam" in name.lower():
            return name
    # 見つからなければ映像キャプチャ系を探す
    for inp in inputs:
        kind = (inp.get("inputKind") or "").lower()
        if "dshow" in kind or "v4l2" in kind or "av_capture" in kind:
            return inp.get("inputName")
    names = ", ".join(i.get("inputName", "?") for i in inputs) or "(なし)"
    raise OBSError("カメラソースを自動検出できませんでした。"
                   f"環境変数 SNAPSHOT_SOURCE にソース名を設定してください。候補: {names}")


def take_snapshot(out_dir, suffix=""):
    """ カメラソースのスナップショットを JPEG 保存してファイルパスを返す """
    import datetime
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{ts}{('_' + suffix) if suffix else ''}.jpg"
    fpath = os.path.abspath(os.path.join(out_dir, fname))
    ws = _connect()
    try:
        source = _find_camera_source(ws)
        _request(ws, "SaveSourceScreenshot", {
            "sourceName": source,
            "imageFormat": "jpg",
            "imageFilePath": fpath,
            "imageCompressionQuality": 92,
        })
    finally:
        ws.close()
    return fpath
