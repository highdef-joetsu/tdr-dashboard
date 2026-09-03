from collectors import ingest as I

QT = {13559: {"key": "frozen", "park": "tds"}, 8027: {"key": "indy", "park": "tds"}}
TP = {"E1": {"key": "frozen", "park": "tds"}}
HOURS = {"tds": {"open": "2026-09-04T09:00:00+09:00", "close": "2026-09-04T21:00:00+09:00"}, "tdl": None}


def wait(at, minutes, open_=True):
    return {"at": at, "kind": "wait",
            "data": {"park": "tds", "rides": [{"id": 13559, "is_open": open_, "wait_time": minutes}]}}


def dpa(at, state):
    return {"at": at, "kind": "dpa", "data": {"liveData": [
        {"id": "E1", "status": "OPERATING",
         "queue": {"PAID_RETURN_TIME": {"state": state, "price": {"amount": 2500}}}}]}}


def test_waits_rebuilt_from_samples():
    s = [wait("2026-09-04T09:00:00+09:00", 60), wait("2026-09-04T13:00:00+09:00", 150)]
    d = I.build_waits(s, "2026-09-04", QT)
    assert len(d["parks"]["tds"]["samples"]) == 2
    assert d["parks"]["tds"]["daily_max"]["frozen"]["minutes"] == 150


def test_rebuild_is_idempotent():
    """同じサンプル列から2回作れば完全に同じ。取り込みが何度動いても二重にならない。"""
    s = [wait("2026-09-04T09:00:00+09:00", 60), dpa("2026-09-04T09:00:05+09:00", "AVAILABLE")]
    assert I.build_waits(s, "2026-09-04", QT) == I.build_waits(s, "2026-09-04", QT)
    assert I.build_dpa(s, "2026-09-04", TP, HOURS) == I.build_dpa(s, "2026-09-04", TP, HOURS)


def test_adding_a_sample_extends_without_disturbing_earlier_ones():
    s1 = [wait("2026-09-04T09:00:00+09:00", 60)]
    s2 = s1 + [wait("2026-09-04T13:00:00+09:00", 150)]
    a, b = I.build_waits(s1, "2026-09-04", QT), I.build_waits(s2, "2026-09-04", QT)
    assert b["parks"]["tds"]["samples"][0] == a["parks"]["tds"]["samples"][0]
    assert len(b["parks"]["tds"]["samples"]) == 2


def test_dpa_sold_out_reconstructed_in_time_order():
    s = [dpa("2026-09-04T09:00:05+09:00", "AVAILABLE"), dpa("2026-09-04T13:00:05+09:00", "FINISHED")]
    d = I.build_dpa(s, "2026-09-04", TP, HOURS)
    rec = d["attractions"]["frozen"]
    assert rec["first_sold_out_at"] == "2026-09-04T13:00:05+09:00"
    assert [e["state"] for e in rec["events"]] == ["AVAILABLE", "FINISHED"]


def test_dpa_outside_operating_hours_is_not_counted_as_sold_out():
    s = [dpa("2026-09-04T07:00:00+09:00", "AVAILABLE"), dpa("2026-09-04T07:30:00+09:00", "FINISHED")]
    d = I.build_dpa(s, "2026-09-04", TP, HOURS)
    assert "first_sold_out_at" not in d["attractions"]["frozen"]


def test_closed_ride_goes_to_closed_not_waits():
    s = [wait("2026-09-04T09:00:00+09:00", 0, open_=False)]
    d = I.build_waits(s, "2026-09-04", QT)
    assert d["parks"]["tds"]["last"]["closed"] == ["frozen"]
    assert d["parks"]["tds"]["last"]["waits"] == {}


def test_empty_samples_produce_empty_doc():
    assert I.build_waits([], "2026-09-04", QT)["parks"] == {}
    assert I.build_dpa([], "2026-09-04", TP, HOURS)["attractions"] == {}
