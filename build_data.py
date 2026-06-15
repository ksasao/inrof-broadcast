# -*- coding: utf-8 -*-
"""
競技順HTML(ISO-2022-JP)を配信システム用のJSON(data/competition.json)に変換する。

当日、各競技の直前に新しい競技順HTMLが公開されるので、
docs/order/ 内の ordera/b/c/d.html を差し替えてから本スクリプトを実行すれば
データが更新される。  実行:  python build_data.py
"""
import re
import os
import json
import csv

BASE = os.path.dirname(os.path.abspath(__file__))
ORDER_DIR = os.path.join(BASE, "docs", "order")
RESULTS_DIR = os.path.join(BASE, "docs", "results")
OUT = os.path.join(BASE, "data", "competition.json")

# 競技順ファイル名 -> ラウンド定義
ROUND_FILES = [
    ("a", "ordera.html"),
    ("b", "orderb.html"),
    ("c", "orderc.html"),
    ("d", "orderd.html"),
]

CELL_RE = re.compile(r"<TD>\s*<TABLE>(.*?)</TABLE>\s*</TD>", re.S | re.I)
LINK_RE = re.compile(r'<A\s+HREF="([^"]+)">(.*?)</A>', re.S | re.I)
TIME_RE = re.compile(r"(\d{1,2}:\d{2})")
TD_RE = re.compile(r"<TD[^>]*>(.*?)</TD>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
H1_RE = re.compile(r"<H1>(.*?)</H1>", re.S | re.I)


def clean(s):
    s = TAG_RE.sub("", s)
    s = s.replace("&nbsp;", " ")
    # 全角スペースを区切りに使うので残す。前後の空白のみ除去
    return s.strip()


def split_code_name(text):
    """ 'C50　Sparviero' -> ('C50', 'Sparviero') """
    text = text.strip()
    # 先頭の英字+数字のコード (C50 / M05 など)
    m = re.match(r"^([A-Za-z]\d{1,3})[\s　]+(.*)$", text)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return "", text


def course_of(code):
    if code.startswith("C"):
        return "challengers"
    if code.startswith("M"):
        return "masters"
    return "other"


def decode_html(path):
    """ 競技順HTMLのエンコーディングを自動判別してデコード。
        ISO-2022-JP(JIS) / UTF-8 / Shift_JIS / EUC-JP に対応。 """
    data = open(path, "rb").read()
    # ISO-2022-JP はエスケープシーケンス ESC $ B を含む
    if b"\x1b$B" in data or b"\x1b$@" in data:
        return data.decode("iso-2022-jp", "replace")
    for enc in ("utf-8", "cp932", "euc-jp"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def parse_order(path):
    raw = decode_html(path)
    title = ""
    mt = H1_RE.search(raw)
    if mt:
        title = clean(mt.group(1))

    # ヘッダ行の「競技台」列数 = 1競技あたりのチーム数 (一次/敗者復活=3, 二次/決勝=2)
    ncols = raw.count("競技台")
    if ncols not in (2, 3):
        ncols = 3  # 不明時は従来どおり3

    cells = CELL_RE.findall(raw)
    parsed = []
    for inner in cells:
        time = ""
        mt = TIME_RE.search(inner)
        if mt:
            time = mt.group(1)
        link = LINK_RE.search(inner)
        url = ""
        code = ""
        name = ""
        team = ""
        if link:
            url = link.group(1)
            code, name = split_code_name(clean(link.group(2)))
        # チーム名: 各TDテキストのうち、時刻でもリンク行でもない最後の非空テキスト
        tds = [clean(x) for x in TD_RE.findall(inner)]
        candidates = []
        for t in tds:
            if not t:
                continue
            if TIME_RE.fullmatch(t):
                continue
            candidates.append(t)
        # リンクのテキスト(code+name)が candidates の先頭付近に入るので除外
        link_text = (code + " " + name).strip()
        team_cands = [c for c in candidates
                      if c.replace("　", " ").strip() != link_text
                      and code not in c]
        if team_cands:
            team = team_cands[-1]
        # 休台/空セルの判定
        is_empty = (name == "") or ("robot99" in url) or ("休" in (name + team) and code == "")
        parsed.append({
            "time": time, "code": code, "name": name,
            "team": team, "url": url, "empty": is_empty,
        })

    # ncols セルずつ1競技にまとめる (一次/敗者復活=3, 二次/決勝=2)
    matches = []
    no = 0
    for i in range(0, len(parsed), ncols):
        group = parsed[i:i + ncols]
        robots = []
        gtime = ""
        for g in group:
            if g["time"] and not gtime:
                gtime = g["time"]
            if not g["empty"] and g["code"]:
                robots.append({
                    "code": g["code"], "name": g["name"], "team": g["team"],
                    "course": course_of(g["code"]), "url": g["url"],
                })
        if not robots:
            continue  # 全休の行はスキップ
        no += 1
        matches.append({"no": no, "time": gtime, "robots": robots})
    return title, matches


# 当日の競技結果HTML置き場 (score{c|m}{a|b|c|d}.html を置く)
#   c/m = チャレンジャーズ/マスターズ, a=一次予選 b=敗者復活戦 c=二次予選 d=決勝
# fetch_live.py が会場サーバから docs/results/2026/ に保存する。
# 2026 のデータが無い場合は 2025 (前回大会) にフォールバック。
SCORE_DIR = os.path.join(RESULTS_DIR, "2026")
if not os.path.exists(os.path.join(SCORE_DIR, "scoreca.html")):
    SCORE_DIR = os.path.join(RESULTS_DIR, "2025")

ROUND_LABEL = {"a": "一次予選", "b": "敗者復活戦", "c": "二次予選", "d": "決勝"}

ROW_RE = re.compile(
    r"<TR[^>]*><TD>([CM]\d+)</TD>\s*"          # ID
    r"<TD[^>]*>\s*(?:<A[^>]*>)?(.*?)(?:</A>)?</TD>\s*"  # ロボット名
    r"<TD[^>]*>(.*?)</TD>\s*"                  # チーム名
    r"<TD>(.*?)</TD>\s*"                       # 競技点
    r"<TD>(.*?)</TD>\s*"                       # 審査点
    r"<TD>(.*?)</TD>\s*"                       # 補正
    r"<TD>(.*?)</TD>\s*"                       # 合計
    r"(?:<TD>(.*?)</TD>)?",                    # 残り時間 (無い形式にも耐える)
    re.S | re.I)


def parse_score_file(path):
    """ 結果HTML -> [{code, total}] (記載順 = 得点順なので順位は行番号) """
    if not os.path.exists(path):
        return []
    raw = decode_html(path)
    rows = []
    for m in ROW_RE.finditer(raw):
        code = m.group(1).upper()
        name = clean(m.group(2))
        team = clean(m.group(3))
        game = clean(m.group(4))    # 競技点
        judge = clean(m.group(5))   # 審査点 ("(無)" の場合あり)
        hosei = clean(m.group(6))   # 補正
        total = clean(m.group(7))
        rtime = clean(m.group(8) or "")  # 残り時間
        row = {"code": code, "name": name, "team": team,
               "total": total, "game": game, "hosei": hosei, "time": rtime}
        # 審査点が数値のときだけ持つ (一次予選・敗者復活戦は審査なし)
        if re.fullmatch(r"[\d.]+", judge):
            row["judge"] = judge
        rows.append(row)
    return rows


def load_round_scores():
    """ ラウンドID(a/b/c/d) -> {code: {total, rank, n}} (コース別に順位付け) """
    result = {}
    for rid in "abcd":
        table = {}
        for course in "cm":
            path = os.path.join(SCORE_DIR, f"score{course}{rid}.html")
            rows = parse_score_file(path)
            for i, row in enumerate(rows):
                rec = {"total": row["total"], "rank": i + 1, "n": len(rows),
                       "game": row["game"]}
                if "judge" in row:
                    rec["judge"] = row["judge"]
                table[row["code"]] = rec
        result[rid] = table
    return result


ROBOT_INFO_DIR = os.path.join(SCORE_DIR, "rinfo")
IMG_RE = re.compile(r'<IMG\s+SRC="([^"]+)"', re.I)


def parse_robot_info(url):
    """ rinfo/robotNNN.html を解析して {image, specs, appeal, features} を返す """
    if not url:
        return None
    fname = os.path.basename(url)                 # robotNNN.html
    path = os.path.join(ROBOT_INFO_DIR, fname)
    if not os.path.exists(path):
        return None
    t = decode_html(path)
    info = {}
    # 画像 (rimage/robotimgNNN.jpeg|png) -> サーバ配信パスへ
    mi = IMG_RE.search(t)
    if mi:
        rel = mi.group(1).lstrip("/")             # rimage/robotimgNNN.jpeg
        year = os.path.basename(SCORE_DIR)            # "2026" / "2025"
        info["image"] = f"/docs/results/{year}/rinfo/" + rel
    # <HR> 区切りでブロック分割
    parts = re.split(r"<HR>", t, flags=re.I)
    def clean_block(s):
        s = TAG_RE.sub(" ", s)
        s = s.replace("　", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s
    for i, p in enumerate(parts):
        c = clean_block(p)
        if not c:
            continue
        if "アピール" in c:
            info["appeal"] = c.split("アピール", 1)[1].strip(" ：:")
        elif "特徴" in c:
            seg = c.split("特徴", 1)[1]
            seg = re.split(r"競技結果", seg)[0]
            info["features"] = seg.strip(" ：:")
        elif i == 1:
            # 最初の <HR> 直後ブロック = 寸法・センサ等のスペック
            info["specs"] = c
    return info if info else None


def load_results_lists():
    """ 結果一覧テロップ用: rid -> {challengers:[rows], masters:[rows]} (得点順) """
    out = {}
    for rid in "abcd":
        entry = {}
        for course, key in (("c", "challengers"), ("m", "masters")):
            path = os.path.join(SCORE_DIR, f"score{course}{rid}.html")
            rows = parse_score_file(path)
            if rows:
                entry[key] = rows
        if entry:
            out[rid] = entry
    return out


def attach_prev(rounds, round_scores):
    """ 各ロボットに『直前ラウンドの成績』を付与する。
        敗者復活戦 -> 一次予選 / 決勝 -> 二次予選
        二次予選   -> 敗者復活戦に出ていればその成績、出ていなければ一次予選 """
    for rnd in rounds:
        rid = rnd["id"]
        for m in rnd["matches"]:
            for r in m["robots"]:
                code = r["code"]
                src = None
                if rid == "b":
                    src = "a"
                elif rid == "c":
                    src = "b" if code in round_scores.get("b", {}) else "a"
                elif rid == "d":
                    src = "c"
                if not src:
                    continue
                rec = round_scores.get(src, {}).get(code)
                if rec:
                    prev = {
                        "round": ROUND_LABEL[src],
                        "total": rec["total"],
                        "rank": rec["rank"],
                        "n": rec["n"],
                    }
                    # 審査点のあるラウンド(二次予選)は内訳も持たせる
                    if rec.get("judge"):
                        prev["game"] = rec["game"]
                        prev["judge"] = rec["judge"]
                    r["prev"] = prev


def load_scores():
    """ 直近(2025)の参考記録: code -> 最高得点/最終順位 """
    scores = {}
    path = os.path.join(RESULTS_DIR, "inrof_2025_score_summary.csv")
    if not os.path.exists(path):
        return scores
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        for row in csv.DictReader(f):
            code = (row.get("ID") or "").strip().upper()
            if not code:
                continue
            scores[code] = {
                "best": (row.get("最高得点") or "").strip(),
                "rank": (row.get("最終順位") or "").strip(),
            }
    return scores


def main():
    scores = load_scores()
    rounds = []
    for rid, fname in ROUND_FILES:
        path = os.path.join(ORDER_DIR, fname)
        if not os.path.exists(path):
            continue
        title, matches = parse_order(path)
        # 参考記録を付与(コード一致時のみ。当日新データでは一致しないこともある)
        for m in matches:
            for r in m["robots"]:
                ref = scores.get(r["code"])
                if ref and ref.get("best"):
                    r["ref"] = ref
                # 当日キャッシュしたロボット情報(画像・紹介文)を付与
                info = parse_robot_info(r.get("url"))
                if info:
                    r["info"] = info
        rounds.append({"id": rid, "name": title or fname, "matches": matches})

    # 直前ラウンドの成績を付与 (docs/results/<年>/score*.html から)
    attach_prev(rounds, load_round_scores())

    data = {
        "event": "第38回 知能ロボットコンテスト 2026",
        "eventShort": "知能ロボットコンテスト 2026",
        "rounds": rounds,
        "results": load_results_lists(),
        "roundLabels": ROUND_LABEL,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

    total = sum(len(r["matches"]) for r in rounds)
    print(f"OK -> {OUT}")
    for r in rounds:
        print(f"  [{r['id']}] {r['name']}: {len(r['matches'])} matches")
    print(f"  total matches: {total}")


if __name__ == "__main__":
    main()
