"""ThemeParks.wiki の live から DPA(ディズニー・プレミアアクセス)の販売状態を追う。

状態が変化したときだけ events に追記し、売切時刻を確定させる。
"""
from __future__ import annotations

from . import common as c

BASE = "https://api.themeparks.wiki/v1"

# 2026-09-03 の実測で観測できた値は AVAILABLE / FINISHED のみ。
# 他の値は「販売中ではない」に倒したうえで unknown_states に記録し、後で仕様を詰める。
ON_SALE = {"AVAILABLE"}
SOLD_OUT = {"FINISHED", "SOLD_OUT", "TEMP_FULL", "UNAVAILABLE"}


def classify(state: str | None) -> str:
    """'on_sale' / 'sold_out' / 'gone'(PAID_RETURN_TIME自体が消えた) を返す。"""
    if state is None:
        return "gone"
    if state in ON_SALE:
        return "on_sale"
    return "sold_out"


def snapshot(live: dict, mapping: dict[str, dict]) -> tuple[dict, list[str]]:
    """live レスポンスから {key: {...}} と未知stateの一覧を作る。"""
    out, unknown = {}, []
    for x in live.get("liveData") or []:
        a = mapping.get(x.get("id"))
        if not a:
            continue
        paid = (x.get("queue") or {}).get("PAID_RETURN_TIME")
        state = (paid or {}).get("state")
        if state and state not in ON_SALE and state not in SOLD_OUT:
            unknown.append(state)
        price = ((paid or {}).get("price") or {}).get("amount")
        out[a["key"]] = {
            "park": a["park"],
            "status": x.get("status"),
            "state": state,
            "price": price if price else None,
            "return_start": (paid or {}).get("returnStart"),
            "return_end": (paid or {}).get("returnEnd"),
        }
    return out, unknown


def apply_snapshot(doc: dict, snap: dict, at: str, within_hours: bool) -> dict:
    """状態変化のみを events に追記する（純関数）。"""
    doc = dict(doc)
    attractions = dict(doc.get("attractions") or {})

    for key, cur in snap.items():
        rec = dict(attractions.get(key) or {"park": cur["park"], "events": []})
        events = list(rec.get("events") or [])
        prev_state = events[-1]["state"] if events else None
        cur_state = cur["state"]

        # 施設が運営していないときの消失は「売切」と区別できないので判定に使わない。
        operating = cur["status"] == "OPERATING"
        if cur_state is None and not operating:
            attractions[key] = rec
            continue

        # 一度もDPAが出たことのない施設(ホーンテッドマンション等)で
        # state=None の空イベントを積まない。
        if cur_state is None and prev_state is None:
            attractions[key] = rec
            continue

        if cur_state != prev_state:
            ev = {"at": at, "state": cur_state}
            if cur.get("return_start"):
                ev["return_start"] = cur["return_start"]
            if cur.get("return_end"):
                ev["return_end"] = cur["return_end"]
            if classify(prev_state) == "sold_out" and classify(cur_state) == "on_sale":
                ev["note"] = "resale"
            events.append(ev)
            rec["events"] = events

            # 開園前・閉園後のサンプルは売切判定に使わない
            if within_hours and classify(prev_state) == "on_sale" and classify(cur_state) != "on_sale":
                rec.setdefault("first_sold_out_at", at)
                rec["final_sold_out_at"] = at

        if cur.get("price"):
            rec["price"] = cur["price"]
        rec["status_at_close"] = "sold_out" if classify(cur_state) != "on_sale" else "on_sale"
        attractions[key] = rec

    doc["attractions"] = attractions
    return doc


def park_hours(park_id: str) -> dict | None:
    """themeparks.wiki の schedule から当日の営業時間を取る。"""
    day = str(c.park_date())
    sched = c.get_json(f"{BASE}/entity/{park_id}/schedule")
    for s in sched.get("schedule") or []:
        if s.get("date") == day and s.get("type") == "OPERATING":
            return {"open": s.get("openingTime"), "close": s.get("closingTime")}
    return None


def within_operating(hours: dict | None, at) -> bool:
    if not hours or not hours.get("open") or not hours.get("close"):
        return False
    from datetime import datetime

    o = datetime.fromisoformat(hours["open"]).astimezone(c.JST)
    cl = datetime.fromisoformat(hours["close"]).astimezone(c.JST)
    return o <= at <= cl


def update_price_ledger(ledger: dict, snap: dict, at: str) -> tuple[dict, list[dict]]:
    """価格の最後に取れた値を持ち越す（純関数）。

    ThemeParks.wiki は同じ施設でも時々 amount:0 / "Unknown" を返す。
    「今回取れなかった」を「価格なし」と混同しないよう、取れた値を台帳に残す。
    ついでに価格改定を検知する。
    """
    ledger = {k: dict(v) for k, v in (ledger or {}).items()}
    events = []
    for key, cur in snap.items():
        price = cur.get("price")
        if not price:
            continue
        prev = ledger.get(key)
        if prev and prev.get("amount") != price:
            events.append({"at": at, "key": key,
                           "before": prev.get("amount"), "after": price})
        ledger[key] = {"amount": price, "at": at}
    return ledger, events


def collect() -> str:
    cfg = c.settings()["themeparks"]
    mapping = c.by_themeparks_id()
    day = c.park_date()
    now = c.now_jst()
    at = c.iso(now)
    path = c.DATA / "dpa" / f"{day}.json"
    doc = c.read_json(path) or {"date": str(day), "source": "themeparks.wiki", "attractions": {}}

    # 営業時間は1日1回だけ取得してキャッシュする
    if not doc.get("hours"):
        doc["hours"] = {p: park_hours(pid) for p, pid in cfg["parks"].items()}

    live = c.get_json(f"{BASE}/entity/{cfg['destination_id']}/live")
    snap, unknown = snapshot(live, mapping)
    if unknown:
        doc["unknown_states"] = sorted(set(doc.get("unknown_states", [])) | set(unknown))
        c.log(f"  未知のstate: {sorted(set(unknown))}")

    # パークごとに営業時間内かを判定して渡す
    open_parks = {p: within_operating((doc.get("hours") or {}).get(p), now) for p in cfg["parks"]}
    for park in cfg["parks"]:
        sub = {k: v for k, v in snap.items() if v["park"] == park}
        doc = apply_snapshot(doc, sub, at, open_parks[park])

    # 価格は断続的に欠ける。台帳に持ち越して、今日の記録にも埋め戻す。
    lpath = c.DATA / "dpa" / "prices.json"
    ledger_doc = c.read_json(lpath) or {"prices": {}, "changes": []}
    ledger, price_events = update_price_ledger(ledger_doc.get("prices"), snap, at)
    if price_events:
        ledger_doc["changes"] = (ledger_doc.get("changes") or []) + price_events
        ledger_doc["changes"] = ledger_doc["changes"][-100:]
        c.log(f"  価格改定を検知: {price_events}")
    ledger_doc["prices"] = ledger
    ledger_doc["updated_at"] = at
    c.write_json(lpath, ledger_doc)

    for key, rec in doc["attractions"].items():
        if not rec.get("price") and ledger.get(key):
            rec["price"] = ledger[key]["amount"]
            rec["price_source"] = "ledger"

    doc["last_polled_at"] = at
    c.write_json(path, doc)
    on_sale = sum(1 for v in snap.values() if classify(v["state"]) == "on_sale")
    return f"{day} 監視{len(snap)}件 販売中{on_sale}件"


if __name__ == "__main__":
    c.main("dpa", collect)
