"""FRED data.

- Daily rates (DGS2, DGS10, DFF) come from public fredgraph CSV (no key). The legacy model uses
  a one-date lag, which does not certify exact publication timing or absence of corrections.
- Monthly macro series ARE revised. The public CSV only has today's vintage, so it is stored for display
  and flagged analysis-only. With FRED_API_KEY set, `fetch_vintages` pulls every real-time period from
  ALFRED and `realtime_feature` reconstructs what was actually known on each past date.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from gmia.config import resolve
from gmia.data.store import load_series, save_series
from gmia.utils.logging import get_logger

log = get_logger("gmia.data.fred")

FREDGRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_API = "https://api.stlouisfed.org/fred/series/observations"

# How each monthly series becomes a feature: year-over-year % change, or level with 3-month change.
MACRO_TRANSFORMS = {"CPIAUCSL": "yoy", "INDPRO": "yoy", "M2SL": "yoy", "UNRATE": "level"}


def fred_path(raw_dir: str, series_id: str, kind: str) -> Path:
    return resolve(raw_dir) / "fred" / kind / f"{series_id}.parquet"


def fetch_fredgraph(series_id: str, start: str, timeout: int = 30) -> pd.Series:
    resp = requests.get(FREDGRAPH, params={"id": series_id, "cosd": start}, timeout=timeout)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if df.shape[1] != 2:
        raise RuntimeError(f"unexpected FRED CSV for {series_id}: columns {list(df.columns)}")
    s = pd.to_numeric(df.iloc[:, 1].replace(".", np.nan), errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    s.index.name = "date"
    return s.dropna().rename(series_id)


def fetch_and_store_fredgraph(series_id: str, description: str, start: str, raw_dir: str, kind: str) -> dict:
    s = fetch_fredgraph(series_id, start)
    meta = {
        "series_id": series_id, "description": description, "source": "FRED (fredgraph CSV)",
        "kind": kind, "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": s.index.min().strftime("%Y-%m-%d"), "end": s.index.max().strftime("%Y-%m-%d"), "rows": int(len(s)),
        "vintage": "latest revised values only" if kind == "macro" else "latest rates; release timing not certified",
        "availability_status": "display_only" if kind == "macro" else "legacy_date_lag_assumption",
        "backtest_use": kind == "rates",
    }
    save_series(s.to_frame(), meta, fred_path(raw_dir, series_id, kind))
    log.info("FRED %s: %d rows %s..%s", series_id, len(s), meta["start"], meta["end"])
    return meta


def fetch_vintages(series_id: str, api_key: str, start: str, timeout: int = 60) -> pd.DataFrame:
    """All real-time periods of a series: columns realtime_start, realtime_end, date, value."""
    rows, offset = [], 0
    while True:
        resp = requests.get(FRED_API, params={
            "series_id": series_id, "api_key": api_key, "file_type": "json", "observation_start": start,
            "realtime_start": "1776-07-04", "realtime_end": "9999-12-31", "limit": 100000, "offset": offset,
        }, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        obs = payload.get("observations", [])
        rows.extend(obs)
        offset += len(obs)
        if not obs or offset >= int(payload.get("count", 0)):
            break
    df = pd.DataFrame(rows)
    df["value"] = pd.to_numeric(df["value"].replace(".", np.nan), errors="coerce")
    df["realtime_end"] = df["realtime_end"].replace("9999-12-31", "2262-04-11")
    for c in ("realtime_start", "realtime_end", "date"):
        df[c] = pd.to_datetime(df[c])
    return df.dropna(subset=["value"])[["realtime_start", "realtime_end", "date", "value"]]


def realtime_feature(vintages: pd.DataFrame, transform: str) -> pd.DataFrame:
    """For each vintage date r, the feature computed from data as published on r.

    Returns a frame indexed by vintage date with columns `value` (and `change` for level series), plus
    `obs_date` = the reference month of the latest observation known on r.
    """
    out = []
    for r in np.sort(vintages["realtime_start"].unique()):
        snap = vintages[(vintages["realtime_start"] <= r) & (vintages["realtime_end"] >= r)]
        snap = snap.sort_values("date").set_index("date")["value"]
        if len(snap) < 13:
            continue
        last_date = snap.index[-1]
        if transform == "yoy":
            prev = snap.get(last_date - pd.DateOffset(months=12))
            if prev is None or not np.isfinite(prev):
                continue
            out.append({"vintage": r, "obs_date": last_date, "value": snap.iloc[-1] / prev - 1.0})
        else:
            prev = snap.get(last_date - pd.DateOffset(months=3))
            out.append({"vintage": r, "obs_date": last_date, "value": snap.iloc[-1],
                        "change": snap.iloc[-1] - prev if prev is not None else np.nan})
    return pd.DataFrame(out).set_index("vintage") if out else pd.DataFrame()


def fetch_and_store_vintage_features(series_id: str, start: str, raw_dir: str) -> dict | None:
    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        return None
    vint = fetch_vintages(series_id, api_key, start)
    feat = realtime_feature(vint, MACRO_TRANSFORMS.get(series_id, "yoy"))
    meta = {"series_id": series_id, "source": "FRED/ALFRED API (real-time vintages)", "rows": int(len(feat)),
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "backtest_use": True}
    save_series(feat, meta, fred_path(raw_dir, series_id, "macro_realtime"))
    log.info("ALFRED %s: %d vintages", series_id, len(feat))
    return meta


def load_fred(raw_dir: str, series_id: str, kind: str) -> tuple[pd.DataFrame, dict] | None:
    return load_series(fred_path(raw_dir, series_id, kind))
