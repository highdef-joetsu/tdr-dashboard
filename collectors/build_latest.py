"""ダッシュボードが読む唯一のファイル docs/data/latest.json を組み立てる。"""
from __future__ import annotations

from datetime import timedelta

from . import common as c

PARKS = ("tdl", "tds")


def target_date(today, watch_dates: list[str]) -> str:
    """来園予定日。未来の watch_dates のうち最も近い日、無ければ明日。"""
    future = sorted(d for d in watch_dates if d >= str(today))
    return future[0] if future else str(today + timedelta(days=1))


def closures_for(official: dict | None, park: str, day: str) -> dict:
    """当日休止 と 期間休止 の和集合をカテゴリ別に返す。"""
    out: dict[str, list] = {}
    if not official:
        return out
    entry = (official.get("parks") or {}).get(park) or {}
    for cat, names in (entry.get("closures_today") or {}).items():
        for n in names:
            out.setdefault(cat, []).append({"name": n, "from": None, "to": None,
                                            "undecided": False, "source": "daily"})
    for item in (official.get("closures_schedule") or {}).get(park) or []:
        frm, to = item.get("from"), item.get("to")
        if frm and frm > day:
            continue
        if to and to < day:
            continue
        if not frm and not item.get("undecided"):
            continue
        cat = item["category"]
        names = {x["name"] for x in out.get(cat, [])}
        if item["name"] in names:
            for x in out[cat]:
                if x["name"] == item["name"]:
                    x.update({"from": frm, "to": to, "undecided": item.get("undecided", False),
                              "source": "both"})
        else:
            out.setdefault(cat, []).append({
                "name": item["name"], "from": frm, "to": to,
                "undecided": item.get("undecided", False), "source": "schedule"})
    return out


def waits_summary(waits: dict | None) -> dict:
    if not waits:
        return {}
    out = {}
    for park in PARKS:
        p = (waits.get("parks") or {}).get(park) or {}
        out[park] = {
            "daily_max": p.get("daily_max") or {},
            "last": p.get("last") or {},
        }
    return out


def dpa_recent(days: list[dict], crowd: dict, park_of: dict, limit: int = 7) -> list[dict]:
    out = []
    for doc in sorted(days, key=lambda d: d.get("date", ""), reverse=True)[:limit]:
        date = doc.get("date")
        row = {"date": date, "crowd_pct": {}, "attractions": {}}
        for park in PARKS:
            row["crowd_pct"][park] = ((crowd.get("parks", {}).get(park) or {})
                                      .get(date) or {}).get("crowd_pct")
        for key, rec in (doc.get("attractions") or {}).items():
            if not rec.get("first_sold_out_at"):
                continue
            row["attractions"][key] = {
                "first_sold_out_at": rec["first_sold_out_at"],
                "final_sold_out_at": rec.get("final_sold_out_at"),
                "resale": any(e.get("note") == "resale" for e in rec.get("events") or []),
            }
        out.append(row)
    return out


def build() -> dict:
    today = c.park_date()
    st = c.settings()
    tgt = target_date(today, st.get("watch_dates", []))
    tomorrow = str(today + timedelta(days=1))
    attractions = c.attractions()
    park_of = {a["key"]: a["park"] for a in attractions}

    crowd = c.read_json(c.DATA / "crowd" / "calendar.json", {}) or {}
    waits = c.read_json(c.DATA / "waits" / f"{today}.json")
    dpa_today = c.read_json(c.DATA / "dpa" / f"{today}.json")
    estimates = c.read_json(c.DATA / "dpa" / "estimates.json")
    health = c.read_health()

    dates = sorted({str(today), tomorrow, tgt})
    official = {d: c.read_json(c.DATA / "official" / f"{d}.json") for d in dates}

    days = [c.read_json(p) for p in sorted((c.DATA / "dpa").glob("20*.json"))]
    days = [d for d in days if d]

    closures = {}
    for d in dates:
        closures[d] = {park: closures_for(official.get(d), park, d) for park in PARKS}

    # 期間休止(closures_schedule)は3日分に同じものが入っており、
    # 日付判定済みの closures に畳んである。latest.json では落として二重持ちを避ける。
    slim = {}
    for d, doc in official.items():
        if not doc:
            slim[d] = None
            continue
        doc = {k: v for k, v in doc.items() if k != "closures_schedule"}
        doc["parks"] = {
            park: {k: v for k, v in (entry or {}).items() if k != "closures_today"}
            for park, entry in (doc.get("parks") or {}).items()
        }
        slim[d] = doc
    official = slim

    return {
        "generated_at": c.iso(c.now_jst()),
        "dates": {"today": str(today), "tomorrow": tomorrow, "target": tgt},
        "attractions": [
            {"key": a["key"], "park": a["park"], "name_ja": a["name_ja"],
             "dpa": a.get("dpa", False), "watch": a.get("watch", True)}
            for a in attractions
        ],
        "crowd": {
            park: {d: ((crowd.get("parks", {}).get(park) or {}).get(d)) for d in dates}
            for park in PARKS
        },
        "crowd_fetched_at": crowd.get("fetched_at"),
        "official": official,
        "closures": closures,
        "waits": waits_summary(waits),
        "waits_fetched_at": ((waits or {}).get("parks", {}).get("tds", {}).get("last") or {}).get("at"),
        "dpa_today": dpa_today,
        "dpa_estimates": estimates,
        "dpa_recent": dpa_recent(days, crowd, park_of),
        "health": health,
    }


def collect() -> str:
    doc = build()
    c.write_json(c.DATA / "latest.json", doc)
    return f"target={doc['dates']['target']}"


if __name__ == "__main__":
    c.main("build_latest", collect)
