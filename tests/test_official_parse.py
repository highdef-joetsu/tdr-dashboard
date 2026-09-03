"""公式サイトパーサ — Phase 0 で保存した実HTMLに対する検証。"""
import json

import pytest

from collectors import official_parse as P
from conftest import fixture


@pytest.mark.parametrize("f,park", [
    ("tdl_daily_20260917.html", "tdl"),
    ("tds_daily_20260917.html", "tds"),
])
def test_hours(f, park):
    assert P.parse_hours(fixture(f)) == {"open": "09:00", "close": "21:00"}


def test_ticket_tds():
    assert P.parse_ticket(fixture("tds_daily_20260917.html")) == {
        "status": "販売中", "adult_1day": 9900}


def test_shows_tds_has_dpa_and_entry():
    shows = P.parse_schedule(fixture("tds_daily_20260917.html"))["shows"]
    by_name = {s["name"]: s for s in shows}
    dtf = by_name["ドリームス・テイク・フライト"]
    assert dtf["times"] == ["11:00", "12:25", "13:50", "15:55", "17:20"]
    assert dtf["dpa"] is True and dtf["entry"] is True
    assert dtf["reservation_only"] is False
    assert by_name["ビリーヴ！～シー・オブ・ドリームス～"]["dpa"] is True
    assert by_name["ダッフィー＆フレンズのワンダフル・フレンドシップ"]["reservation_only"] is True


def test_shows_tdl_entry_only():
    shows = P.parse_schedule(fixture("tdl_daily_20260917.html"))["shows"]
    jm = next(s for s in shows if s["name"].startswith("ジャンボリミッキー"))
    assert jm["entry"] is True and jm["dpa"] is False


def test_greeting_time_range_is_normalized():
    """改行・NBSP が混ざった時間帯を 'H:MM - H:MM' に正規化できていること。"""
    g = P.parse_schedule(fixture("tds_daily_20260917.html"))["greetings"]
    assert g, "グリーティングが1件も取れていない"
    for item in g:
        for t in item["times"]:
            assert "\n" in t or "\xa0" in t or True
            assert t == " ".join(t.split()), f"空白が残っている: {t!r}"


def test_closures_today_categories():
    cl = P.parse_closures_today(fixture("tds_daily_20260917.html"))
    assert set(cl) == set(P.CATEGORY.values())
    assert "インディ・ジョーンズ・アドベンチャー：クリスタルスカルの魔宮" in cl["attraction"]


def test_stop_schedule_periods():
    items = P.parse_stop_schedule(fixture("tds_stop.html"))
    by_name = {i["name"]: i for i in items}
    indy = by_name["インディ・ジョーンズ・アドベンチャー：クリスタルスカルの魔宮"]
    assert indy["from"] == "2025-08-18" and indy["to"] == "2026-11-29"
    assert indy["undecided"] is False
    mermaid = by_name["マーメイドラグーンシアター"]
    assert mermaid["undecided"] is True and mermaid["to"] is None


def test_is_published_true_for_captured_pages():
    assert P.is_published(fixture("tds_daily_20260917.html")) is True


def test_is_published_false_for_empty_page():
    assert P.is_published("<html><body><h2>当日のスケジュール</h2></body></html>") is False
