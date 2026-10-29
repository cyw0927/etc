"""Compare saved WTI snapshots; observed changes do not prove revision timestamps."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def _load(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("source") != "FinzData":
        raise ValueError("wrong provider")
    item = manifest["responses"]["continuous"]
    if item.get("params", {}).get("adjust") != "none":
        raise ValueError("adjusted prices not allowed")
    observed = datetime.fromisoformat(item["received_utc"].replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("missing timezone")
    raw = (folder / "continuous.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise ValueError("hash mismatch")
    payload = json.loads(raw)
    rows = payload["data"]
    if payload["count"] != len(rows):
        raise ValueError("invalid count")
    result = {}
    for row in rows:
        day = row["date"][:10]
        if day in result or row["root"] != "CL":
            raise ValueError("invalid or duplicate date")
        result[day] = {k: row.get(k) for k in ("contract", "close", "status")}
    return observed, result


def compare(before, after):
    first, a = _load(before)
    second, b = _load(after)
    if second <= first:
        raise ValueError("snapshots are not ordered")
    common = sorted(a.keys() & b.keys())
    changes = [{"date": day, "fields": [k for k in ("contract", "close", "status") if a[day][k] != b[day][k]]}
               for day in common if a[day] != b[day]]
    return {"before_received_utc": first.isoformat(), "after_received_utc": second.isoformat(),
            "common_days": len(common), "changed_days": changes,
            "limitation": "Changes occurred between observations; exact publication or revision time is unknown."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.before, args.after), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
