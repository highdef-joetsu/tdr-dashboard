import json

from collectors import wait_times as W
from conftest import fixture


MAPPING = {
    13559: {"key": "frozen_journey", "park": "tds"},
    8024: {"key": "soaring", "park": "tds"},
    8027: {"key": "indiana_jones", "park": "tds"},
}


def test_parse_rides_handles_toplevel_rides():
    payload = json.loads(fixture("qt_275.json"))
    rides = W.parse_rides(payload)
    assert len(rides) == 34
    assert any(r["name"] == "Anna and Elsa's Frozen Journey" for r in rides)


def test_parse_rides_handles_lands_nesting():
    payload = {"lands": [{"rides": [{"id": 1, "name": "A"}]}], "rides": [{"id": 2, "name": "B"}]}
    assert [r["id"] for r in W.parse_rides(payload)] == [1, 2]


def test_sample_park_splits_open_and_closed():
    payload = json.loads(fixture("qt_275.json"))
    s = W.sample_park(payload, MAPPING, "tds")
    assert "frozen_journey" in s["waits"]
    assert "indiana_jones" in s["closed"]
    assert "indiana_jones" not in s["waits"]
    assert s["unmapped"], "未対応施設の記録が空になっている"


def test_merge_sample_updates_daily_max_only_when_larger():
    obj = {}
    obj = W.merge_sample(obj, {"waits": {"a": 100}, "closed": [], "unmapped": []}, "T1")
    obj = W.merge_sample(obj, {"waits": {"a": 60}, "closed": [], "unmapped": []}, "T2")
    assert obj["daily_max"]["a"] == {"minutes": 100, "at": "T1"}
    assert obj["last"] == {"at": "T2", "waits": {"a": 60}, "closed": []}
    obj = W.merge_sample(obj, {"waits": {"a": 150}, "closed": [], "unmapped": []}, "T3")
    assert obj["daily_max"]["a"] == {"minutes": 150, "at": "T3"}
    assert len(obj["samples"]) == 3


def test_merge_sample_ignores_none_wait():
    obj = W.merge_sample({}, {"waits": {"a": None}, "closed": [], "unmapped": []}, "T1")
    assert obj["daily_max"] == {}
