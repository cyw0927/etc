"""FinzData WTI research snapshot. Never writes forecasts or production datasets."""
import hashlib
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE = "https://api.finzdata.com"
ROOT = Path(__file__).resolve().parents[1] / "data" / "operations" / "source_research"


def validate(payload, kind):
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("invalid response envelope")
    rows = payload["data"]
    if payload.get("count") != len(rows) or not rows:
        raise ValueError("empty or incomplete response")
    if kind == "contracts":
        if any(not r.get("contract") for r in rows):
            raise ValueError("contract identifier missing")
        return {"rows": len(rows)}
    seen = set()
    for row in rows:
        contract, day = row.get("contract"), row.get("date")
        if row.get("root") != "CL" or not contract or not day:
            raise ValueError("missing contract or date")
        datetime.fromisoformat(str(day).replace("Z", "+00:00"))
        key = (str(day), contract)
        if key in seen:
            raise ValueError("duplicate contract and date")
        seen.add(key)
        value = row.get("close")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("invalid close")
    days = sorted(str(row["date"])[:10] for row in rows)
    switches = []
    if kind == "continuous":
        ordered = sorted(rows, key=lambda r: r["date"])
        if len({r["date"] for r in rows}) != len(rows):
            raise ValueError("duplicate continuous date")
        for before, after in zip(ordered, ordered[1:]):
            if before["contract"] != after["contract"]:
                switches.append({"date": str(after["date"])[:10], "from": before["contract"], "to": after["contract"]})
    return {"rows": len(rows), "first_date": days[0], "last_date": days[-1], "observed_switches": switches}


def compare_contracts(continuous, individual):
    lookup = {(str(row["date"])[:10], row["contract"]): row for row in individual}
    matched = sum(lookup.get((str(row["date"])[:10], row["contract"]), {}).get("close") == row["close"] for row in continuous)
    switches = []
    ordered = sorted(continuous, key=lambda row: row["date"])
    for before, after in zip(ordered, ordered[1:]):
        if before["contract"] != after["contract"]:
            day = str(after["date"])[:10]
            switches.append({"date": day, "both_contracts_present": all((day, contract) in lookup for contract in (before["contract"], after["contract"]))})
    return {"close_matches": matched, "continuous_rows": len(continuous), "switch_checks": switches, "statuses": sorted({str(row.get("status")) for row in continuous})}


def main():
    key = os.environ.get("FINZDATA_API_KEY")
    if not key:
        raise SystemExit("FINZDATA_API_KEY is required")
    specs = {
        "contracts": ("/v1/futures/contracts", {"root": "CL"}),
        "continuous": ("/v1/futures/daily", {"root": "CL", "continuous": "true", "adjust": "none", "limit": 100000}),
        "individual": ("/v1/futures/daily", {"root": "CL", "continuous": "false", "limit": 100000}),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = ROOT / ("finz-wti-" + stamp + "-" + uuid.uuid4().hex[:10])
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {"source": "FinzData", "model_use": False, "reason": "research only; availability timestamps and rollout evidence not verified", "responses": {}}
    payloads = {}
    try:
        for kind, (path, params) in specs.items():
            before = datetime.now(timezone.utc).isoformat()
            response = requests.get(BASE + path, params=params, headers={"X-API-Key": key}, timeout=30)
            response.raise_for_status()
            received = datetime.now(timezone.utc).isoformat()
            raw = response.content
            payload = response.json()
            payloads[kind] = payload
            checks = validate(payload, kind)
            target = folder / (kind + ".json")
            with target.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            manifest["responses"][kind] = {"url": BASE + path, "params": params, "received_utc": received, "request_started_utc": before, "sha256": hashlib.sha256(raw).hexdigest(), "history_note": payload.get("history_note"), "checks": checks}
        manifest["cross_checks"] = compare_contracts(payloads["continuous"]["data"], payloads["individual"]["data"])
        with (folder / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"snapshot": str(folder), "responses": manifest["responses"], "cross_checks": manifest["cross_checks"], "model_use": False}, ensure_ascii=False))
    except (requests.RequestException, ValueError, OSError) as exc:
        # Status code distinguishes e.g. 401 (key) from 429 (rate limit); never print the request/headers (API key).
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        print(json.dumps({"snapshot": str(folder), "error": type(exc).__name__, "http_status": status,
                          "model_use": False}), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
