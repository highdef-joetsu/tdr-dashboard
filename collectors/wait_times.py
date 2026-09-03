"""Queue-Times の待ち時間を1サンプル追記し、当日最大を更新する。"""
from __future__ import annotations

from . import common as c


def parse_rides(payload: dict) -> list[dict]:
    """lands[].rides[] と トップレベル rides[] の両方に対応する。

    2026-09-03 実測では TDL/TDS とも lands は空でトップレベル rides のみだった。
    """
    rides = [r for land in payload.get("lands") or [] for r in land.get("rides") or []]
    rides += payload.get("rides") or []
    return rides


def sample_park(payload: dict, mapping: dict[int, dict], park: str) -> dict:
    waits, closed, unmapped = {}, [], []
    for r in parse_rides(payload):
        a = mapping.get(r.get("id"))
        if not a or a.get("park") != park:
            if not a:
                unmapped.append(r.get("name"))
            continue
        if r.get("is_open"):
            waits[a["key"]] = r.get("wait_time")
        else:
            closed.append(a["key"])
    return {"waits": waits, "closed": sorted(closed), "unmapped": sorted(unmapped)}


def merge_sample(park_obj: dict, sample: dict, at: str) -> dict:
    """サンプルを追記し daily_max / last を更新する（純関数）。"""
    park_obj = dict(park_obj)
    samples = list(park_obj.get("samples") or [])
    samples.append({"at": at, "waits": sample["waits"], "closed": sample["closed"]})
    park_obj["samples"] = samples

    daily_max = dict(park_obj.get("daily_max") or {})
    for key, minutes in sample["waits"].items():
        if minutes is None:
            continue
        cur = daily_max.get(key)
        if cur is None or minutes > cur["minutes"]:
            daily_max[key] = {"minutes": minutes, "at": at}
    park_obj["daily_max"] = daily_max
    park_obj["last"] = {"at": at, "waits": sample["waits"], "closed": sample["closed"]}
    park_obj["unmapped"] = sample["unmapped"]
    return park_obj


def collect() -> str:
    mapping = c.by_queue_times_id()
    day = c.park_date()
    at = c.iso(c.now_jst())
    path = c.DATA / "waits" / f"{day}.json"
    doc = c.read_json(path) or {"date": str(day), "source": "queue-times.com", "parks": {}}

    counts = []
    for park, pid in c.settings()["queue_times"].items():
        payload = c.get_json(f"https://queue-times.com/parks/{pid}/queue_times.json")
        sample = sample_park(payload, mapping, park)
        doc["parks"][park] = merge_sample(doc["parks"].get(park, {}), sample, at)
        counts.append(f"{park}={len(sample['waits'])}件")

    c.write_json(path, doc)
    return f"{day} {' '.join(counts)}"


if __name__ == "__main__":
    c.main("wait_times", collect)
