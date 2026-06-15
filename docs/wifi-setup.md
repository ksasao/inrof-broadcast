# 配信用ノートPC WiFi 2系統 設定メモ

YouTube 配信をしながら、会場内に閉じたローカルネットワーク（成績情報の取得用）に
同時アクセスするためのネットワーク構成と設定手順。

```
[配信ノートPC]
 ├─ 内蔵WiFi  ──→ モバイルWiFiルータ ──→ インターネット (YouTube配信)
 └─ USB WiFiドングル ──→ 会場ローカルWiFi (成績ページの取得)
```

- `server.py`・OBSブラウザソース・操作画面はすべて localhost で完結するため、
  この構成の影響を受けない。
- 成績の取り込みは「会場WiFi経由で結果ページを開いて
  `docs/results/2025/score○○.html` に保存 → `python build_data.py`」の流れ。

---

## 1. 必要機材

| 機材 | 用途 |
|---|---|
| USB WiFi アダプタ（2.4GHz/5GHz両対応推奨） | 会場ローカルWiFi接続用 |
| モバイルWiFiルータ | インターネット（配信アップリンク） |

代替構成（どちらか使えるならドングル不要）:
- モバイルルータが **USBテザリング対応** なら、USB接続＝インターネット、内蔵WiFi＝会場用
- 会場側が **有線LAN** を出せるなら USB-Ethernet アダプタで有線＝会場、内蔵WiFi＝モバイルルータ

---

## 2. 接続先の固定（アダプタごとにSSIDを固定する）

Windows では WiFi プロファイルをアダプタ（インターフェース）ごとに持たせることで
接続先を固定できる。管理者権限のコマンドプロンプト / PowerShell で実行。

### 2-1. アダプタ名の確認

```
netsh wlan show interfaces
```

内蔵が `Wi-Fi`、ドングルが `Wi-Fi 2` のような名前で表示される（以下この名前と仮定）。

### 2-2. 各アダプタで目的のSSIDに接続

初回は GUI で一度パスワードを入れて接続し、プロファイルを作ってから行うと楽。

```
netsh wlan connect name="モバイルルータのSSID" interface="Wi-Fi"
netsh wlan connect name="会場WiFiのSSID" interface="Wi-Fi 2"
```

### 2-3. 逆側のアダプタから不要なプロファイルを削除（固定の本体）

プロファイルが無ければ、そのアダプタはそのSSIDに繋ぎに行かない。

```
:: 内蔵WiFiから会場WiFiのプロファイルを削除
netsh wlan delete profile name="会場WiFiのSSID" interface="Wi-Fi"

:: ドングルからモバイルルータのプロファイルを削除
netsh wlan delete profile name="モバイルルータのSSID" interface="Wi-Fi 2"
```

### 2-4. 自動接続の有効化

```
netsh wlan set profileparameter name="モバイルルータのSSID" interface="Wi-Fi" connectionmode=auto
netsh wlan set profileparameter name="会場WiFiのSSID" interface="Wi-Fi 2" connectionmode=auto
```

これで PC 起動時にそれぞれが決まった相手へ自動接続する。

### 2-5. 【重要】`#` で始まるSSID/プロファイル名の注意（実機で確認済み）

`#wifibox_4tj` のように SSID が `#` で始まる場合、コマンドが通らないことがある。

1. **PowerShell は `#` 以降をコメントとして無視する**
   → `ssid=#wifibox_4tj` は空文字扱いになりエラー。
2. **netsh 自身も `#` をコメント文字として扱う**
   → PowerShell の解析停止トークン `--%` ＋引用符
   （`netsh --% wlan connect name="#wifibox_4tj" interface="Wi-Fi"`）でも、
   `set profileparameter` などは「パラメーターが正しくないか不足しています」で
   失敗することがある（netsh のコメント処理は引用符を完全には尊重しない）。

`#` 入りの名前では netsh の `name=` 指定を避け、以下の方法を使うのが確実。

**自動接続の有効化（2-4 の代替）→ GUI で設定**

設定 → ネットワークとインターネット → Wi-Fi → 既知のネットワークの管理
→ 該当ネットワーク → 「範囲内の場合は自動的に接続する」にチェック。

**プロファイル操作（2-3 の代替）→ XML エクスポート/インポート**

`name=` を使わずにプロファイルを操作できる。

```powershell
# 1. 全プロファイルをエクスポート (name 指定不要なので # 問題なし)
mkdir C:\temp\wifi
netsh --% wlan export profile folder=C:\temp\wifi interface="Wi-Fi"

# 2. 出力された XML (例: Wi-Fi-#wifibox_4tj.xml) をメモ帳で開き、
#    <connectionMode>manual</connectionMode> を auto に書き換えて保存

# 3. インターフェースを指定して読み込み (filename 指定なので # 問題なし)
netsh --% wlan add profile filename="C:\temp\wifi\Wi-Fi-#wifibox_4tj.xml" interface="Wi-Fi" user=all
```

- 特定アダプタだけにプロファイルを持たせたい場合も、この
  「GUIで削除 → 必要な側だけ XML で `add profile interface=` 指定して再追加」が確実。
- 確認は `netsh --% wlan show profiles interface="Wi-Fi"`（複数形の show は
  name に `#` を渡さないので問題なく動く）。

---

## 3. 同時接続を切られないようにする（重要）

