"""One-off exchange session changes that the calendar libraries do not know about.

pandas-market-calendars 5.5.0 and exchange-calendars 4.13.2 list Korea's college entrance exam (CSAT) days
as normal 09:00-15:30 sessions. On those days KRX shifts the regular session by one hour to 10:00-16:30 KST.
Using the library close would treat a still-trading KOSPI bar as complete (issuance or scoring on a partial
bar). This is a factual correction of "actual regular-session close", not a change of any registered rule.

Add a date only with a source. Update the 2026 entry if KRX's own notice differs.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

KST = ZoneInfo("Asia/Seoul")

# date -> (open, close) in KST, with the evidence for each entry
KRX_SESSION_OVERRIDES: dict[str, tuple[str, str, str]] = {
    "2023-11-16": ("10:00", "16:30", "KRX CSAT-day notice (2024 CSAT), regular session 10:00-16:30"),
    "2024-11-14": ("10:00", "16:30", "KRX CSAT-day notice (2025 CSAT), regular session 10:00-16:30"),
    "2025-11-13": ("10:00", "16:30", "KRX CSAT-day notice (2026 CSAT), regular session 10:00-16:30"),
    "2026-11-19": ("10:00", "16:30", "EXPECTED: 2027 CSAT date announced by KICE 2026-03-31; hours follow the "
                                     "2023-2025 KRX pattern, KRX notice for 2026 not yet published"),
}

MARKET_OVERRIDES = {"XKRX": KRX_SESSION_OVERRIDES}
ASSET_MARKET = {"KOSPI": "XKRX"}


def session_override(market: str, day: date | str | pd.Timestamp) -> tuple[datetime, datetime] | None:
    """(open, close) as aware KST datetimes when `day` has a known one-off session change."""
    key = pd.Timestamp(day).strftime("%Y-%m-%d")
    entry = MARKET_OVERRIDES.get(market, {}).get(key)
    if entry is None:
        return None
    d = pd.Timestamp(key).date()

    def hhmm(s: str) -> time:
        h, m = s.split(":")
        return time(int(h), int(m))

    return datetime.combine(d, hhmm(entry[0]), tzinfo=KST), datetime.combine(d, hhmm(entry[1]), tzinfo=KST)


def apply_schedule_overrides(market: str, schedule: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of a pandas-market-calendars schedule with known one-off sessions corrected."""
    out = schedule.copy()
    for idx in out.index:
        hit = session_override(market, idx)
        if hit is None:
            continue
        tz = out["market_close"].dt.tz
        out.loc[idx, "market_open"] = pd.Timestamp(hit[0]).tz_convert(tz)
        out.loc[idx, "market_close"] = pd.Timestamp(hit[1]).tz_convert(tz)
    return out


def close_time_for(asset: str | None, day: date | str | pd.Timestamp, default_close: str) -> str:
    """Local close time "HH:MM" for an asset's bar dated `day` (config default unless overridden)."""
    market = ASSET_MARKET.get(asset or "")
    hit = session_override(market, day) if market else None
    return hit[1].strftime("%H:%M") if hit else default_close
