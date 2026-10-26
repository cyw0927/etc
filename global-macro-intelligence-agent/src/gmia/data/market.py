"""Daily market data from Yahoo Finance via yfinance.

Failures are logged and reported; there is no fallback to synthetic data.
Yahoo data is for personal research use under Yahoo's terms; yfinance is an unofficial client.
"""

from __future__ import annotations

import time as _time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from gmia.config import AssetSpec, resolve
from gmia.data.clean import clean_prices, drop_incomplete_bars
from gmia.data.store import load_series, save_series
from gmia.utils.logging import get_logger

log = get_logger("gmia.data.market")

_RENAME = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"}


def market_path(raw_dir: str, key: str) -> Path:
    return resolve(raw_dir) / "market" / f"{key}.parquet"


def _download(ticker: str, start: str, end: str | None, retries: int = 3) -> pd.DataFrame:
    import yfinance as yf

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = yf.download(
                    ticker, start=start, end=end, interval="1d", auto_adjust=False, actions=False,
                    progress=False, multi_level_index=False, threads=False,
                )
            if df is not None and not df.empty:
                return df.rename(columns=_RENAME)
            last_err = RuntimeError("empty response")
        except Exception as e:  # network / rate limit / parsing
            last_err = e
        log.warning("download %s attempt %d failed: %s", ticker, attempt, last_err)
        _time.sleep(2 * attempt)
    raise RuntimeError(f"Yahoo download failed for {ticker}: {last_err}")


def fetch_asset(spec: AssetSpec, start: str, end: str | None, raw_dir: str, now_utc: datetime | None = None) -> dict:
    """Download, clean and store one asset. Returns its metadata (incl. quality report)."""
    now_utc = now_utc or datetime.now(timezone.utc)
    raw = _download(spec.ticker, start, end)
    raw.index = pd.to_datetime(raw.index).tz_localize(None) if raw.index.tz is not None else pd.to_datetime(raw.index)
    before = len(raw)
    raw = drop_incomplete_bars(raw, spec.close_tz, spec.close_time, now_utc)
    clean, quality = clean_prices(raw)
    quality["incomplete_bars_dropped"] = before - len(raw)
    meta = {
        "key": spec.key, "ticker": spec.ticker, "name": spec.name, "source": "Yahoo Finance (yfinance)",
        "price_type": spec.price_type, "currency": spec.currency, "calendar": spec.calendar,
        "fetched_at_utc": now_utc.isoformat(timespec="seconds"), "quality": quality,
    }
    save_series(clean, meta, market_path(raw_dir, spec.key))
    log.info("%s (%s): %s rows %s..%s", spec.key, spec.ticker, quality["rows_clean"], quality["start"], quality["end"])
    return meta


def load_asset(raw_dir: str, key: str) -> tuple[pd.DataFrame, dict] | None:
    return load_series(market_path(raw_dir, key))
