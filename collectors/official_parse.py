"""公式サイトHTMLのパーサ（純関数のみ。ネットワークに触れない）。"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

CATEGORY = {
    "アトラクション": "attraction",
    "パレード/ショー": "show",
    "キャラクターグリーティング": "greeting",
    "ショップ": "shop",
    "レストラン": "restaurant",
    "サービス施設": "service",
}
TIME_RE = re.compile(r"\d{1,2}:\d{2}")
RANGE_RE = re.compile(r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}")
PRICE_RE = re.compile(r"[￥¥]\s*([\d,]+)")
DATE_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")


def _soup(html: str) -> BeautifulSoup:
    s = BeautifulSoup(html, "html.parser")
    for t in s(["script", "style", "noscript"]):
        t.decompose()
    return s


def _label_block(soup, label: str):
    """見出しテキストが label の h3 を探し、その値を含むブロックの文字列を返す。"""
    for h in soup.find_all(["h2", "h3", "h4"]):
        if h.get_text(strip=True) == label:
            blk = h.parent.parent
            txt = blk.get_text("\n", strip=True)
            return [x for x in txt.split("\n") if x and x != label]
    return []


def parse_hours(html: str) -> dict:
    lines = _label_block(_soup(html), "開園時間")
    for line in lines:
        m = RANGE_RE.search(line)
        if m:
            o, cl = re.split(r"\s*-\s*", m.group(0))
            return {"open": _pad(o), "close": _pad(cl)}
    return {"open": None, "close": None}


def _pad(t: str) -> str:
    h, m = t.strip().split(":")
    return f"{int(h):02d}:{m}"


def parse_ticket(html: str) -> dict:
    lines = _label_block(_soup(html), "チケット情報")
    status, price = None, None
    for line in lines:
        m = PRICE_RE.search(line)
        if m and price is None:
            price = int(m.group(1).replace(",", ""))
        elif status is None and not m and "※" not in line and "チケットを探す" not in line:
            status = line
    return {"status": status, "adult_1day": price}


def _tags(li) -> list[str]:
    return [s.get_text(strip=True) for s in li.select("div.tagArea span.iconTag")]


def _timetable(li) -> tuple[list[str], bool, str | None]:
    """(時刻リスト, 当日変更フラグ, 変更を疑った生マークアップ) を返す。

    「赤字は当日開催時間が変更になった情報です」の赤字を表すマークアップは
    2026-09-03 時点のフィクスチャに出現しなかった（変更が無い日だったため）。
    div.timetable 内に子要素か inline style が現れたら変更ありとみなし、
    生マークアップを残して後から実体を確認できるようにする。
    """
    tt = li.select_one("div.timetable")
    if not tt:
        return [], False, None
    changed_markup = None
    if tt.find(True) is not None or tt.get("style"):
        changed_markup = re.sub(r"\s+", " ", str(tt))[:400]
    # 改行・全角空白・NBSP が時刻の途中に入るので先に潰す
    text = re.sub(r"[\s\u00a0\u3000]+", " ", tt.get_text(" ", strip=True))
    ranges = [re.sub(r"\s*-\s*", " - ", r) for r in RANGE_RE.findall(text)]
    times = ranges if ranges else TIME_RE.findall(text)
    return times, changed_markup is not None, changed_markup


def _items(container) -> list[dict]:
    out = []
    for li in container.select("li"):
        name_el = li.select_one("p.heading3")
        if not name_el:
            continue
        times, changed, markup = _timetable(li)
        tags = _tags(li)
        a = li.select_one("a[href]")
        item = {
            "name": name_el.get_text(strip=True),
            "times": times,
            "dpa": any("プレミアアクセス" in t for t in tags),
            "entry": any("エントリー受付" in t for t in tags),
            "reservation_only": any(("予約が必須" in t) or ("事前予約" in t) for t in tags),
            "changed": changed,
            "url": a["href"] if a else None,
        }
        if markup:
            item["changed_markup"] = markup
        out.append(item)
    return out


def _ordered_nodes(soup):
    return soup.select("h2.heading2, h3.heading3, div.linkList, div.accordion")


def parse_schedule(html: str) -> dict:
    """当日のスケジュール（パレード/ショー・キャラクターグリーティング）。"""
    soup = _soup(html)
    shows, greetings = [], []
    section, sub = None, None
    for node in _ordered_nodes(soup):
        cls = node.get("class") or []
        if node.name in ("h2", "h3"):
            t = node.get_text(strip=True)
            if node.name == "h2":
                section, sub = t, None
            else:
                sub = t
            continue
        if section != "当日のスケジュール" or "linkList" not in cls:
            continue
        if sub == "パレード/ショー":
            shows += _items(node)
        elif sub == "キャラクターグリーティング":
            greetings += _items(node)
    return {"shows": shows, "greetings": greetings}


def parse_closures_today(html: str) -> dict:
    """休止情報（当日）をカテゴリ別に返す。"""
    soup = _soup(html)
    out = {v: [] for v in CATEGORY.values()}
    section = None
    for node in _ordered_nodes(soup):
        cls = node.get("class") or []
        if node.name == "h2":
            section = node.get_text(strip=True)
            continue
        if section != "休止情報" or "accordion" not in cls:
            continue
        for blk in node.select("div.accordionBlock"):
            ti = blk.select_one("div.accordionTitle")
            if not ti:
                continue
            cat = CATEGORY.get(ti.get_text(strip=True))
            if not cat:
                continue
            for li in blk.select("div.accordionDetail li p.heading3"):
                out[cat].append(li.get_text(strip=True))
    return out


def parse_stop_schedule(html: str) -> list[dict]:
    """stop.html から期間つき休止を返す。'未定' は to=None。"""
    soup = _soup(html)
    out = []
    for blk in soup.select("div.accordionBlock"):
        ti = blk.select_one("div.accordionTitle")
        if not ti:
            continue
        cat = CATEGORY.get(ti.get_text(strip=True))
        if not cat:
            continue
        for li in blk.select("li"):
            name_el = li.select_one("p.heading3")
            if not name_el:
                continue
            period = None
            for p in li.select("div.listTextArea p"):
                if p is name_el:
                    continue
                if "-" in p.get_text():
                    period = p.get_text(strip=True)
                    break
            frm, to, undecided = None, None, False
            if period:
                parts = re.split(r"\s*-\s*", period, maxsplit=1)
                frm = _date(parts[0]) if parts else None
                if len(parts) > 1:
                    if "未定" in parts[1]:
                        undecided = True
                    else:
                        to = _date(parts[1])
            a = li.select_one("a[href]")
            out.append({
                "category": cat,
                "name": name_el.get_text(strip=True),
                "from": frm,
                "to": to,
                "undecided": undecided,
                "raw_period": period,
                "url": a["href"] if a else None,
            })
    return out


def _date(s: str) -> str | None:
    m = DATE_RE.search(s or "")
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def is_published(html: str) -> bool:
    """翌月未掲載ページかどうか。スケジュールが1件も無ければ未掲載とみなす。"""
    s = parse_schedule(html)
    return bool(s["shows"] or s["greetings"])
