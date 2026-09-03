# 東京ディズニーリゾート 来園計画ダッシュボード

明日（または指定日）の来園判断に必要な情報を1画面に集める個人用ツール。
GitHub Actions がデータを収集してリポジトリにコミットし、GitHub Pages が静的に配信する。

**非公式。東京ディズニーリゾートおよび関連会社とは一切関係がない。**

- ダッシュボード: https://highdef-joetsu.github.io/tdr-dashboard/ （ソースは `docs/index.html`）
- 日付を変える: `?date=YYYY-MM-DD`
- 来園予定日: `config/settings.json` の `watch_dates` に入れる（現在 `2026-09-17`）

## Phase 0 で実測した制約（重要）

### 公式サイトは headless ブラウザを弾く

`www.tokyodisneyresort.jp` は Akamai 配下にあり、**curl / Python requests / headless Chromium は
TCPは繋がるがHTTPレスポンスが返らない**（無応答でドロップされる）。実測:

| 経路 | 結果 |
|---|---|
| `curl`（自前UA / ブラウザUA / HTTP1.1 / HTTP2 / sec-ch-ua 付き） | 全てタイムアウト |
| Python `requests`（ブラウザ風ヘッダ一式） | `ReadTimeout` |
| Playwright Chromium **headless** | `goto` タイムアウト |
| Playwright Chromium **headed** | **200 OK** |
| Playwright 実Chrome **headless** | タイムアウト |
| Playwright 実Chrome **headed** | **200 OK** |

このため `collectors/official.py` は Playwright を **headed** で動かし、CI では **xvfb** 配下で実行する。
依存に `playwright` が入っているのはこの理由による（当初仕様の「requests / bs4 / pytest のみ」から逸脱）。

さらに**連続アクセスで 403 になる**。1.2秒間隔だと2件目以降が全て403。
ブラウザコンテキストをページごとに作り直し、`official_fetch_gap_seconds`（既定20秒）空けると全て200になる。
1回の実行で 8ページ（2パーク × 3日 + stop.html × 2）取るため、約3〜4分かかる。

### データ源

| 用途 | 取得元 | 認証 | 備考 |
|---|---|---|---|
| 待ち時間・混雑度 | Queue-Times.com | 不要 | park id: TDL=274 / TDS=275。**表示義務あり**（下記） |
| DPA販売状況 | ThemeParks.wiki | 不要 | destination `tdr`（slug は `tokyodisneyresort` ではない） |
| 開園時間・チケット・ショー・休止 | 公式サイト | 不要 | 上記のとおり headed ブラウザが必要 |

Queue-Times の利用条件により、ダッシュボードに **"Powered by Queue-Times.com"** と
`https://queue-times.com/` へのリンクを表示している。**フッタから消さないこと。**

### DPA は TDR でも取れる（当初の未検証事項をクリア）

`GET /entity/faff60df-c766-4470-8adb-dee78e813f42/live` の `liveData[].queue.PAID_RETURN_TIME` が
**14施設**で返る（2026-09-03 実測）。観測できた `state` は `AVAILABLE` と `FINISHED` のみ。
`returnStart` / `returnEnd` は全件 `null`、`price.amount` は一部 `0`（`formatted: "Unknown"`）だった。

## 未検証・未解決（読む前に把握すること）

1. **公式サイトの利用規約を確認していない。** 個人利用・低頻度（1日2回）に留めている。
   規約上の可否は未確認のまま。
2. **GitHub Actions の IP から公式サイトに到達できるかは、Actions 上で実行するまで分からない。**
   ローカル（家庭回線）では headed で通ることを確認済み。データセンターIPを Akamai が
   別扱いする可能性がある。失敗した場合は `data/health.json` に記録され、UIが警告を出す。
   恒久的に通らないなら公式データだけ Mac 側の定期実行に移す。
3. **「赤字＝当日開催時間変更」を表すマークアップを特定できていない。**
   注記文言は存在するが、取得した2日分のフィクスチャに変更が無く実物が出現しなかった。
   `div.timetable` 内に子要素または inline style が現れたら `changed: true` とし、
   生マークアップを `changed_markup` に残す実装にしてある。実物が出たらそれを見て確定させる。
4. **`state` の全取り得る値が不明。** `AVAILABLE` / `FINISHED` 以外は「販売中でない」に倒し、
   `unknown_states` に記録する。想定外の値が出たらそこに溜まる。
