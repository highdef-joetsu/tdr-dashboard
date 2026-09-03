"""Cloudflare Worker が溜めた生サンプルを取り込み、日次ファイルを組み直す。

GitHub の cron は高頻度スケジュールの大半を実行しないため、取得は Worker が行う
（正本: worker/src/index.js）。ここはその生サンプルを読んで、
既存の wait_times / dpa と同じロジックで日次ファイルを作る。

**毎回ゼロから組み直す。** サンプルの集合に対する純粋な関数にしておけば、
何度動いても・途中で失敗しても、二重に追記されることがない。
"""
from __future__ import annotations

import os

from . import common as c
from . import dpa as D
from . import wait_times as W

PARKS = ("tdl", "tds")


def fetch_samples(date: str) -> list[dict]:
    base = os.environ.get("TDR_WORKER_URL", "").rstrip("/")
    token = os.environ.get("TDR_INGEST_TOKEN", "")
    if not base or not token:
        raise RuntimeError("TDR_WORKER_URL と TDR_INGEST_TOKEN が要る")
    import requests

    r = requests.get(f"{base}/samples", params={"date": date},
                     headers={"Authorization": f"Bearer {token}",
                              "User-Agent": c.USER_AGENT}, timeout=c.TIMEOUT)
    r.raise_for_status()
    return r.json().get("samples") or []


def build_waits(samples: list[dict], date: str, mapping: dict) -> dict:
    """待ち時間の日次ファイルを、サンプル列から丸ごと作る（純関数）。"""
    doc = {"date": date, "source": "queue-times.com", "parks": {}}
    for s in samples:
        if s.get("kind") != "wait":
            continue
        park = (s.get("data") or {}).get("park")
        if park not in PARKS:
            continue
        sample = W.sample_park(s["data"], mapping, park)
        doc["parks"][park] = W.merge_sample(doc["parks"].get(park, {}), sample, s["at"])
    return doc


def build_dpa(samples: list[dict], date: str, mapping: dict, hours: dict) -> dict:
    """DPAの日次ファイルを、サンプル列から丸ごと作る（純関数）。"""
    from datetime import datetime

    doc = {"date": date, "source": "themeparks.wiki", "attractions": {}, "hours": hours}
    unknown: set[str] = set()
    last_at = None
    for s in samples:
        if s.get("kind") != "dpa":
            continue
        snap, unk = D.snapshot(s.get("data") or {}, mapping)
        unknown |= set(unk)
        at = s["at"]
        last_at = at
        try:
            when = datetime.fromisoformat(at)
        except ValueError:
            continue
        for park in PARKS:
            sub = {k: v for k, v in snap.items() if v["park"] == park}
            if not sub:
                continue
            doc = D.apply_snapshot(doc, sub, at, D.within_operating(hours.get(park), when))
    if unknown:
        doc["unknown_states"] = sorted(unknown)
    if last_at:
        doc["last_polled_at"] = last_at
    return doc


def collect() -> str:
    date = str(c.park_date())
    samples = fetch_samples(date)
    if not samples:
        return f"{date} サンプル0件（営業時間外か、Worker がまだ動いていない）"

    wait_doc = build_waits(samples, date, c.by_queue_times_id())
    c.write_json(c.DATA / "waits" / f"{date}.json", wait_doc)

    # 営業時間は1日1回だけ取りに行き、既存ファイルにあれば再利用する
    existing = c.read_json(c.DATA / "dpa" / f"{date}.json") or {}
    hours = existing.get("hours")
    if not hours:
        cfg = c.settings()["themeparks"]
        hours = {p: D.park_hours(pid) for p, pid in cfg["parks"].items()}
    dpa_doc = build_dpa(samples, date, c.by_themeparks_id(), hours)

    # 価格は断続的に欠けるので台帳から埋め戻す（dpa.py と同じ扱い）
    ledger = (c.read_json(c.DATA / "dpa" / "prices.json", {}) or {}).get("prices") or {}
    for key, rec in dpa_doc["attractions"].items():
        if not rec.get("price") and ledger.get(key):
            rec["price"] = ledger[key]["amount"]
            rec["price_source"] = "ledger"
    c.write_json(c.DATA / "dpa" / f"{date}.json", dpa_doc)

    n_wait = sum(1 for s in samples if s.get("kind") == "wait")
    n_dpa = sum(1 for s in samples if s.get("kind") == "dpa")
    return f"{date} 待ち{n_wait}件 DPA{n_dpa}件 から再構成"


if __name__ == "__main__":
    c.main("ingest", collect)
