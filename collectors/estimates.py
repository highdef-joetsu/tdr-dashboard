"""蓄積した DPA 実績から、混雑度帯 × 施設 の売切目安を算出する。"""
from __future__ import annotations

import statistics

from . import common as c

BANDS = [("0-30", 0, 30), ("31-60", 31, 60), ("61-80", 61, 80), ("81-100", 81, 100)]
MIN_SAMPLES = 3


def band_of(pct: int | None) -> str | None:
    if pct is None:
        return None
    for name, lo, hi in BANDS:
        if lo <= pct <= hi:
            return name
    return None


def _minutes(iso_ts: str) -> int:
    """ISO時刻 → その日の0時からの分。中央値を時刻として扱うため。"""
    from datetime import datetime

    d = datetime.fromisoformat(iso_ts).astimezone(c.JST)
    return d.hour * 60 + d.minute


def _hhmm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


def compute(days: list[dict], crowd: dict, attractions: list[dict]) -> dict:
    """days: dpa/YYYY-MM-DD.json のリスト。crowd: crowd/calendar.json。"""
    park_of = {a["key"]: a["park"] for a in attractions}
    buckets: dict[tuple[str, str], list[int]] = {}

    for doc in days:
        date = doc.get("date")
        for key, rec in (doc.get("attractions") or {}).items():
            ts = rec.get("first_sold_out_at")
            if not ts:
                continue
            park = park_of.get(key)
            pct = ((crowd.get("parks", {}).get(park) or {}).get(date) or {}).get("crowd_pct")
            band = band_of(pct)
            if not band:
                continue
            buckets.setdefault((key, band), []).append(_minutes(ts))

    bootstrap = c.read_json(c.CONFIG / "dpa_estimates_bootstrap.json", {}) or {}
    boot = bootstrap.get("attractions", {})

    out: dict[str, dict] = {}
    for a in attractions:
        if not a.get("dpa"):
            continue
        key = a["key"]
        out[key] = {}
        for band, _lo, _hi in BANDS:
            samples = buckets.get((key, band), [])
            if len(samples) >= MIN_SAMPLES:
                out[key][band] = {
                    "median": _hhmm(statistics.median(samples)),
                    "samples": len(samples),
                    "source": "observed",
                }
            else:
                out[key][band] = {
                    "median": (boot.get(key) or {}).get(band),
                    "samples": len(samples),
                    "source": "bootstrap",
                }
    return {"generated_at": c.iso(c.now_jst()), "min_samples": MIN_SAMPLES, "attractions": out}


def collect() -> str:
    days = [c.read_json(p) for p in sorted((c.DATA / "dpa").glob("20*.json"))]
    days = [d for d in days if d]
    crowd = c.read_json(c.DATA / "crowd" / "calendar.json", {}) or {}
    doc = compute(days, crowd, c.attractions())
    c.write_json(c.DATA / "dpa" / "estimates.json", doc)
    observed = sum(1 for v in doc["attractions"].values()
                   for b in v.values() if b["source"] == "observed")
    return f"実績日数{len(days)} observed帯{observed}"


if __name__ == "__main__":
    c.main("estimates", collect)
