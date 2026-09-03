from collectors import dpa as D


def _snap(state, status="OPERATING", price=2500):
    return {"x": {"park": "tds", "status": status, "state": state,
                  "price": price, "return_start": None, "return_end": None}}


def test_no_event_when_state_unchanged():
    d = D.apply_snapshot({"attractions": {}}, _snap("AVAILABLE"), "T1", True)
    d = D.apply_snapshot(d, _snap("AVAILABLE"), "T2", True)
    assert len(d["attractions"]["x"]["events"]) == 1


def test_sold_out_recorded_only_within_operating_hours():
    d = D.apply_snapshot({"attractions": {}}, _snap("AVAILABLE"), "T1", True)
    d = D.apply_snapshot(d, _snap("FINISHED"), "T2", False)  # 開園前/閉園後
    assert "first_sold_out_at" not in d["attractions"]["x"]


def test_first_sold_out_is_not_overwritten_but_final_is():
    d = D.apply_snapshot({"attractions": {}}, _snap("AVAILABLE"), "T1", True)
    d = D.apply_snapshot(d, _snap("FINISHED"), "T2", True)
    d = D.apply_snapshot(d, _snap("AVAILABLE"), "T3", True)
    d = D.apply_snapshot(d, _snap("FINISHED"), "T4", True)
    rec = d["attractions"]["x"]
    assert rec["first_sold_out_at"] == "T2"
    assert rec["final_sold_out_at"] == "T4"
    assert rec["events"][2]["note"] == "resale"


def test_never_dpa_attraction_records_no_empty_event():
    d = D.apply_snapshot({"attractions": {}}, _snap(None, price=None), "T1", True)
    assert d["attractions"]["x"]["events"] == []


def test_disappearing_while_closed_is_not_sold_out():
    d = D.apply_snapshot({"attractions": {}}, _snap("AVAILABLE"), "T1", True)
    d = D.apply_snapshot(d, _snap(None, status="CLOSED"), "T2", True)
    assert "first_sold_out_at" not in d["attractions"]["x"]
    assert len(d["attractions"]["x"]["events"]) == 1


def test_unknown_state_is_treated_as_not_on_sale():
    assert D.classify("SOMETHING_NEW") == "sold_out"
    assert D.classify("AVAILABLE") == "on_sale"
    assert D.classify(None) == "gone"
