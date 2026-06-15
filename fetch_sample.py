# -*- coding: utf-8 -*-
"""
公式サイトに公開されている 2026 年大会の競技記録を取得して、
そのままサンプルデータとして利用できるようにするスクリプト。

会場のローカルサーバが無い環境（このリポジトリを試す人）でも、
本物の競技順・結果・ロボット情報（写真付き）で動作確認できます。

取得元: http://www.inrof.org/2026/irc/score/

使い方:
    python fetch_sample.py            # 競技順＋結果＋ロボット情報＋写真をすべて取得
    python fetch_sample.py --quick    # 競技順＋結果のみ（写真はスキップ・高速）

取得後 build_data.py が自動実行され、data/competition.json が生成されます。
そのまま `python server.py` で配信システムを起動できます。

※ 取得データは公式サイトで一般公開されているものです。再配布の際は出典(inrof.org)を
   明記し、各データの権利・規約に配慮してください。
"""
import os
import sys
import runpy

PUBLIC_URL = "http://www.inrof.org/2026/irc/score/"


def main():
    # fetch_live.py の取得処理をそのまま再利用し、取得元だけ公式サイトに差し替える
    os.environ.setdefault("IRC_BASE_URL", PUBLIC_URL)
    print(f"== 公式サイトからサンプルデータを取得します: {PUBLIC_URL}")
    print("   (公開データです。出典 inrof.org を明記してご利用ください)\n")
    here = os.path.dirname(os.path.abspath(__file__))
    # 引数(--quick など)は fetch_live.py 側にそのまま渡る
    runpy.run_path(os.path.join(here, "fetch_live.py"), run_name="__main__")


if __name__ == "__main__":
    main()
