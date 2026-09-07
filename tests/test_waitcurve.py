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


# ---------- advise（基準時刻から先だけで判定する）----------
OPEN, CLOSE = 9, 21


def test_advise_needs_data():
    assert W.advise(None, 2500, None, 9, CLOSE)["verdict"] == "insufficient"


def test_advise_ignores_hours_already_past():
    # 10時の90分は、16時に立っている人には使えない。
    cb = {"10": {"median": 90}, "17": {"median": 100}, "18": {"median": 110}}
    assert W.advise(cb, 2500, None, 16, CLOSE)["best"] == {
        "hour": 17, "minutes": 100, "lastcall": False}
    assert W.advise(cb, 2500, None, 22, CLOSE)["verdict"] == "insufficient"


def test_advise_skip_when_a_short_wait_is_still_ahead():
    cb = {"12": {"median": 120}, "17": {"median": 30}}
    r = W.advise(cb, 2500, None, 9, CLOSE)
    assert r["verdict"] == "skip" and r["best"]["minutes"] == 30


def test_advise_worth_when_cheap_per_minute():
    # DPAを買えば並ばずに済むので、浮くのは「これから先の最短待ち」まるごと。
    cb = {"12": {"median": 180}, "17": {"median": 100}}
    r = W.advise(cb, 2000, None, 9, CLOSE)
    assert r["verdict"] == "worth" and r["yen_per_minute"] == 20


def test_advise_depends_when_expensive_per_minute():
    cb = {"12": {"median": 120}, "17": {"median": 60}}
    r = W.advise(cb, 2500, None, 9, CLOSE)
    assert r["verdict"] == "depends"


def test_advise_marks_lastcall_when_only_the_closing_hour_is_left():
    # 閉園前1時間しか残っていないなら、その根拠は他の施設と取り合いになる。
    cb = {"12": {"median": 120}, "20": {"median": 20}}
    r = W.advise(cb, 2500, None, 19, CLOSE)
    assert r["verdict"] == "skip" and r["best"]["lastcall"] is True
    # 20時より前が残っていれば取り合いではない
    cb2 = {"17": {"median": 40}, "18": {"median": 30}, "20": {"median": 20}}
    assert W.advise(cb2, 2500, None, 17, CLOSE)["best"] == {
        "hour": 18, "minutes": 30, "lastcall": False}


def test_advise_sold_out_when_the_estimate_has_passed():
    cb = {"18": {"median": 120}, "19": {"median": 110}}
    r = W.advise(cb, 2000, "17:40", 18, CLOSE)
    assert r["verdict"] == "sold_out"
    r2 = W.advise(cb, 2000, "17:40", 16, CLOSE)
    assert r2["verdict"] == "worth" and r2["hours_left_to_buy"] == 1


def test_advise_by_hour_covers_open_to_close_and_drops_repeated_fields():
    table = W.advise_by_hour({"12": {"median": 120}, "15": {"median": 100}},
                             2000, "17:40", OPEN, CLOSE)
    assert sorted(int(h) for h in table) == list(range(OPEN, CLOSE + 1))
    assert "price" not in table["9"] and "sold_out_at" not in table["9"]
    assert table["9"]["verdict"] == "worth"
    assert table["16"]["verdict"] == "insufficient", "過ぎた時間帯だけなら判定は出さない"


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


def test_advise_needs_more_than_one_hour_ahead():
    # 先の時間帯が1つしか埋まっていない施設は、まだ見えていない空き時間を
    # 無視して「最短でも◯分」と大きく出るため、順位に混ぜない。
    cb = {"9": {"median": 140}}
    assert W.advise(cb, 2500, None, 9, CLOSE)["verdict"] == "insufficient"
    cb2 = {"9": {"median": 140}, "12": {"median": 100}}
    assert W.advise(cb2, 2500, None, 9, CLOSE)["verdict"] == "worth"


def test_late_hour_with_few_slots_left_still_gets_a_verdict():
    # 19時で閉園21時なら、閉園前枠を除くと選べるのは19時だけ。
    # データの穴ではなく本当に選択肢が1つなので、黙らずに判定する。
    cb = {"10": {"median": 140}, "19": {"median": 90}, "20": {"median": 20}}
    r = W.advise(cb, 1500, None, 19, CLOSE)
    assert r["verdict"] == "worth" and r["best"] == {"hour": 19, "minutes": 90, "lastcall": False}


def test_lastcall_slot_still_gets_a_verdict():
    # 閉園前の枠しか残っていないなら、選べる時間帯が本当に1つなので判定する。
    cb = {"9": {"median": 140}, "20": {"median": 10}}
    r = W.advise(cb, 2500, None, 20, CLOSE)
    assert r["verdict"] == "skip" and r["best"]["lastcall"] is True
