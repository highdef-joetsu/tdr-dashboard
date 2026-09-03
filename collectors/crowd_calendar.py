"""Queue-Times の混雑カレンダー(HTML)から日別の混雑度と開園時間を取る。"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from . import common as c

DATE_RE = re.compile(r"/calendar/(\d{4})/(\d{2})/(\d{2})")
PCT_RE = re.compile(r"(\d{1,3})\s*%")
HOURS_RE = re.compile(r"(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})")


def parse_calendar(html: str) -> dict[str, dict]:
    """{'2026-09-17': {'crowd_pct': 61, 'hours': '09:00-21:00'}} を返す。"""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, dict] = {}
    for a in soup.select("a[href]"):
        m = DATE_RE.search(a["href"])
        if not m:
            continue
        text = a.get_text(" ", strip=True)
        pct = PCT_RE.search(text)
        hours = HOURS_RE.search(text)
        out[f"{m.group(1)}-{m.group(2)}-{m.group(3)}"] = {
            "crowd_pct": int(pct.group(1)) if pct else None,
            "hours": hours.group(1).replace(" ", "") if hours else None,
        }
    return out


def collect() -> str:
    path = c.DATA / "crowd" / "calendar.json"
    doc = c.read_json(path) or {"source": "queue-times.com", "parks": {}}
    counts = []
    for park, pid in c.settings()["queue_times"].items():
        html = c.get_text(f"https://queue-times.com/parks/{pid}/calendar")
        days = parse_calendar(html)
        if not days:
            raise RuntimeError(f"{park}: カレンダーを1日も解析できなかった（HTML構造の変更を疑う）")
        # 既存を保持しつつ上書き（月替わりで前月分を失わない）
        merged = dict(doc["parks"].get(park) or {})
        merged.update(days)
        doc["parks"][park] = merged
        counts.append(f"{park}={len(days)}日")
    doc["fetched_at"] = c.iso(c.now_jst())
    c.write_json(path, doc)
    return " ".join(counts)


if __name__ == "__main__":
    c.main("crowd_calendar", collect)
