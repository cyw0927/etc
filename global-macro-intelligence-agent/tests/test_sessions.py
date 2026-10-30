"""Known one-off session changes (KRX CSAT day) reach every place that decides whether a bar is complete."""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal

from gmia.config import asset_specs, load_config
from gmia.data.clean import drop_incomplete_bars
from gmia.data.sessions import apply_schedule_overrides, close_time_for, session_override
from gmia.evaluation.forward import bar_completion_utc

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_libraries_still_miss_csat_day_so_override_is_needed():
    raw = mcal.get_calendar("XKRX").schedule("2026-11-19", "2026-11-19")
    assert raw["market_close"].iloc[0].tz_convert("Asia/Seoul").strftime("%H:%M") == "15:30"
    fixed = apply_schedule_overrides("XKRX", raw)
    assert fixed["market_open"].iloc[0].tz_convert("Asia/Seoul").strftime("%H:%M") == "10:00"
    assert fixed["market_close"].iloc[0].tz_convert("Asia/Seoul").strftime("%H:%M") == "16:30"


def test_normal_days_and_other_markets_are_untouched():
    raw = mcal.get_calendar("XKRX").schedule("2026-11-18", "2026-11-20")
    fixed = apply_schedule_overrides("XKRX", raw)
    assert fixed.loc[raw.index[0]].equals(raw.loc[raw.index[0]])
    assert fixed.loc[raw.index[2]].equals(raw.loc[raw.index[2]])
    assert session_override("NYSE", "2026-11-19") is None
    assert close_time_for("SPY", "2026-11-19", "16:00") == "16:00"
    assert close_time_for("KOSPI", "2026-11-18", "15:30") == "15:30"


def test_v04_ledger_bar_completion_uses_csat_close():
    spec = asset_specs(load_config())["KOSPI"]
    # 16:30 KST + 15 min = 07:45 UTC (not 06:45 UTC)
    assert bar_completion_utc("2026-11-19", spec) == datetime(2026, 11, 19, 7, 45, tzinfo=timezone.utc)
    assert bar_completion_utc("2026-11-18", spec) == datetime(2026, 11, 18, 6, 45, tzinfo=timezone.utc)


def test_collection_drops_a_still_trading_csat_bar():
    bars = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.to_datetime(["2026-11-18", "2026-11-19"]))
    at_1600_kst = datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc)
    kept = drop_incomplete_bars(bars, "Asia/Seoul", "15:30", at_1600_kst, asset="KOSPI")
    assert list(kept.index) == [pd.Timestamp("2026-11-18")]
    legacy = drop_incomplete_bars(bars, "Asia/Seoul", "15:30", at_1600_kst)  # without asset: old behaviour
    assert len(legacy) == 2


def test_pit_issuance_schedule_and_safe_forward_calendar_use_override():
    issue = _load("issue_pit_baseline")
    sched = issue.market_schedule("KOSPI", "2026-11-19", "2026-11-19")
    assert sched["market_close"].iloc[0].tz_convert("Asia/Seoul").strftime("%H:%M") == "16:30"
    safe = _load("safe_forward")
    _, s = safe.expected_dates("KOSPI", pd.Timestamp("2026-11-19"), pd.Timestamp("2026-11-20"))
    assert s["market_close"].iloc[0].tz_convert("Asia/Seoul").strftime("%H:%M") == "16:30"
    # at 16:00 KST on CSAT day the 11-19 session is not yet complete for the freshness check
    px = pd.DataFrame({"adj_close": [1.0]}, index=pd.to_datetime(["2026-11-18"]))
    assert safe.latest_completed_missing("KOSPI", px, datetime(2026, 11, 19, 7, 0, tzinfo=timezone.utc)) is None
