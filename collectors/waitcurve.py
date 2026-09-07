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
SKIP_MINUTES = 40     # これ以下で並べるならDPAは要らない
BUY_MINUTES = 60      # これ以上待つならDPAを検討する
YEN_PER_MINUTE = 40   # 1分あたりこれ以下なら割に合う
LASTCALL_HOURS = 1    # 閉園前のこの時間は全施設で枠を取り合う
MIN_HOURS_AHEAD = 2   # これから先がこの数の時間帯に満たないなら判定を出さない

# Queue-Times は列を締め切ったあとも is_open=true のまま wait_time を 0 にする。
# 実測（2026-09-05 TDS）: ソアリンは 19:55 に 80分 → 20:00 に 0分 へ1ステップで落ち、
# is_open が false になったのは 21:05（閉園後）だった。この 0 は「待たずに乗れる」
# ではなく「もう並べない」を意味する。集計に入れると、案内終了の時刻がその施設の
# 「一番空く時間帯」として採用され、DPAの判定が全施設 skip に倒れる。
CLOSED_DROP_FROM = 15   # 直前がこれ以上あって 0 に落ちたら案内終了とみなす
CLOSED_ZERO_RUN = 2     # その 0 がこの回数以上続いたら確定（単発のノイズは拾わない）


def _hour(iso_ts: str) -> int:
    return datetime.fromisoformat(iso_ts).astimezone(c.JST).hour


def drop_after_queue_close(samples: list[dict]) -> list[dict]:
    """施設ごとに「案内終了以降の 0」を落とす（純関数）。

    朝一番の本物の 0（直前に有効値が無い）は残す。落とすのは、まとまった待ちが
    あった施設が 0 に落ち、そのまま 0 が続いた場合だけ。判断は施設ごとに独立で、
    締め切る時刻が施設によって違う実態（同日 20:00 / 20:40 / 20:45）に合わせる。
    """
    series: dict[str, list[int]] = {}
    for i, s in enumerate(samples):
        for key, minutes in (s.get("waits") or {}).items():
            if minutes is not None:
                series.setdefault(key, []).append(i)

    cut: dict[str, int] = {}
    for key, idxs in series.items():
        last_positive = None
        for n, i in enumerate(idxs):
            minutes = samples[i]["waits"][key]
            if minutes > 0:
                last_positive = minutes
                continue
            if last_positive is None or last_positive < CLOSED_DROP_FROM:
                continue
            run = 0
            for j in idxs[n:]:
                if samples[j]["waits"][key] != 0:
                    break
                run += 1
            if run >= CLOSED_ZERO_RUN:
                cut[key] = i
                break

    if not cut:
        return samples
    out = []
    for i, s in enumerate(samples):
        waits = {k: v for k, v in (s.get("waits") or {}).items() if i < cut.get(k, 1 << 30)}
        out.append({**s, "waits": waits})
    return out


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
            for s in drop_after_queue_close(p.get("samples") or []):
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


