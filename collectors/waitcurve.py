"""待ち時間の「時間帯別カーブ」を混雑度帯ごとに作り、DPAを買う価値を計算する。

Queue-Times は現在値しか返さず、DPA を持っているのは ThemeParks.wiki。
両方を日次で蓄積しているので、「同じ混雑度の日に、この施設は何時が何分だったか」
を出せる。これは待ち時間だけ／DPAだけを見ているサイトには作れない。
"""
from __future__ import annotations

import statistics
from datetime import datetime

from . import common as c
from .estimates import BANDS, band_of

MIN_DAYS = 3          # この日数そろわない時間帯は出さない
LATE_FROM_HOUR = 15   # 「夕方に並び直す」の起点


def _hour(iso_ts: str) -> int:
    return datetime.fromisoformat(iso_ts).astimezone(c.JST).hour


def build_curves(wait_docs: list[dict], crowd: dict, attractions: list[dict]) -> dict:
    """curves[key][band][hour] = {"median": 分, "days": 日数} を返す（純関数）。"""
    park_of = {a["key"]: a["park"] for a in attractions}
    # (key, band, hour) -> {date: [分, ...]}
    acc: dict[tuple, dict[str, list[int]]] = {}

    for doc in wait_docs:
        date = doc.get("date")
        for park, p in (doc.get("parks") or {}).items():
            pct = ((crowd.get("parks", {}).get(park) or {}).get(date) or {}).get("crowd_pct")
            band = band_of(pct)
            if not band:
                continue
            for s in p.get("samples") or []:
                try:
                    h = _hour(s["at"])
                except (KeyError, ValueError):
                    continue
                for key, minutes in (s.get("waits") or {}).items():
                    if minutes is None or park_of.get(key) != park:
                        continue
                    acc.setdefault((key, band, h), {}).setdefault(date, []).append(minutes)

    curves: dict = {}
    for (key, band, h), per_day in acc.items():
        if len(per_day) < MIN_DAYS:
            continue
        # 1日1値（その時間帯の中央値）にしてから日をまたいで中央値を取る。
        # 同じ日に何度もサンプルがあっても、その日が重く効かないようにする。
        per_day_median = [statistics.median(v) for v in per_day.values()]
        curves.setdefault(key, {}).setdefault(band, {})[str(h)] = {
            "median": round(statistics.median(per_day_median)),
            "days": len(per_day),
        }
    return curves


def advise(curve_band: dict | None, price: int | None, sold_out_at: str | None) -> dict:
    """1施設・1混雑帯についてDPAを買う価値を計算する（純関数）。

    判定の閾値は説明可能な形で持ち、根拠になる数値も一緒に返す。
    UI は判定だけでなく計算に使った数値も出す。
    """
    if not curve_band:
        return {"verdict": "insufficient", "reason": "同じ混雑度の日のデータがまだ足りない"}

    hours = {int(h): v["median"] for h, v in curve_band.items()}
    peak_h = max(hours, key=lambda h: hours[h])
    late = {h: m for h, m in hours.items() if h >= LATE_FROM_HOUR}
    if not late:
        return {"verdict": "insufficient", "reason": f"{LATE_FROM_HOUR}時以降のデータがまだ足りない"}
    late_h = min(late, key=lambda h: late[h])

    peak, late_min = hours[peak_h], late[late_h]
    saved = peak - late_min
    out = {
        "peak": {"hour": peak_h, "minutes": peak},
        "late": {"hour": late_h, "minutes": late_min},
        "saved_minutes": saved,
        "price": price,
        "sold_out_at": sold_out_at,
        "hours_covered": len(hours),
    }
    if price and saved > 0:
        out["yen_per_minute"] = round(price / saved)

    # 判定ルール（数値は上に出しているので、納得できなければ自分で読み替えられる）
    if late_min <= 40:
        out["verdict"] = "skip"
        out["reason"] = f"{late_h}時台なら並んでも約{late_min}分。買わずに後で並べば足りる"
    elif saved >= 60 and out.get("yen_per_minute", 999) <= 40:
        out["verdict"] = "buy"
        out["reason"] = f"ピーク{peak}分に対し{late_h}時台でも{late_min}分。{saved}分短縮で1分あたり約{out['yen_per_minute']}円"
    else:
        out["verdict"] = "depends"
        out["reason"] = f"ピーク{peak}分／{late_h}時台{late_min}分。短縮{saved}分で、価値は滞在計画次第"
    return out


def collect() -> str:
    wait_docs = [c.read_json(p) for p in sorted((c.DATA / "waits").glob("20*.json"))]
    wait_docs = [d for d in wait_docs if d]
    crowd = c.read_json(c.DATA / "crowd" / "calendar.json", {}) or {}
    curves = build_curves(wait_docs, crowd, c.attractions())
    c.write_json(c.DATA / "waits" / "curves.json", {
        "generated_at": c.iso(c.now_jst()),
        "min_days": MIN_DAYS,
        "late_from_hour": LATE_FROM_HOUR,
        "days_used": len(wait_docs),
        "curves": curves,
    })
    filled = sum(len(h) for v in curves.values() for h in v.values())
    return f"{len(wait_docs)}日分から {len(curves)}施設 / 時間帯{filled}枠"


if __name__ == "__main__":
    c.main("waitcurve", collect)
