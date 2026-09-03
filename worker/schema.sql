-- 生サンプルだけを溜める。加工は Python 側が行うので、ここでは一切解釈しない。
CREATE TABLE IF NOT EXISTS samples (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  at        TEXT NOT NULL,   -- ISO8601 (+09:00)
  park_date TEXT NOT NULL,   -- 開園日ベース YYYY-MM-DD（5時未満は前日）
  kind      TEXT NOT NULL,   -- 'wait' | 'dpa'
  payload   TEXT NOT NULL    -- JSON 文字列
);
CREATE INDEX IF NOT EXISTS idx_samples ON samples(park_date, kind, at);

-- 発火の物証。「登録した」ではなく「動いた」を残す。
CREATE TABLE IF NOT EXISTS heartbeat (
  cron      TEXT PRIMARY KEY,
  last_at   TEXT NOT NULL,
  last_note TEXT,
  runs      INTEGER NOT NULL DEFAULT 0,
  errors    INTEGER NOT NULL DEFAULT 0
);