Windows には「同時接続数を最小化する」既定動作があり、両方がインターネットに
到達できると判断されると片方が自動切断されることがある。
会場WiFiは通常インターネット無しのため問題になりにくいが、確実を期すなら無効化する。

管理者 PowerShell:

```powershell
New-Item -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WcmSvc\GroupPolicy" -Force | Out-Null
Set-ItemProperty -Path "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WcmSvc\GroupPolicy" -Name fMinimizeConnections -Value 0 -Type DWord
```

Windows Pro なら gpedit.msc でも可:
「コンピューターの構成 → 管理用テンプレート → ネットワーク → Windows接続マネージャー
→ インターネットまたはWindowsドメインへの同時接続数を最小化する」を **無効** に。
設定後は再起動推奨。

---

## 4. ルーティングの優先度（インターネットは必ずモバイルルータ側へ）

2つのネットワークに同時接続すると、Windows がどちらをインターネットに使うか
迷うことがある。会場WiFiが「インターネットなし」のローカル網なら自動的に
モバイルルータ側が既定ルートになるが、確実にするには以下のいずれかを行う。

### 方法A: インターフェースメトリックの設定

```powershell
# 現在のメトリック確認
Get-NetIPInterface | Sort-Object InterfaceMetric | Format-Table InterfaceAlias, InterfaceMetric

# 会場WiFi側のメトリックを大きく（=優先度低く）
Set-NetIPInterface -InterfaceAlias "Wi-Fi 2" -InterfaceMetric 100
# モバイルルータ側を小さく（=優先度高く）
Set-NetIPInterface -InterfaceAlias "Wi-Fi" -InterfaceMetric 10
```

### 方法B: 会場側アダプタのデフォルトゲートウェイを空欄に

会場側アダプタの IPv4 設定でデフォルトゲートウェイを空欄にすると、
会場サブネット内の成績サーバには届き、インターネットへは絶対に流れない。
（最も確実。会場WiFiがDHCPでゲートウェイを配る場合は手動IP設定にする）

---

## 5. 当日の動作確認チェックリスト

1. `netsh wlan show interfaces` で2つのアダプタがそれぞれ意図したSSIDに接続されている
2. `https://www.youtube.com` が開ける（= 配信経路が生きている）
3. 会場の成績ページ（例 `http://192.168.x.x/...`）がブラウザで開ける（= 取得経路OK）
4. その状態で配信テストを数分回し、OBS の「ドロップフレーム」が出ないこと

---

## 6. iPhone カメラの接続（USB を推奨）

OBS に iPhone のカメラ映像を取り込む際は、Wi-Fi 経由ではなく **USB ケーブル接続を推奨**する。
会場では多数の無線機器が稼働しており、Wi-Fi 経由の映像伝送は混信・遅延・切断の影響を受けやすい。
USB 接続にすれば周囲の Wi-Fi 環境に左右されず、安定した映像が得られる。

- DroidCam OBS など iPhone カメラ用ツールは Wi-Fi モードと USB モードの両方に対応していることが多い。USB モードを選ぶ。
- iPhone を USB 接続し、必要に応じて「このコンピュータを信頼」を許可する。
- 長時間の配信では iPhone のバッテリーが切れないよう、給電可能な接続（給電対応ハブ等）を用意する。

---

## 7. クラウド同期（OneDrive / Google Drive）の一時無効化

OBS で録画を行うと**大きな動画ファイル**が生成される。録画先フォルダが OneDrive や
Google Drive などのファイル同期の対象になっていると、生成された動画が**自動的にアップロード**され、
配信の上り帯域を圧迫してドロップフレームの原因になる。配信前に同期を無効化しておくこと。

- **OneDrive**: タスクトレイのアイコン →「同期の一時停止」（2/8/24時間）。または録画先を同期対象外のフォルダにする。
- **Google Drive（Drive for desktop）**: 同様に同期を一時停止するか、録画先を同期対象外にする。
- 最も確実なのは、**録画の保存先を同期フォルダの外**（例: `D:\rec\` など）に設定しておくこと。
  OBS の「設定 → 出力 → 録画 → 録画ファイルのパス」で指定する。

---

## 8. 会場メモ（仙台市科学館）

- 複数キャリアを比較したところ、**SoftBank が最も通信環境が良かった**。ただし
  アップロード帯域がダウンロード帯域に比べて狭く帯域が非対称なため、配信に必要な上り帯域が
  確保できるか、当日に上り・下り双方を実測したうえで回線を検討すること。
- モバイル回線は時間帯・来場者数によって大きく変動する。本番前のリハーサルで必ず実測する
  （「5. 当日の動作確認チェックリスト」参照）。

---

## 9. その他の注意

- **配信の上り帯域**: YouTube 1080p30 なら 6Mbps 前後。モバイルルータの電波状況を
  会場で事前確認し、不安なら 720p に落とす設定も用意しておく。
- **キャプティブポータル**: 会場WiFiに同意画面がある場合、ドングル側のブラウザ
  アクセスで一度認証が必要。
- **操作画面を別端末（タブレット等）から使う場合**: その端末を会場WiFiではなく
  **モバイルWiFiルータ側**に接続し、配信PCのモバイルルータ側IPで
  `http://<配信PCのIP>:8080/` にアクセスする
  （Windowsファイアウォールでポート8080の許可が必要になることがある）。
