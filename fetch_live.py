# -*- coding: utf-8 -*-
"""
会場ローカルサーバから最新の競技順・結果・ロボット情報を取得するスクリプト。

  python fetch_live.py            # 全取得 (競技順+結果+ロボット情報+写真)
  python fetch_live.py --quick    # 競技順と結果のみ (rinfo キャッシュ済みなら高速)

取得先:
  大会ロゴ logo5.png     -> images/        (未取得時のみ・公式サイトから)
  競技順 ordera-d.html   -> docs/order/
  結果   score{c,m}{a-d}.html, list*.html -> docs/results/2026/
  ロボット情報+写真 rinfo/* -> docs/results/2026/rinfo/

サーバ負荷軽減のため、各リクエストの間隔を IRC_THROTTLE 秒(既定0.3)空ける。
実行後は build_data.py を自動実行して data/competition.json を更新する。
"""
import os
import re
import sys
import time
import urllib.request
import urllib.error

# 会場ローカルサーバ。環境変数 IRC_BASE_URL で上書き可能
# (例: 公式サイト http://www.inrof.org/2026/irc/score/ から取得する fetch_sample.py)
BASE_URL = os.environ.get("IRC_BASE_URL", "http://192.168.1.63/2026/irc/score/")

# 大会ロゴ。初回 fetch 時に公式サイトから取得する (リポジトリには含めない)
LOGO_URL = os.environ.get("IRC_LOGO_URL", "http://www.inrof.org/irc/img/logo5.png")

# サーバ負荷軽減のためのリクエスト間隔(秒)。環境変数 IRC_THROTTLE で調整可能
THROTTLE = float(os.environ.get("IRC_THROTTLE", "0.3"))

BASE = os.path.dirname(os.path.abspath(__file__))
ORDER_DIR = os.path.join(BASE, "docs", "order")
RES_DIR = os.path.join(BASE, "docs", "results", "2026")
RINFO_DIR = os.path.join(RES_DIR, "rinfo")
IMAGES_DIR = os.path.join(BASE, "images")

ORDER_FILES = ["ordera.html", "orderb.html", "orderc.html", "orderd.html"]
SCORE_FILES = [f"score{c}{r}.html" for c in "cm" for r in "abcd"]
LIST_FILES = ["listcha.html", "listma.html"]

RINFO_RE = re.compile(r'href="(rinfo/robot\d+\.html)"', re.I)
IMG_RE = re.compile(r'(?:src|href)="([^"]+\.(?:jpe?g|png|gif))"', re.I)


_last_request = [0.0]


def _throttle():
    """ 直前のリクエストから THROTTLE 秒未満なら待機し、サーバ負荷を抑える """
    if THROTTLE <= 0:
        return
    dt = time.monotonic() - _last_request[0]
    if dt < THROTTLE:
        time.sleep(THROTTLE - dt)
    _last_request[0] = time.monotonic()


def fetch(url, timeout=10):
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": "inrof-broadcast/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def get(url, dest, optional=False):
    try:
        data = fetch(url)
        save(dest, data)
        print(f"  OK   {url}  ({len(data):,} bytes)")
        return data
    except urllib.error.HTTPError as e:
        msg = f"  {'--' if optional else 'NG'}   {url}  (HTTP {e.code})"
        print(msg)
        return None
    except Exception as e:
        print(f"  NG   {url}  ({e})")
        return None


def main():
    quick = "--quick" in sys.argv
    rinfo_pages = set()

    # 大会ロゴ (未取得なら公式サイトから一度だけ取得)
    logo_dest = os.path.join(IMAGES_DIR, "logo5.png")
    if not os.path.exists(logo_dest):
        print(f"== 大会ロゴ -> {IMAGES_DIR}")
        get(LOGO_URL, logo_dest, optional=True)

    print(f"== 競技順 -> {ORDER_DIR}")
    for f in ORDER_FILES:
        data = get(BASE_URL + f, os.path.join(ORDER_DIR, f))
        if data:
            rinfo_pages.update(RINFO_RE.findall(data.decode("latin1")))

    print(f"== 競技結果 -> {RES_DIR}")
    for f in SCORE_FILES:
        # まだ実施されていないラウンドの結果は存在しないことがある (optional)
        data = get(BASE_URL + f, os.path.join(RES_DIR, f), optional=True)
        if data:
            rinfo_pages.update(RINFO_RE.findall(data.decode("latin1")))

    print(f"== ロボットリスト -> {RES_DIR}")
    for f in LIST_FILES:
        data = get(BASE_URL + f, os.path.join(RES_DIR, f), optional=True)
        if data:
            rinfo_pages.update(RINFO_RE.findall(data.decode("latin1")))

    if not quick:
        print(f"== ロボット情報 ({len(rinfo_pages)} 件) -> {RINFO_DIR}")
        for rel in sorted(rinfo_pages):
            fname = rel.split("/")[-1]
            dest = os.path.join(RINFO_DIR, fname)
            data = get(BASE_URL + rel, dest, optional=True)
            if not data:
                continue
            # ページ内の写真をキャッシュ (rinfo/ からの相対参照)
            html = data.decode("latin1")
            for img in set(IMG_RE.findall(html)):
                if img.startswith(("http://", "https://", "/")):
                    continue  # 外部/絶対参照はスキップ
                img_dest = os.path.normpath(os.path.join(RINFO_DIR, img))
                if not img_dest.startswith(RINFO_DIR):
                    continue  # ディレクトリ外への参照は無視
                if os.path.exists(img_dest):
                    continue  # キャッシュ済み
                get(BASE_URL + "rinfo/" + img, img_dest, optional=True)

    print("== build_data.py を実行")
    import subprocess
    rc = subprocess.call([sys.executable, os.path.join(BASE, "build_data.py")])
    print("== 完了" if rc == 0 else "== build_data.py が失敗しました")


if __name__ == "__main__":
    main()
