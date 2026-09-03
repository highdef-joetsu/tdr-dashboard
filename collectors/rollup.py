"""90日より古い waits/dpa の生サンプルを日次サマリーに丸める（月1実行）。"""
from __future__ import annotations

from datetime import timedelta

from . import common as c

KEEP_DAYS = 90


def rollup_waits(doc: dict) -> dict:
    """samples を捨て、daily_max / last だけ残す。"""
    doc = dict(doc)
    for park, p in (doc.get("parks") or {}).items():
        p = dict(p)
        p.pop("samples", None)
        p["rolled_up"] = True
        doc["parks"][park] = p
    return doc


def rollup_dpa(doc: dict) -> dict:
    """events を捨て、売切時刻と再販有無だけ残す。"""
    doc = dict(doc)
    for key, rec in (doc.get("attractions") or {}).items():
        rec = dict(rec)
        rec["resale"] = any(e.get("note") == "resale" for e in rec.get("events") or [])
        rec.pop("events", None)
        rec["rolled_up"] = True
        doc["attractions"][key] = rec
    return doc


def collect() -> str:
    cutoff = str(c.park_date() - timedelta(days=KEEP_DAYS))
    n = 0
    for sub, fn in (("waits", rollup_waits), ("dpa", rollup_dpa)):
        for path in sorted((c.DATA / sub).glob("20*.json")):
            if path.stem >= cutoff:
                continue
            doc = c.read_json(path)
            if not doc or doc.get("rolled_up_at"):
                continue
            doc = fn(doc)
            doc["rolled_up_at"] = c.iso(c.now_jst())
            c.write_json(path, doc)
            n += 1
    return f"{n}ファイルを丸めた (cutoff={cutoff})"


if __name__ == "__main__":
    c.main("rollup", collect)
