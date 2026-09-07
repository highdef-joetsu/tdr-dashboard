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


# ---------- 案内終了（Queue-Times が 0 を返し続ける区間）を落とす ----------
def _s(t, v):
    return {"at": f"2026-08-10T{t}:00+09:00", "waits": {"a": v}}


def test_queue_close_zeros_are_dropped():
    # 80分 → 0 に落ちて 0 が続く。これは「空いた」ではなく「締め切った」。
    kept = W.drop_after_queue_close([_s("19:55", 80), _s("20:00", 0), _s("20:30", 0)])
    assert [s["waits"].get("a") for s in kept] == [80, None, None]


def test_single_zero_is_not_treated_as_close():
    # 0 が1回だけならノイズとみなして残す（締め切りは戻らない）。
    kept = W.drop_after_queue_close([_s("19:55", 80), _s("20:00", 0), _s("20:30", 40)])
    assert [s["waits"].get("a") for s in kept] == [80, 0, 40]


def test_morning_zero_is_kept():
    # 直前に待ちが無い朝一の 0 は本物。
    kept = W.drop_after_queue_close([_s("09:00", 0), _s("09:05", 0), _s("10:00", 30)])
    assert [s["waits"].get("a") for s in kept] == [0, 0, 30]


def test_zero_after_a_short_wait_is_kept():
    # もともと5分しか待っていない施設が 0 になるのは、締め切りではなく本当に空。
    kept = W.drop_after_queue_close([_s("19:55", 5), _s("20:00", 0), _s("20:30", 0)])
    assert [s["waits"].get("a") for s in kept] == [5, 0, 0]


def test_close_is_per_attraction():
    # 施設ごとに締め切る時刻が違う（実データで 20:00 / 20:40 が同居する）。
    samples = [
        {"at": "2026-08-10T19:55:00+09:00", "waits": {"a": 80, "b": 50}},
        {"at": "2026-08-10T20:00:00+09:00", "waits": {"a": 0, "b": 50}},
        {"at": "2026-08-10T20:30:00+09:00", "waits": {"a": 0, "b": 40}},
        {"at": "2026-08-10T20:40:00+09:00", "waits": {"a": 0, "b": 0}},
        {"at": "2026-08-10T20:50:00+09:00", "waits": {"a": 0, "b": 0}},
    ]
    kept = W.drop_after_queue_close(samples)
    assert [s["waits"].get("a") for s in kept] == [80, None, None, None, None]
    assert [s["waits"].get("b") for s in kept] == [50, 50, 40, None, None]


def test_close_zeros_do_not_become_the_quietest_hour():
    # 集計まで通したとき、締め切りの 0 が「一番空く時間帯」にならないこと。
    crowd = {"parks": {"tds": {f"2026-08-{d:02d}": {"crowd_pct": 70} for d in range(10, 13)}}}
    docs = [{"date": f"2026-08-{d:02d}", "parks": {"tds": {"samples": [
        {"at": f"2026-08-{d:02d}T19:00:00+09:00", "waits": {"a": 90}},
        {"at": f"2026-08-{d:02d}T20:00:00+09:00", "waits": {"a": 0}},
        {"at": f"2026-08-{d:02d}T20:30:00+09:00", "waits": {"a": 0}},
    ]}}} for d in range(10, 13)]
    curves = W.build_curves(docs, crowd, ATTRS)
    assert "20" not in curves["a"]["61-80"], "案内終了の0が時間帯として残っている"
    assert curves["a"]["61-80"]["19"]["median"] == 90
