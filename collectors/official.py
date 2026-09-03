"""東京ディズニーリゾート公式サイトから 日次スケジュール・休止情報を取る。

公式サイトは Akamai の bot 対策下にあり、curl / requests / headless Chromium は
いずれも無応答でドロップされる（Phase 0 実測）。headed Chromium だけが通るため
Playwright を headed で使い、CI では xvfb 配下で動かす。

取得間隔を詰めると 403 が返る（実測: 1.2秒間隔で2件目以降が全て403、
コンテキストを都度作り直して20秒空けると全て200）。ページごとに新しい
ブラウザコンテキストを作り、settings.json の official_fetch_gap_seconds だけ空ける。
"""
from __future__ import annotations

import time
from datetime import timedelta

from . import changes as CH
from . import common as c
from . import official_parse as P

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
BASE = "https://www.tokyodisneyresort.jp"
PARKS = ("tdl", "tds")


def target_dates() -> list[str]:
    """今日・明日 + settings.json の watch_dates（過去日は落とす）。"""
    today = c.park_date()
    days = {str(today), str(today + timedelta(days=1))}
    days |= {d for d in c.settings().get("watch_dates", []) if d >= str(today)}
    return sorted(days)


class Fetcher:
    """headed Chromium で1ページずつ取る。ページごとに新しいコンテキストを使う。"""

    def __init__(self, gap: int):
        self.gap = gap
        self._first = True

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        return self

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()

    def get(self, url: str) -> str:
        if not self._first:
            time.sleep(self.gap)
        self._first = False
        ctx = self._browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", user_agent=UA)
        try:
            page = ctx.new_page()
            r = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if r is None or r.status != 200:
                raise RuntimeError(f"{url}: HTTP {r.status if r else 'なし'}")
            page.wait_for_timeout(1500)
            return page.content()
        finally:
            ctx.close()


def build_day_doc(pages: dict, stops: dict, day: str, fetched_at: str) -> dict:
    """取得済みHTMLから1日分のドキュメントを組み立てる（純関数）。"""
    doc = {"date": day, "fetched_at": fetched_at, "source": "tokyodisneyresort.jp", "parks": {}}
    for park in PARKS:
        html = pages.get((park, day))
        if html is None:
            doc["parks"][park] = {"note": "fetch_failed"}
            continue
        sched = P.parse_schedule(html)
        entry = {
            "hours": P.parse_hours(html),
            "ticket": P.parse_ticket(html),
            "shows": sched["shows"],
            "greetings": sched["greetings"],
            "closures_today": P.parse_closures_today(html),
        }
        if not sched["shows"] and not sched["greetings"]:
            # 翌月分は前月8日ごろ掲載。空＝未掲載であって取得失敗ではない。
            entry["note"] = "not_published"
        doc["parks"][park] = entry
    doc["closures_schedule"] = {
        park: (P.parse_stop_schedule(stops[park]) if stops.get(park) else None)
        for park in PARKS
    }
    return doc


def collect() -> str:
    gap = c.settings().get("official_fetch_gap_seconds", 20)
    days = target_dates()
    fetched_at = c.iso(c.now_jst())
    pages, stops, errors = {}, {}, []

    with Fetcher(gap) as f:
        for park in PARKS:
            for day in days:
                ymd = day.replace("-", "")
                try:
                    pages[(park, day)] = f.get(f"{BASE}/{park}/daily/calendar/{ymd}/")
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{park}/{day}: {type(e).__name__}")
            try:
                stops[park] = f.get(f"{BASE}/{park}/monthly/stop.html")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{park}/stop: {type(e).__name__}")

    written, changed = 0, 0
    for day in days:
        if not any((park, day) in pages for park in PARKS):
            continue  # 両パークとも取れていない日は既存ファイルを壊さない
        path = c.DATA / "official" / f"{day}.json"
        old_doc = c.read_json(path)
        new_doc = build_day_doc(pages, stops, day, fetched_at)

        # 前回との差分を台帳に積む。公開サイトは「今」しか出さないので、
        # 「前回から何が変わったか」は蓄積している側だけが出せる。
        diffs = CH.diff_day(old_doc, new_doc, day)
        if diffs:
            led = c.DATA / "changes" / f"{day}.json"
            ledger = c.read_json(led) or {"date": day, "entries": []}
            for d in diffs:
                ledger["entries"].append({"at": fetched_at, **d})
            ledger["entries"] = ledger["entries"][-200:]
            c.write_json(led, ledger)
            changed += len(diffs)

        c.write_json(path, new_doc)
        written += 1

    if errors:
        raise RuntimeError(f"{written}日分を書き出したが失敗あり: {'; '.join(errors)}")
    return f"{written}日分 変更{changed}件 ({', '.join(days)})"


if __name__ == "__main__":
    c.main("official", collect)
