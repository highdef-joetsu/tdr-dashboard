# tdr-collector（Cloudflare Worker）

待ち時間とDPA販売状況の**取得だけ**を担う。加工・統合は GitHub 側の Python が行う。

## なぜ Cloudflare に移したか

GitHub Actions の `schedule` は高頻度の cron をほとんど実行しない。実測（2026-09-03、
JST 8:00–22:00 の稼働枠）:

| | 期待 | 実際 |
|---|---|---|
| DPA（5分ごと） | 約168本 | **1本** |
| 待ち時間（10分ごと） | 約84本 | **1本** |

しかも唯一の発火は 23:20 JST で、最終スロット（21:55）から **87分遅れ**。
DPAの売切時刻も待ち時間カーブも、この歩留まりでは成立しない。

Cloudflare の Cron Triggers に取得を移し、GitHub には `repository_dispatch`
（cron ではなくイベント）で取り込みを依頼する。

## 役割分担

| 担当 | 何をするか |
|---|---|
| Worker `*/5` | Queue-Times と ThemeParks.wiki を叩き、**生のまま** D1 に入れる |
| Worker `*/20` | GitHub に `repository_dispatch` を投げ、古い行（4日より前）を消す |
| GitHub `ingest.yml` | Worker から生サンプルを取り、日次ファイルを**毎回ゼロから組み直す** |

Worker は施設の対応付けも売切判定もしない。同じロジックを2箇所に持たないため。
取り込みはサンプル列に対する純粋な関数なので、何度動いても二重に追記されない。

## セットアップ

```bash
cd app/tdr-dashboard/worker

# 1. Cloudflare にログイン（ブラウザが開く）
npx wrangler login

# 2. D1 を作り、出力された database_id を wrangler.toml に貼る
npx wrangler d1 create tdr_samples

# 3. スキーマを本番に流す
npx wrangler d1 execute tdr_samples --remote --file schema.sql

# 4. シークレットを2つ入れる（値は画面に出さない）
#    GITHUB_TOKEN : このリポジトリに Contents:write を持つ fine-grained PAT
#    INGEST_TOKEN : /samples を守る共有シークレット（openssl rand -hex 32 で作る）
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put INGEST_TOKEN

# 5. デプロイ
npx wrangler deploy
```

デプロイ後、GitHub 側にも同じ値を登録する。

```bash
gh secret set TDR_WORKER_URL   --body "https://tdr-collector.<サブドメイン>.workers.dev"
gh secret set TDR_INGEST_TOKEN --body "<INGEST_TOKEN と同じ値>"
```

## エンドポイント

| パス | 認証 | 用途 |
|---|---|---|
| `/live` | **不要** | 最新1件の生値。ダッシュボードがこれを読んで「現在の待ち時間」「今のDPA販売状況」を出す |
| `/samples?date=` | Bearer | 当日の全生サンプル。GitHub の取り込みが使う |
| `/health` | Bearer | cron ごとの発火実績 |

`/live` を認証なしにしているのは、中身が Queue-Times と ThemeParks.wiki の
公開データそのままで、秘匿するものが無いため。60秒キャッシュを付けてある。
**施設の対応付けはここでは行わない**（対応表は latest.json 側が持ち、ブラウザが突き合わせる）。
Worker にロジックを持たせない方針を崩さないため。

## 動いているかの確認

**「登録した」は証拠にならない。** 発火の物証を D1 の `heartbeat` に残してある。

```bash
# ハートビート（cron ごとの最終実行時刻・回数・エラー数）
curl -sS -H "Authorization: Bearer $INGEST_TOKEN" \
  https://tdr-collector.<サブドメイン>.workers.dev/health | python3 -m json.tool

# 当日の生サンプル件数
curl -sS -H "Authorization: Bearer $INGEST_TOKEN" \
  "https://tdr-collector.<サブドメイン>.workers.dev/samples?date=$(date +%F)" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['date'], d['count'], '件')"
```

営業時間（JST 8:00–22:00）の外では `collect` は何もしない。`heartbeat` の
`last_note` に「営業時間外のため取得しない」と入る。これは正常。

## 費用

無料枠に収まる。5分ごと＝288回/日、20分ごと＝72回/日で、Workers の
1日10万リクエストに対して桁が違う。D1 の書き込みは1回3行 × 168回（稼働枠）で
1日約500行、無料枠10万行/日に対して十分小さい。
