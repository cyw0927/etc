"""Collect every configured source, logging failures instead of substituting data."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from gmia.config import asset_specs, resolve
from gmia.data import fred, market
from gmia.utils.logging import get_logger

log = get_logger("gmia.data.collect")


def collect_all(cfg: dict) -> dict:
    d = cfg["data"]
    summary: dict = {"started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "market": {}, "rates": {}, "macro": {}, "macro_realtime": {}, "failures": []}

    for key, spec in asset_specs(cfg).items():
        try:
            summary["market"][key] = market.fetch_asset(spec, d["start"], d.get("end"), d["raw_dir"])
        except Exception as e:
            log.error("market %s failed: %s", key, e)
            summary["failures"].append({"source": "yahoo", "id": key, "error": str(e)})

    for kind in ("rates", "macro"):
        for sid, desc in cfg.get(kind, {}).items():
            try:
                summary[kind][sid] = fred.fetch_and_store_fredgraph(sid, desc, d["start"], d["raw_dir"], kind)
            except Exception as e:
                log.error("FRED %s failed: %s", sid, e)
                summary["failures"].append({"source": "fred", "id": sid, "error": str(e)})

    for sid in cfg.get("macro", {}):
        try:
            meta = fred.fetch_and_store_vintage_features(sid, d["start"], d["raw_dir"])
            if meta is None:
                summary["macro_realtime"][sid] = "skipped: FRED_API_KEY not set (macro excluded from models)"
            else:
                summary["macro_realtime"][sid] = meta
        except Exception as e:
            log.error("ALFRED %s failed: %s", sid, e)
            summary["failures"].append({"source": "alfred", "id": sid, "error": str(e)})

    summary["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = resolve(d["raw_dir"]) / "collection_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if summary["failures"]:
        log.warning("%d source(s) failed; see %s", len(summary["failures"]), out)
    return summary
