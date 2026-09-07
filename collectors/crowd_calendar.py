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


def keep_forecast(prev: dict | None, fresh: dict, date_str: str, today: str) -> int | None:
    """その日の「予想」を保つ（純関数）。日を過ぎたら凍結する。

    Queue-Times の混雑度は2種類が同じ欄に入る。日を過ぎると実績値で上書きされ、
    実測（2026-09-06 TDS）では 予想62% → 実績16% と48ポイント動いて帯を2つまたいだ。
    未来日の予想も日々わずかに更新される（9/17 は 66% → 64%）。

    来園日には実績が存在しないので、蓄積側を実績・来園日を予想で突き合わせると
    別の物差しを比べることになる。帯の判定は常に予想同士で行う。

    - 未来日: まだ予想なので、最新の予想を追い続ける
    - 当日・過去日: その朝に見えていた予想で凍結する（実績で上書きさせない）

    実績（最新値）は crowd_pct にそのまま残るので、予想の当たり外れは後から見られる。
    """
    if date_str > today:
        return fresh.get("crowd_pct")
    if prev and prev.get("forecast_pct") is not None:
        return prev["forecast_pct"]
    if prev and prev.get("crowd_pct") is not None:
        return prev["crowd_pct"]
    return fresh.get("crowd_pct")


def collect() -> str:
    path = c.DATA / "crowd" / "calendar.json"
    doc = c.read_json(path) or {"source": "queue-times.com", "parks": {}}
    today = str(c.park_date())
    counts = []
    for park, pid in c.settings()["queue_times"].items():
        html = c.get_text(f"https://queue-times.com/parks/{pid}/calendar")
        days = parse_calendar(html)
        if not days:
            raise RuntimeError(f"{park}: カレンダーを1日も解析できなかった（HTML構造の変更を疑う）")
        # 既存を保持しつつ上書き（月替わりで前月分を失わない）
        merged = dict(doc["parks"].get(park) or {})
        for ds, rec in days.items():
            merged[ds] = {**rec, "forecast_pct": keep_forecast(merged.get(ds), rec, ds, today)}
        doc["parks"][park] = merged
        counts.append(f"{park}={len(days)}日")
    doc["fetched_at"] = c.iso(c.now_jst())
    c.write_json(path, doc)
    return " ".join(counts)


if __name__ == "__main__":
    c.main("crowd_calendar", collect)
