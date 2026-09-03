"""コレクタ共通: HTTP・JST時刻・原子的なJSON保存・ヘルス記録。"""
from __future__ import annotations

import json
import os
import pathlib
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
import yaml

JST = timezone(timedelta(hours=9), "JST")
USER_AGENT = "tdr-plan-dashboard/0.1 (personal use)"
TIMEOUT = 15
RETRIES = 3

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
# GitHub Pages を /docs から配信するため、データも docs 配下に置く。
# ルート直下の data/ に置くと Pages から参照できない。
DATA = ROOT / "docs" / "data"


def log(msg: str) -> None:
    print(f"[{datetime.now(JST):%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


# ---------- 時刻 ----------

def now_jst() -> datetime:
    return datetime.now(JST)


def iso(dt: datetime) -> str:
    return dt.astimezone(JST).isoformat(timespec="seconds")


def park_date(at: datetime | None = None) -> date:
    """開園日ベースの日付。5:00 JST 未満は前日扱い。"""
    at = at or now_jst()
    at = at.astimezone(JST)
    boundary = settings().get("park_day_boundary_hour", 5)
    return (at - timedelta(hours=boundary)).date()


# ---------- 設定 ----------

_settings_cache: dict | None = None


def settings() -> dict:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = json.loads((CONFIG / "settings.json").read_text("utf-8"))
    return _settings_cache


def attractions() -> list[dict]:
    return yaml.safe_load((CONFIG / "attractions.yaml").read_text("utf-8"))


def by_queue_times_id() -> dict[int, dict]:
    return {a["queue_times_id"]: a for a in attractions() if a.get("queue_times_id")}


def by_themeparks_id() -> dict[str, dict]:
    return {a["themeparks_id"]: a for a in attractions() if a.get("themeparks_id")}


# ---------- HTTP ----------

class TransientError(RuntimeError):
    """通信の一時的な失敗。これだけは Actions を赤くしない。

    TypeError などのコードの不具合まで握り潰すと、ワークフローが緑のまま
    データが増えない状態になる（実測: ingest が TypeError で全滅したのに
    ワークフローは成功扱いだった）。
    """


def _sleep_backoff(attempt: int) -> None:
    time.sleep(min(30, (2 ** attempt) + random.random()))


def http_get(url: str, *, accept: str = "*/*") -> requests.Response:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": accept},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"  取得失敗 ({attempt + 1}/{RETRIES}) {url}: {type(e).__name__}")
            if attempt < RETRIES - 1:
                _sleep_backoff(attempt)
    raise TransientError(f"{url} の取得に3回失敗: {last}")


def get_json(url: str):
    return http_get(url, accept="application/json").json()


def get_text(url: str) -> str:
    return http_get(url, accept="text/html").text


# ---------- JSON 入出力 ----------

def read_json(path: pathlib.Path, default=None):
    try:
        return json.loads(path.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: pathlib.Path, obj) -> None:
    """一時ファイル → rename の原子的保存。途中で落ちても既存を壊さない。

    TDR_WRITE_MANIFEST が指定されていれば、書いたパスをそこに追記する。
    CI は他のワークフローの push と衝突したとき、この一覧だけを
    最新の origin/main の上に置き直して作り直す。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)
    manifest = os.environ.get("TDR_WRITE_MANIFEST")
    if manifest:
        with open(manifest, "a", encoding="utf-8") as f:
            f.write(str(path.relative_to(ROOT)) + "\n")


# ---------- ヘルス ----------

def read_health() -> dict:
    """コレクタごとの health ファイルを1つの辞書にまとめる。"""
    out = {}
    for p in sorted((DATA / "health").glob("*.json")):
        v = read_json(p)
        if v:
            out[p.stem] = v
    return out


def record_health(collector: str, ok: bool, detail: str = "") -> None:
    # 1ファイルを全コレクタで共有すると、並行するワークフローの push が
    # 必ず衝突する。コレクタごとに分けて衝突の芽を消す。
    path = DATA / "health" / f"{collector}.json"
    h = {collector: read_json(path, {}) or {}}
    entry = h.get(collector, {"consecutive_failures": 0})
    if ok:
        entry["consecutive_failures"] = 0
        entry["last_success_at"] = iso(now_jst())
    else:
        entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
        entry["last_failure_at"] = iso(now_jst())
    entry["last_run_at"] = iso(now_jst())
    entry["last_detail"] = detail
    write_json(path, entry)


def _annotate(msg: str) -> None:
    """GitHub Actions のログに目立つ形で残す。"""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=collector::{msg}", flush=True)


def run(collector: str, fn) -> int:
    """コレクタ本体を包む。失敗してもActionsを赤くせず(終了コード0)、health に残す。"""
    try:
        detail = fn() or ""
        record_health(collector, True, str(detail))
        log(f"{collector}: 成功 {detail}")
    except TransientError as e:
        # 通信の一時失敗。health に残し、終了コードは0のまま（赤くしない）。
        record_health(collector, False, f"{type(e).__name__}: {e}")
        log(f"{collector}: 取得失敗（一時的）{e}")
        _annotate(f"{collector}: 取得に失敗した（一時的とみなす）: {e}")
        return 0
    except Exception as e:  # noqa: BLE001
        # コードの不具合・設定漏れ・解析破綻。これは黙って通さない。
        import traceback

        traceback.print_exc()
        record_health(collector, False, f"{type(e).__name__}: {e}")
        log(f"{collector}: 失敗 {type(e).__name__}: {e}")
        _annotate(f"{collector}: {type(e).__name__}: {e}")
        return 1
    return 0


def main(collector: str, fn) -> None:
    sys.exit(run(collector, fn))