5. **DPA売切目安は自前の実測が溜まるまで出ない。外部の数値では埋めない。**
   混雑度帯ごとに3件たまるまでは `config/dpa_estimates_bootstrap.json` を使うが、
   意図的にすべて `null`（＝「データなし」表示）にしてある。理由は2つ。

   - **2026年9月1日にDPAの制度が変わった。** 無料のプライオリティパスが8月末で終了し、
     プーさんのハニーハント・ビッグサンダー・マウンテン・モンスターズ・インクの3施設が
     有料DPAへ新規移行、同時に既存施設の価格改定も行われた
     （[トラベルWatch 2026-07-30](https://travel.watch.impress.co.jp/docs/news/2129321.html)、
     [日経](https://www.nikkei.com/article/DGXZQOUC29BVJ0Z20C26A5000000/)）。
     8月以前の売切時刻は条件が異なり、新規3施設は9/1以降のデータしか存在しない。
   - **公開されている数値の突き合わせが取れない。** 同一日・同一施設について情報源間で
     数時間の乖離がある（2026-09-03のソアリンで「14:38」と「午前中〜11時頃」）。
     さらに、独立に見えた2ソースのうち一方が他方と数値完全一致で、裏取りになっていなかった。

   手で入れる場合は `{"median": "HH:MM", "note": "出典と日付"}` の形にすること。
   UIが「暫定」バッジと一緒に note を表示するので、出典のない数字が紛れ込まない。

6. **schedule の起動は遅延・不発がある。** GitHub の cron は最短5分だが定刻には来ない。
   DPA売切時刻の粒度はポーリング間隔ではなく実際の起動間隔で決まる。UIは「10:30頃」と表示する。
7. **60日間コミットが無いと schedule は停止する。** データが毎日コミットされる限り問題ない。

## セットアップ

```bash
pip install -r requirements.txt
python -m playwright install chromium   # official.py に必要
python -m pytest tests/ -v
```

ローカル実行:

```bash
python -m collectors.wait_times
python -m collectors.crowd_calendar
python -m collectors.dpa
python -m collectors.official        # headed ブラウザが開く。3〜4分かかる
python -m collectors.estimates
python -m collectors.build_latest
cd docs && python3 -m http.server 8791   # http://127.0.0.1:8791/
```

### GitHub Pages を有効にする（手動）

1. リポジトリの **Settings → Pages** を開く
2. **Source** を `Deploy from a branch` にする
3. **Branch** を `main`、フォルダを **`/docs`** にして Save
4. 数分後 `https://<owner>.github.io/<repo>/` で表示される

> データは `docs/data/` に置いてある。`/docs` 配信では docs 配下がサイトのルートになるため、
> リポジトリ直下の `data/` はブラウザから読めない。当初仕様の `data/` から移動しているのはこのため。

### public にしている理由

**Actions の実行時間の都合で public にしてある。**
DPA が5分ごと・待ち時間が10分ごとで、JST 8:00〜21:30 だけ回しても月およそ7,500分になる。
private リポジトリの無料枠は月2,000分（Pro でも3,000分）なので、private のままでは
この頻度を維持できない。public リポジトリは Actions 無料・Pages 無料。

その代わり `config/settings.json` の `watch_dates`（来園予定日）と収集データは公開される。
伏せたい場合は `watch_dates` を空にして `?date=YYYY-MM-DD` で見る運用にできるが、
`docs/data/official/<date>.json` が残るので完全には隠れない。

## 取得は Cloudflare Worker が行う

GitHub Actions の `schedule` は高頻度 cron をほとんど実行しない。実測
（2026-09-03、JST 8:00–22:00 の稼働枠）: DPA は期待168本に対し**発火1本**、
待ち時間は期待84本に対し**1本**。しかも唯一の発火が 23:20 JST で、
最終スロット（21:55）から **87分遅れ**だった。この歩留まりでは
待ち時間カーブもDPA売切時刻も成立しない。

そこで取得だけを Cloudflare の Cron Triggers に移した（`worker/`）。

| 担当 | 何をするか | 間隔 |
|---|---|---|
| Worker | Queue-Times / ThemeParks.wiki を叩き、**生のまま** D1 に入れる | 5分 |
| Worker | GitHub に `repository_dispatch` を投げ、4日より前の行を消す | 20分 |
| `ingest.yml` | 生サンプルから日次ファイルを**毎回ゼロから組み直す** | 上の通知で起動 |
| `official.yml` / `crowd.yml` | 公式サイト・混雑カレンダー（GitHub の cron のまま） | 1日1〜2回 |

`repository_dispatch` は cron ではなくイベントなので、GitHub の schedule の
ような取りこぼしが起きない。公式サイトは1日2回で、多少ずれても実害がないため
GitHub 側に残してある。

取り込みには予備の毎時スケジュールも入れてある。**取り込みは D1 の当日分から
毎回ゼロ組み立てし直すので、回が飛んでも失うのは鮮度だけでデータは失われない。**
（取得の欠落だけが回復不能で、そこは Worker が担保している。）

cron の分は**毎時0分を避けてずらしてある**。GitHub 側は毎時0分が最も混み、
実測でも日次の「JST 5:00」実行が 07:10 に発火＝130分遅れだった。

Worker は施設の対応付けも売切判定もしない。**同じロジックを2箇所に持たない**ため、
加工は既存の Python（`wait_times.py` / `dpa.py`）をそのまま使う。取り込みは
サンプル列に対する純粋な関数なので、何度動いても二重に追記されない。

さらに、ダッシュボードは Worker の `/live`（認証不要・60秒キャッシュ）を直接読み、
「現在の待ち時間」と「今のDPA販売状況」を出す。**取り込みの遅れが表示に響かない。**
取り込み側が担うのは当日最大・売切時刻・待ちカーブといった集計だけで、
そこは1時間ずれても実害がない。

`/live` は施設の対応付けをしない。対応表（`queue_times_id` / `themeparks_id`）は
`latest.json` に載せてあり、突き合わせはブラウザが行う。Worker に業務ロジックを
持たせない方針を崩さないため。

セットアップと動作確認の手順は `worker/README.md`。

## 他のサイトに無い部分

待ち時間サイトもDPA完売時刻サイトも混雑予想サイトも既にある。このツールが持つのは、
**それらが構造的に持てない2つ**だけ。

### 1. 変更差分（`docs/data/changes/<date>.json`）

公式サイトも他のサイトも「現在の状態」しか出さない。「前回から何が変わったか」は
過去を持っている側にしか出せない。来園日の情報は掲載後も変わり続ける
（休止の追加、公演時刻の変更、チケット価格の改定、DPA対象施設の変更）。

`official.py` は書き込む前に前回のファイルと突き合わせ、差分を台帳に積む。
実際に2026年9月1日、無料のプライオリティパスが終了して3施設が有料DPAへ移行し、
価格改定も行われた。この種の変化を来園前に拾うのがこの機能の目的。

### 2. DPAの費用対効果（`docs/data/waits/curves.json`）

「DPAを買うべきか」は、買わなかった場合の待ち時間で決まる。判断には3つが要る。

- 時間帯別の待ち時間カーブ（Queue-Times は現在値しか返さないので自前で蓄積）
- 来園日と同じ混雑度帯の日だけを集めた中央値（混雑カレンダーと突き合わせ）
- DPAの価格と売切時刻（ThemeParks.wiki）

3つとも持っているのはここだけ。`waitcurve.advise()` が
「ピーク何分 / 夕方に並び直すと何分 / 何分短縮 / 1分あたり何円」を出し、
判定（買う価値あり / 買わなくてよい / 滞在計画次第 / データ不足）を付ける。
判定の閾値は `waitcurve.py` に定数で置き、根拠の数値も一緒に画面に出す
（判定だけ出して計算を隠すと、閾値が合わないときに読み替えられない）。

同じ混雑帯の日が `MIN_DAYS`（既定3日）たまるまでは「データ不足」と表示する。

## リポジトリ構成

```
collectors/
  common.py           HTTP(リトライ/UA/タイムアウト)・JST時刻・原子的保存・health記録
  wait_times.py       Queue-Times 待ち時間 → docs/data/waits/
  crowd_calendar.py   Queue-Times 混雑カレンダー(HTML) → docs/data/crowd/
  dpa.py              ThemeParks.wiki DPA状態 → docs/data/dpa/
  official.py         公式サイト取得（Playwright headed）
  official_parse.py   公式サイトHTMLのパーサ（純関数・ネットワークに触れない）
  estimates.py        実績から売切目安を算出 → docs/data/dpa/estimates.json
  rollup.py           90日より古い生サンプルを丸める
  build_latest.py     統合して docs/data/latest.json を生成
config/
  attractions.yaml            施設対応表（3系統のID）
  settings.json               park id・destination id・来園予定日
  dpa_estimates_bootstrap.json 売切目安の初期値（未入力）
docs/                 GitHub Pages 配信ルート
  index.html / style.css / app.js
  data/               収集結果（Actions がコミット）
tests/
  fixtures/           Phase 0 で保存した実HTML/JSON
  test_*.py
```

## 設計上の判断

- **取得失敗で Actions を赤くしない。** 終了コードは常に0。連続失敗回数を `docs/data/health.json`
  に記録し、2回以上でダッシュボードが赤く警告する。落ちたことに気づけない状態を作らない。
- **書き込みは一時ファイル→rename の原子的保存。** 途中で落ちても既存ファイルを壊さない。
- **ワークフローごとに concurrency group を分けている。** 全部を1グループにすると
  GitHub が待機ジョブを1本しか保持せず、5分間隔のDPAが黙って捨てられる。
  同時 push は `git pull --rebase` の再試行（最大5回）で吸収する。
- **空と失敗を区別する。** 翌月未掲載は `note: "not_published"`、取得失敗は `note: "fetch_failed"`。
  UIの表示も別にしてある。
- **「終了未定」が長く続く休止は恒久終了として本体から外す。** コロナ以降戻っていない施設
  （2020-07-01 開始が7件ある）は、来園日の判断材料にならない。閾値は
  `settings.json` の `permanent_closure_years`（既定2年）。実データでは
  2022-04-01 と 2025-08-18 の間に3年以上の空白があり、その空白の中ならどこで切っても
  結果が同じなので、区切りの良い2年にしてある。落とさず折りたたみには残す。
- **日付境界は開園日ベース。** 5:00 JST 未満は前日として扱う（`park_day_boundary_hour`）。
