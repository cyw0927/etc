"""Point-in-time research input from immutable FinzData snapshots.

Not registered in the legacy prediction pipeline; no forecast or ledger writes.
"""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have timezone")
    return parsed.astimezone(timezone.utc)


def features_at(snapshot_dirs, decision_time):
    """Return same-contract daily return based only on final rows observed by decision."""
    decision = _time(decision_time)
    available = []
    for folder in map(Path, snapshot_dirs):
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("source") != "FinzData" or manifest.get("model_use") is not False:
            raise ValueError("unexpected snapshot provenance")
        item = manifest["responses"]["continuous"]
        received = _time(item["received_utc"])
        if received > decision:
            continue
        raw = (folder / "continuous.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("snapshot hash mismatch")
        if item.get("params", {}).get("adjust") != "none":
            raise ValueError("unadjusted series required")
        data = json.loads(raw)
        if not isinstance(data.get("data"), list) or data.get("count") != len(data["data"]):
            raise ValueError("invalid data")
        other = manifest["responses"]["individual"]
        if _time(other["received_utc"]) > decision:
            continue
        other_raw = (folder / "individual.json").read_bytes()
        if hashlib.sha256(other_raw).hexdigest() != other["sha256"]:
            raise ValueError("individual snapshot hash mismatch")
        individual = json.loads(other_raw)
        if not isinstance(individual.get("data"), list) or individual.get("count") != len(individual["data"]):
            raise ValueError("invalid individual data")
        indexed = {}
        for row in individual["data"]:
            key = (str(row.get("date"))[:10], row.get("contract"))
            if key in indexed:
                raise ValueError("duplicate individual contract date")
            indexed[key] = row
        seen_dates = set()
        for row in data["data"]:
            day = str(row.get("date"))[:10]
            if day in seen_dates:
                raise ValueError("duplicate continuous date")
            seen_dates.add(day)
            match = indexed.get((str(row.get("date"))[:10], row.get("contract")))
            if row.get("root") != "CL" or not match or match.get("root") != "CL" or match.get("close") != row.get("close") or match.get("status") != row.get("status"):
                raise ValueError("continuous and individual contracts disagree")
        received = max(received, _time(other["received_utc"]))
        available.append((received, folder, data["data"], item["sha256"]))
    if not available:
        raise ValueError("no snapshot observed by decision time")
    available.sort(key=lambda item: (item[0], str(item[1])))
    received, folder, rows, digest = available[-1]
    rows = sorted(rows, key=lambda r: r["date"])
    if len(rows) < 2:
        raise ValueError("insufficient final observations")
    a, b = rows[-2:]
    if any(r.get("status") != "final" for r in (a, b)):
        raise ValueError("latest observations are not final")
    if a["contract"] != b["contract"]:
        raise ValueError("contract change: do not treat roll gap as return")
    if str(a["date"])[:10] == str(b["date"])[:10]:
        raise ValueError("duplicate dates")
    previous, latest = (date.fromisoformat(str(r["date"])[:10]) for r in (a, b))
    if previous >= latest:
        raise ValueError("dates not increasing")
    # A weekday gap could mean a missing session. Reject holidays as well;
    # without an independently verified exchange calendar we fail closed.
    day = previous + timedelta(days=1)
    while day < latest:
        if day.weekday() < 5:
            raise ValueError("possible missing session")
        day += timedelta(days=1)
    if previous.weekday() >= 5 or latest.weekday() >= 5:
        raise ValueError("unexpected weekend session")
    if decision - received > timedelta(days=3) or (decision.date() - latest).days > 5:
        raise ValueError("snapshot is stale")
    # Reject invalid and nonpositive denominator: ratio return is not meaningful.
    old, new = a["close"], b["close"]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (old, new)):
        raise ValueError("invalid denominator")
    if str(b["date"])[:10] > received.date().isoformat():
        raise ValueError("future observation")
    return {"wti_same_contract_return": new / old - 1, "contract": b["contract"],
            "observation_date": str(b["date"])[:10], "available_at_utc": received.isoformat(),
            "source_snapshot": str(folder), "source_sha256": digest, "research_only": True}
