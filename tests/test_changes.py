from collectors import changes as CH


def _doc(shows=None, closures=None, hours=None, ticket=None, schedule=None):
    return {
        "parks": {
            "tds": {
                "hours": hours or {"open": "09:00", "close": "21:00"},
                "ticket": ticket or {"adult_1day": 9900, "status": "販売中"},
                "shows": shows or [],
                "closures_today": closures or {},
            },
            "tdl": {},
        },
        "closures_schedule": {"tds": schedule or [], "tdl": []},
    }


def _show(name, times, dpa=False, entry=False, res=False):
    return {"name": name, "times": times, "dpa": dpa, "entry": entry, "reservation_only": res}


def test_first_fetch_reports_nothing():
    assert CH.diff_day(None, _doc(), "2026-09-17") == []


def test_no_change_reports_nothing():
    d = _doc(shows=[_show("A", ["10:00"])], closures={"attraction": ["X"]})
    assert CH.diff_day(d, d, "2026-09-17") == []


def test_show_time_change():
    old = _doc(shows=[_show("A", ["19:50"])])
    new = _doc(shows=[_show("A", ["19:30", "21:00"])])
    out = CH.diff_day(old, new, "2026-09-17")
    assert [c["kind"] for c in out] == ["show_times"]
    assert out[0]["before"] == ["19:50"] and out[0]["after"] == ["19:30", "21:00"]


def test_show_badge_change_is_detected():
    old = _doc(shows=[_show("A", ["10:00"])])
    new = _doc(shows=[_show("A", ["10:00"], dpa=True)])
    out = CH.diff_day(old, new, "2026-09-17")
    assert out[0]["kind"] == "show_badges" and out[0]["after"] == ["DPA対象"]


def test_ticket_price_change():
    out = CH.diff_day(_doc(), _doc(ticket={"adult_1day": 10900, "status": "販売中"}), "2026-09-17")
    assert out[0]["kind"] == "ticket" and out[0]["after"] == 10900


def test_closure_added_and_removed():
    old = _doc(closures={"attraction": ["A"]})
    new = _doc(closures={"attraction": ["B"]})
    kinds = sorted(c["kind"] for c in CH.diff_day(old, new, "2026-09-17"))
    assert kinds == ["closure_added", "closure_removed"]


def test_long_closure_period_change_only_when_it_covers_the_day():
    base = {"category": "attraction", "name": "T", "from": "2026-09-01", "to": "2026-09-30"}
    old = _doc(schedule=[base])
    new = _doc(schedule=[{**base, "to": "2026-10-31"}])
    out = CH.diff_day(old, new, "2026-09-17")
    assert out[0]["kind"] == "long_closure_period"

    # 対象日に掛からない期間の変更は出さない
    far = {"category": "attraction", "name": "T", "from": "2026-11-01", "to": "2026-11-30"}
    out2 = CH.diff_day(_doc(schedule=[far]), _doc(schedule=[{**far, "to": "2026-12-31"}]), "2026-09-17")
    assert out2 == []


def test_publication_change_short_circuits():
    old = {"parks": {"tds": {"note": "not_published", "shows": []}, "tdl": {}}}
    new = _doc(shows=[_show("A", ["10:00"])])
    out = CH.diff_day(old, new, "2026-09-17")
    assert [c["kind"] for c in out] == ["published"]


def test_fetch_failure_is_not_reported_as_change():
    old = _doc(shows=[_show("A", ["10:00"])])
    new = {"parks": {"tds": {"note": "fetch_failed"}, "tdl": {}}, "closures_schedule": {"tds": [], "tdl": []}}
    assert CH.diff_day(old, new, "2026-09-17") == []
