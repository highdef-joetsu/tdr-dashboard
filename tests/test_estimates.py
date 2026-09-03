from collectors.estimates import _bootstrap_entry
def test_plain_string():
    assert _bootstrap_entry("10:30", 0) == {"median":"10:30","samples":0,"source":"bootstrap"}
def test_dict_with_note():
    e=_bootstrap_entry({"median":"09:40","note":"出典X 2026-05"},1)
    assert e["median"]=="09:40" and e["note"]=="出典X 2026-05" and e["source"]=="bootstrap"
def test_none_stays_none():
    assert _bootstrap_entry(None,0)["median"] is None
