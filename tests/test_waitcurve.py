from collectors import waitcurve as W

ATTRS = [{"key": "a", "park": "tds", "dpa": True}]


def _days(n, base=100):
    crowd = {"parks": {"tds": {f"2026-08-{d:02d}": {"crowd_pct": 70} for d in range(10, 10 + n)}}}
    docs = [{"date": f"2026-08-{d:02d}", "parks": {"tds": {"samples": [
        {"at": f"2026-08-{d:02d}T12:00:00+09:00", "waits": {"a": base}},
        {"at": f"2026-08-{d:02d}T17:00:00+09:00", "waits": {"a": 30}},
    ]}}} for d in range(10, 10 + n)]
    return docs, crowd


def test_below_min_days_produces_nothing():
    docs, crowd = _days(W.MIN_DAYS - 1)
    assert W.build_curves(docs, crowd, ATTRS) == {}


def test_at_min_days_produces_curve():
    docs, crowd = _days(W.MIN_DAYS)
    c = W.build_curves(docs, crowd, ATTRS)
    assert c["a"]["61-80"]["12"]["median"] == 100
    assert c["a"]["61-80"]["12"]["days"] == W.MIN_DAYS


def test_days_without_crowd_data_are_skipped():
    docs, crowd = _days(W.MIN_DAYS)
    crowd["parks"]["tds"] = {}
    assert W.build_curves(docs, crowd, ATTRS) == {}


def test_repeated_samples_in_one_day_do_not_outweigh_other_days():
    docs, crowd = _days(W.MIN_DAYS)
    # 1日目だけ12時台に極端な値を大量に入れる
    docs[0]["parks"]["tds"]["samples"] += [
        {"at": "2026-08-10T12:30:00+09:00", "waits": {"a": 999}} for _ in range(20)]
    c = W.build_curves(docs, crowd, ATTRS)
    assert c["a"]["61-80"]["12"]["median"] == 100, "1日の中の連打が日をまたぐ中央値を動かしている"


def test_advise_needs_data():
    assert W.advise(None, 2500, None)["verdict"] == "insufficient"
    assert W.advise({"10": {"median": 90}}, 2500, None)["verdict"] == "insufficient"


def test_advise_skip_when_late_wait_is_short():
    cb = {"12": {"median": 120}, "17": {"median": 30}}
    r = W.advise(cb, 2500, None)
    assert r["verdict"] == "skip" and r["late"]["minutes"] == 30


def test_advise_buy_when_saving_is_large_and_cheap():
    cb = {"12": {"median": 180}, "17": {"median": 100}}
    r = W.advise(cb, 2000, None)
    assert r["verdict"] == "buy"
    assert r["saved_minutes"] == 80 and r["yen_per_minute"] == 25


def test_advise_depends_when_expensive_per_minute():
    cb = {"12": {"median": 120}, "17": {"median": 60}}
    r = W.advise(cb, 2500, None)
    assert r["verdict"] == "depends"