def advise(curve_band: dict | None, price: int | None, sold_out_at: str | None,
           from_hour: int, close_hour: int) -> dict:
    """ある時刻から先を見て、その施設のDPAに価値があるかを計算する（純関数）。

    比べる相手は「一日で一番空く時間帯」ではなく「これから先で一番空く時間帯」。
    過ぎた時間帯を根拠にしても、その時刻にはもう戻れない。

    ここで出すのは1施設の話だけで、「今この1枠をどれに使うか」は決めない。
    アトラクションのDPAは購入から60分（または利用開始時刻）が過ぎるまで次を
    買えないため、選ぶのは常に1つで、それは施設を横断して比べないと決まらない。
    横断の順位付けと、閉園前の枠の取り合いは画面側が行う。
    """
    out: dict = {"price": price, "sold_out_at": sold_out_at}
    if not curve_band:
        return {**out, "verdict": "insufficient", "reason": "同じ混雑度の日のデータがまだ足りない"}

    hours = {int(h): v["median"] for h, v in curve_band.items()}
    remaining = {h: m for h, m in hours.items() if h >= from_hour}
    if not remaining:
        return {**out, "verdict": "insufficient",
                "reason": f"{from_hour}時以降のデータがまだ足りない"}

    # 閉園前の1時間は全施設で枠を取り合う。ここしか残っていない施設は、
    # 「並べば足りる」の根拠が他の施設と重なっていることを示す印を付ける。
    lastcall_from = close_hour - LASTCALL_HOURS
    normal = {h: m for h, m in remaining.items() if h < lastcall_from}
    pool = normal or remaining
    best_h = min(pool, key=lambda h: (pool[h], h))
    best_m = pool[best_h]
    out["best"] = {"hour": best_h, "minutes": best_m, "lastcall": not normal}
    out["hours_covered"] = len(remaining)
    if price and best_m > 0:
        # DPAを買えば並ばずに済むので、浮くのは best_m まるごと。
        out["yen_per_minute"] = round(price / best_m)

    sold_out_hour = None
    if sold_out_at:
        try:
            sold_out_hour = int(sold_out_at.split(":")[0])
        except ValueError:
            sold_out_hour = None
    if sold_out_hour is not None:
        out["hours_left_to_buy"] = sold_out_hour - from_hour

    if sold_out_hour is not None and sold_out_hour <= from_hour:
        out["verdict"] = "sold_out"
        out["reason"] = f"売切目安 {sold_out_at} を過ぎている。並ぶなら{best_h}時台が最短で約{best_m}分"
        return out

    # 「これから先で一番空く時間帯」は、先の時間帯が複数埋まって初めて言える。
    # 1枠しか埋まっていない施設をそのまま比べると、まだ見えていない空き時間を
    # 無視して「最短でも◯分」と大きく出てしまい、順位の先頭に来る。
    #
    # ただし「カーブに穴がある」と「もう時間帯が残っていない」は別物。
    # 夜に近づけば選べる時間帯は自然に減るので、そこで黙ると使えなくなる。
    # 埋まっている数が、そもそも選べる数より少ないときだけ穴とみなす。
    # 売切の判定はカーブの厚みと関係なく決まるので、この前に返してある。
    selectable = max(0, lastcall_from - from_hour)
    if normal and len(normal) < MIN_HOURS_AHEAD <= selectable:
        return {**out, "verdict": "insufficient",
                "reason": f"{from_hour}時から先で埋まっている時間帯が{len(normal)}つしかない"}

    if best_m <= SKIP_MINUTES:
        out["verdict"] = "skip"
        out["reason"] = f"{best_h}時台なら約{best_m}分で並べる"
        return out

    if price and best_m >= BUY_MINUTES and out.get("yen_per_minute", 10 ** 9) <= YEN_PER_MINUTE:
        out["verdict"] = "worth"
        out["reason"] = (f"これから並ぶと最短でも{best_m}分（{best_h}時台）。"
                         f"1分あたり約{out['yen_per_minute']}円")
        return out

    out["verdict"] = "depends"
    out["reason"] = f"これから並ぶと最短{best_m}分（{best_h}時台）。短縮の価値は滞在計画次第"
    return out


def advise_by_hour(curve_band: dict | None, price: int | None, sold_out_at: str | None,
                   open_hour: int, close_hour: int) -> dict:
    """開園から閉園までの各時刻について advise() を回す。

    「今」はブラウザにしか無いので、判定表を先に作って渡し、画面は現在時刻の行を
    引くだけにする。判定のロジックをJS側に写さないため。
    """
    drop = ("price", "sold_out_at", "hours_covered")  # 施設ごとに1つでよい値は行に持たせない
    return {str(h): {k: v for k, v in advise(curve_band, price, sold_out_at, h, close_hour).items()
                     if k not in drop}
            for h in range(open_hour, close_hour + 1)}


def collect() -> str:
    wait_docs = [c.read_json(p) for p in sorted((c.DATA / "waits").glob("20*.json"))]
    wait_docs = [d for d in wait_docs if d]
    crowd = c.read_json(c.DATA / "crowd" / "calendar.json", {}) or {}
    curves = build_curves(wait_docs, crowd, c.attractions())
    c.write_json(c.DATA / "waits" / "curves.json", {
        "generated_at": c.iso(c.now_jst()),
        "min_days": MIN_DAYS,
        "skip_minutes": SKIP_MINUTES,
        "buy_minutes": BUY_MINUTES,
        "yen_per_minute": YEN_PER_MINUTE,
        "lastcall_hours": LASTCALL_HOURS,
        "days_used": len(wait_docs),
        "curves": curves,
    })
    filled = sum(len(h) for v in curves.values() for h in v.values())
    return f"{len(wait_docs)}日分から {len(curves)}施設 / 時間帯{filled}枠"


if __name__ == "__main__":
    c.main("waitcurve", collect)
