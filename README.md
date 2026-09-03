# 東京ディズニーリゾート 来園計画ダッシュボード

明日（または指定日）の来園判断に必要な情報を1画面に集める個人用ツール。
GitHub Actions がデータを収集してリポジトリにコミットし、GitHub Pages が静的に配信する。

**非公式。東京ディズニーリゾートおよび関連会社とは一切関係がない。**

- ダッシュボード: `docs/index.html`（Pages 有効化後は `https://<owner>.github.io/<repo>/`）
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
5. **DPA売切目安は実績が溜まるまで出ない。** 混雑度帯ごとに3件たまるまでは
   `config/dpa_estimates_bootstrap.json` を使う（現在すべて `null` = 「データなし」表示）。
   来園日 2026-09-17 までに3件揃うのは、同じ混雑度帯の日が3日以上ある場合に限る。
   **初回来園には実質間に合わない。** 手で目安を入れるなら bootstrap を埋める。
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

### public / private について

**Actions の実行時間の都合で、実質 public でないと運用できない。**
DPA が5分ごと・待ち時間が10分ごとで、JST 8:00〜21:30 だけ回しても月およそ7,500分になる。
private リポジトリの無料枠は月2,000分なので数日で尽きる。public リポジトリは Actions 無料・Pages 無料。

public にすると **来園予定日（`config/settings.json` の `watch_dates`）が公開される**。
それが困る場合は、頻度を落として private のままにするか、`watch_dates` を空にして
`?date=2026-09-17` で見る運用にする。

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
- **日付境界は開園日ベース。** 5:00 JST 未満は前日として扱う（`park_day_boundary_hour`）。
