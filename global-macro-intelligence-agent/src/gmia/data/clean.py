"""Cleaning and quality checks for daily price series.

Rules:
- one row per date (duplicates: keep the last delivered row), sorted ascending, tz-naive dates
- non-positive prices are invalid for return math and become NaN (e.g. WTI front month on 2020-04-20)
- extreme moves are FLAGGED, never removed or smoothed: real crashes are information
- bars that were not complete at fetch time are dropped (see drop_incomplete_bars)
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PRICE_COLS = ["open", "high", "low", "close", "adj_close"]


def drop_incomplete_bars(
    df: pd.DataFrame, close_tz: str, close_time: str, now_utc: datetime, buffer_minutes: int = 15
) -> pd.DataFrame:
    """Drop bars whose session had not closed (plus buffer) at `now_utc`."""
    if df.empty:
        return df
    tz = ZoneInfo(close_tz)
    hh, mm = (int(x) for x in close_time.split(":"))
    now_local = now_utc.astimezone(tz)

    def complete(d: pd.Timestamp) -> bool:
        close_dt = datetime.combine(d.date(), time(hh, mm), tzinfo=tz) + timedelta(minutes=buffer_minutes)
        return now_local >= close_dt

    mask = np.array([complete(d) for d in df.index])
    return df.loc[mask]


def clean_prices(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Standardize a raw OHLCV frame (index = dates). Returns cleaned frame and a quality report."""
    report: dict = {"rows_raw": int(len(df))}
    out = df.copy()
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    out.index.name = "date"

    dup = out.index.duplicated(keep="last")
    report["duplicates_removed"] = int(dup.sum())
    out = out.loc[~dup].sort_index()

    for c in PRICE_COLS:
        if c in out:
            out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)
    if "adj_close" not in out or out["adj_close"].isna().all():
        out["adj_close"] = out["close"]

    nonpos_close = (out[["close", "adj_close"]] <= 0).any(axis=1)
    report["nonpositive_close_rows"] = [d.strftime("%Y-%m-%d") for d in out.index[nonpos_close]]
    for c in PRICE_COLS:
        if c in out:
            out.loc[out[c] <= 0, c] = np.nan
    out.loc[nonpos_close, ["close", "adj_close"]] = np.nan

    all_nan = out[["close", "adj_close"]].isna().all(axis=1)
    report["missing_close_rows"] = int(all_nan.sum())

    ret = out["adj_close"].pct_change(fill_method=None)
    vol = ret.rolling(60, min_periods=20).std().shift(1)
    extreme = (ret.abs() > 8 * vol) & (ret.abs() > 0.05)
    out["anomaly_flag"] = extreme.fillna(False)
    report["extreme_moves_flagged"] = [
        {"date": d.strftime("%Y-%m-%d"), "return": round(float(ret.loc[d]), 4)} for d in out.index[extreme.fillna(False)]
    ]

    gaps = out.index.to_series().diff().dt.days
    report["max_gap_days"] = int(gaps.max()) if len(gaps) > 1 else 0
    report["gaps_over_7_days"] = [d.strftime("%Y-%m-%d") for d in gaps.index[gaps > 7]]
    stale = out["adj_close"].diff().eq(0).rolling(5).sum().eq(5)
    report["stale_5day_runs"] = int(stale.sum())
    report["rows_clean"] = int(len(out))
    report["start"] = out.index.min().strftime("%Y-%m-%d") if len(out) else None
    report["end"] = out.index.max().strftime("%Y-%m-%d") if len(out) else None
    return out, report
