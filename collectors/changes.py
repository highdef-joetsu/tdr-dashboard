"""来園日の情報が「前回からどう変わったか」を出す。

公開サイトは現在の状態しか出さない。前の状態を持っている側だけが差分を出せる。
ここは純関数のみ（ネットワークにもファイルにも触れない）。
"""
from __future__ import annotations

PARKS = ("tdl", "tds")
CAT_JA = {
    "attraction": "アトラクション", "show": "パレード/ショー",
    "greeting": "キャラクターグリーティング", "shop": "ショップ",
    "restaurant": "レストラン", "service": "サービス施設",
}


def _shows(entry: dict) -> dict[str, dict]:
    return {s["name"]: s for s in (entry or {}).get("shows") or []}


def _badges(s: dict) -> list[str]:
    out = []
    if s.get("dpa"):
        out.append("DPA対象")
    if s.get("entry"):
        out.append("エントリー受付")
    if s.get("reservation_only"):
        out.append("要事前予約")
    return out


def _closures(entry: dict) -> set[tuple[str, str]]:
    out = set()
    for cat, names in ((entry or {}).get("closures_today") or {}).items():
        for n in names:
            out.add((cat, n))
    return out


def diff_park(old: dict, new: dict, park: str) -> list[dict]:
    """1パーク分の変更を列挙する。old が None なら「初回取得」として空を返す。"""
    if not old:
        return []
    o = (old.get("parks") or {}).get(park) or {}
    n = (new.get("parks") or {}).get(park) or {}
    if n.get("note") == "fetch_failed" or o.get("note") == "fetch_failed":
        return []
    out: list[dict] = []

    # 掲載状態そのものの変化（未掲載 → 掲載）
    if o.get("note") == "not_published" and n.get("note") != "not_published":
        out.append({"park": park, "kind": "published", "label": "スケジュールが掲載された"})
        return out

    oh, nh = o.get("hours") or {}, n.get("hours") or {}
    if oh and nh and oh != nh:
        out.append({"park": park, "kind": "hours", "label": "開園時間",
                    "before": f"{oh.get('open')} - {oh.get('close')}",
                    "after": f"{nh.get('open')} - {nh.get('close')}"})

    ot, nt = o.get("ticket") or {}, n.get("ticket") or {}
    if ot.get("adult_1day") != nt.get("adult_1day") and nt.get("adult_1day"):
        out.append({"park": park, "kind": "ticket", "label": "1デーパスポート(大人)",
                    "before": ot.get("adult_1day"), "after": nt.get("adult_1day")})
    if ot.get("status") != nt.get("status") and nt.get("status"):
        out.append({"park": park, "kind": "ticket_status", "label": "チケット販売状況",
                    "before": ot.get("status"), "after": nt.get("status")})

    os_, ns = _shows(o), _shows(n)
    for name in sorted(set(ns) - set(os_)):
        out.append({"park": park, "kind": "show_added", "label": name,
                    "after": ns[name].get("times") or []})
    for name in sorted(set(os_) - set(ns)):
        out.append({"park": park, "kind": "show_removed", "label": name,
                    "before": os_[name].get("times") or []})
    for name in sorted(set(os_) & set(ns)):
        a, b = os_[name], ns[name]
        if (a.get("times") or []) != (b.get("times") or []):
            out.append({"park": park, "kind": "show_times", "label": name,
                        "before": a.get("times") or [], "after": b.get("times") or []})
        if _badges(a) != _badges(b):
            out.append({"park": park, "kind": "show_badges", "label": name,
                        "before": _badges(a), "after": _badges(b)})

    oc, nc = _closures(o), _closures(n)
    for cat, name in sorted(nc - oc):
        out.append({"park": park, "kind": "closure_added", "label": name,
                    "after": CAT_JA.get(cat, cat)})
    for cat, name in sorted(oc - nc):
        out.append({"park": park, "kind": "closure_removed", "label": name,
                    "after": CAT_JA.get(cat, cat)})
    return out


def _schedule_index(doc: dict, park: str) -> dict[tuple[str, str], dict]:
    return {(i["category"], i["name"]): i
            for i in ((doc or {}).get("closures_schedule") or {}).get(park) or []}


def diff_schedule(old: dict, new: dict, park: str, date: str) -> list[dict]:
    """期間つき休止のうち、指定日に掛かるものの増減・期間変更を出す。"""
    if not old:
        return []

    def covers(i):
        if i.get("from") and i["from"] > date:
            return False
        if i.get("to") and i["to"] < date:
            return False
        return bool(i.get("from") or i.get("undecided"))

    o = {k: v for k, v in _schedule_index(old, park).items() if covers(v)}
    n = {k: v for k, v in _schedule_index(new, park).items() if covers(v)}
    out = []
    for k in sorted(set(n) - set(o)):
        out.append({"park": park, "kind": "long_closure_added", "label": k[1],
                    "after": _period(n[k]), "category": CAT_JA.get(k[0], k[0])})
    for k in sorted(set(o) - set(n)):
        out.append({"park": park, "kind": "long_closure_removed", "label": k[1],
                    "before": _period(o[k]), "category": CAT_JA.get(k[0], k[0])})
    for k in sorted(set(o) & set(n)):
        if _period(o[k]) != _period(n[k]):
            out.append({"park": park, "kind": "long_closure_period", "label": k[1],
                        "before": _period(o[k]), "after": _period(n[k]),
                        "category": CAT_JA.get(k[0], k[0])})
    return out


def _period(i: dict) -> str:
    to = "終了未定" if i.get("undecided") else (i.get("to") or "?")
    return f"{i.get('from') or '?'} 〜 {to}"


def diff_day(old: dict | None, new: dict, date: str) -> list[dict]:
    """1日分の全変更。old が None（初回取得）なら空。"""
    out = []
    for park in PARKS:
        out += diff_park(old, new, park)
        out += diff_schedule(old, new, park, date)
    return out
