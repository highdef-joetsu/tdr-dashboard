from collectors import build_latest as B


def _official(closures_today=None, schedule=None):
    return {
        "parks": {"tds": {"closures_today": closures_today or {}}},
        "closures_schedule": {"tds": schedule or []},
    }


def test_target_date_picks_nearest_future_watch_date():
    from datetime import date
    assert B.target_date(date(2026, 9, 3), ["2026-09-17", "2026-10-01"]) == "2026-09-17"


def test_target_date_ignores_past_watch_dates():
    from datetime import date
    assert B.target_date(date(2026, 9, 18), ["2026-09-17"]) == "2026-09-19"


def test_target_date_falls_back_to_tomorrow():
    from datetime import date
    assert B.target_date(date(2026, 9, 3), []) == "2026-09-04"


def test_closures_includes_period_covering_the_day():
    o = _official(schedule=[{"category": "attraction", "name": "A",
                            "from": "2026-09-01", "to": "2026-09-30", "undecided": False}])
    out = B.closures_for(o, "tds", "2026-09-17")
    assert out["attraction"][0]["name"] == "A"
    assert out["attraction"][0]["source"] == "schedule"


def test_closures_excludes_period_ending_before_the_day():
    o = _official(schedule=[{"category": "attraction", "name": "A",
                            "from": "2026-07-01", "to": "2026-09-14", "undecided": False}])
    assert B.closures_for(o, "tds", "2026-09-17") == {}


def test_closures_excludes_period_starting_after_the_day():
    o = _official(schedule=[{"category": "attraction", "name": "A",
                            "from": "2026-09-28", "to": "2026-11-05", "undecided": False}])
    assert B.closures_for(o, "tds", "2026-09-17") == {}


def test_closures_keeps_undecided_end():
    o = _official(schedule=[{"category": "attraction", "name": "A",
                            "from": "2020-07-01", "to": None, "undecided": True}])
    out = B.closures_for(o, "tds", "2026-09-17")
    assert out["attraction"][0]["undecided"] is True


def test_closures_merges_daily_and_schedule_without_duplicating():
    o = _official(closures_today={"attraction": ["A"]},
                  schedule=[{"category": "attraction", "name": "A",
                             "from": "2025-08-18", "to": "2026-11-29", "undecided": False}])
    out = B.closures_for(o, "tds", "2026-09-17")
    assert len(out["attraction"]) == 1
    assert out["attraction"][0]["source"] == "both"
    assert out["attraction"][0]["to"] == "2026-11-29"


def test_closures_empty_when_official_missing():
    assert B.closures_for(None, "tds", "2026-09-17") == {}


def _sched(name, frm, undecided=True, to=None):
    return {"category": "attraction", "name": name, "from": frm, "to": to, "undecided": undecided}


def test_long_undecided_closure_is_marked_permanent():
    o = _official(schedule=[_sched("マーメイドラグーンシアター", "2020-07-01")])
    out = B.closures_for(o, "tds", "2026-09-17")
    assert out["attraction"][0]["permanent"] is True


def test_recent_undecided_closure_is_not_permanent():
    o = _official(schedule=[_sched("トゥーンポップ", "2026-07-01")])
    out = B.closures_for(o, "tds", "2026-09-17")
    assert out["attraction"][0]["permanent"] is False


def test_closure_with_end_date_is_never_permanent():
    o = _official(schedule=[_sched("旧い工事", "2019-01-01", undecided=False, to="2026-12-31")])
    out = B.closures_for(o, "tds", "2026-09-17")
    assert out["attraction"][0]["permanent"] is False


def test_permanent_flag_survives_merge_with_daily_list():
    o = _official(closures_today={"attraction": ["マーメイドラグーンシアター"]},
                  schedule=[_sched("マーメイドラグーンシアター", "2020-07-01")])
    out = B.closures_for(o, "tds", "2026-09-17")
    assert len(out["attraction"]) == 1
    assert out["attraction"][0]["permanent"] is True and out["attraction"][0]["source"] == "both"


def test_is_permanent_boundary():
    assert B.is_permanent({"undecided": True, "from": "2024-09-16"}, "2026-09-17", 2) is True
    assert B.is_permanent({"undecided": True, "from": "2024-09-18"}, "2026-09-17", 2) is False
