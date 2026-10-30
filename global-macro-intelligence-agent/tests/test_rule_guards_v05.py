"""Guards for v0.5 timing rules that earlier tests did not pin down (synthetic data only).

Each rejection test has a positive control at the boundary, so the test cannot pass just because
the fixture is invalid for some other reason.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


issue = _load('issue_pit_baseline')
score = _load('score_pit_baseline')
UTC = timezone.utc


def frame_on(calendar, start, end):
    """Synthetic adjusted closes on every session of the exchange calendar."""
    schedule = mcal.get_calendar(calendar).schedule(start, end)
    index = pd.DatetimeIndex(schedule.index).tz_localize(None)
    values = 100 + np.arange(len(index)) / 100 + np.sin(np.arange(len(index)))
    return pd.DataFrame({'adj_close': values}, index=index)


def source(fetched, ingested):
    return {'fetched_at_utc': fetched, 'ingested_at_utc': ingested,
            'snapshot_id': 'snapshot', 'pointer': {'manifest_sha256': 'abc'}}


# SPY anchor 2026-10-27 (EDT): NYSE close 20:00 UTC, so the buffer ends at 20:15 UTC.
SPY = frame_on('NYSE', '2023-01-01', '2026-10-27')


@pytest.mark.parametrize('fetched', ['2026-10-27T20:00:00+00:00', '2026-10-27T20:14:59+00:00'])
def test_issuance_rejects_source_fetched_inside_close_buffer(fetched):
    """(a) A fetch in [close, close+15min) of the anchor is not a completed-bar collection."""
    meta = source(fetched, '2026-10-27T20:15:30+00:00')
    with pytest.raises(ValueError, match='publication, ingestion or next-open timing'):
        issue.prepare_asset('SPY', SPY, meta, datetime(2026, 10, 27, 20, 30, tzinfo=UTC))


def test_issuance_accepts_source_fetched_at_close_plus_buffer():
    """Positive control for (a): the same fixture at exactly close+15min is accepted."""
    meta = source('2026-10-27T20:15:00+00:00', '2026-10-27T20:15:30+00:00')
    rows = issue.prepare_asset('SPY', SPY, meta, datetime(2026, 10, 27, 20, 30, tzinfo=UTC))
    assert [r['forecast_date'] for r in rows] == ['2026-10-27', '2026-10-27']


@pytest.mark.parametrize('minute', [0, 10, 14])
def test_issuance_decision_inside_close_buffer_is_not_a_completed_session(minute):
    """(b) A decision in [close, close+15min) does not make the anchor session complete.

    The fetch and ingest are before the decision, so only the completeness rule decides.
    """
    meta = source(f'2026-10-27T20:{minute:02d}:00+00:00', f'2026-10-27T20:{minute:02d}:00+00:00')
    decision = datetime(2026, 10, 27, 20, minute, 30, tzinfo=UTC)
    with pytest.raises(ValueError, match='latest completed session is 2026-10-26, source ends 2026-10-27'):
        issue.prepare_asset('SPY', SPY, meta, decision)


# Scoring: forecast 2026-10-27, h=5, maturity 2026-11-03 (EST): NYSE close 21:00 UTC, buffer ends 21:15 UTC.
def scoring_fixture():
    schedule = mcal.get_calendar('NYSE').schedule('2026-10-27', '2026-11-30')
    index = pd.DatetimeIndex(schedule.index).tz_localize(None)
    frame = pd.DataFrame({'adj_close': 100. + np.arange(len(index))}, index=index)
    row = {'model': 'pit_baseline_v0.5', 'horizon': 5, 'forecast_date': '2026-10-27', 'asset': 'SPY',
           'issued_utc': '2026-10-28T00:00:00+00:00', 'anchor_price': 100., 'probability': .6, 'run_id': 'origin'}
    meta = {'source': 'Yahoo Finance (yfinance)', 'snapshot_id': 'snapshot', 'pointer': {'manifest_sha256': 'hash'}}
    return row, frame, meta


@pytest.mark.parametrize('now', [datetime(2026, 11, 3, 21, 0, 30, tzinfo=UTC), datetime(2026, 11, 3, 21, 14, 59, tzinfo=UTC)])
def test_scoring_pending_when_now_inside_maturity_buffer(now):
    """(c) now in [maturity close, close+15min): pending, even with a post-close collection."""
    row, frame, meta = scoring_fixture()
    meta = dict(meta, fetched_at_utc='2026-11-03T21:00:10+00:00', ingested_at_utc='2026-11-03T21:00:20+00:00')
    out, reason = score.score_one(row, frame, meta, now)
    assert out is None and reason.startswith('pending until 2026-11-03T21:15:00')


@pytest.mark.parametrize('fetched', ['2026-11-03T21:00:00+00:00', '2026-11-03T21:14:59+00:00'])
def test_scoring_not_scored_when_fetch_inside_maturity_buffer(fetched):
    """(c) A collection that began in [maturity close, close+15min) is not used for a score."""
    row, frame, meta = scoring_fixture()
    meta = dict(meta, fetched_at_utc=fetched, ingested_at_utc='2026-11-03T21:20:00+00:00')
    out, reason = score.score_one(row, frame, meta, datetime(2026, 11, 6, tzinfo=UTC))
    assert out is None and reason == 'collection began before maturity close plus buffer'


def test_scoring_accepts_fetch_at_maturity_close_plus_buffer():
    """Positive control for (c)."""
    row, frame, meta = scoring_fixture()
    meta = dict(meta, fetched_at_utc='2026-11-03T21:15:00+00:00', ingested_at_utc='2026-11-03T21:15:30+00:00')
    out, reason = score.score_one(row, frame, meta, datetime(2026, 11, 3, 21, 16, tzinfo=UTC))
    assert reason is None and out['maturity_date'] == '2026-11-03'


# KRX CSAT day 2026-11-19: session 10:00-16:30 KST (01:00-07:30 UTC); buffer ends 16:45 KST = 07:45 UTC.
KOSPI = frame_on('XKRX', '2022-01-01', '2026-11-19')


def test_csat_day_kospi_fetch_at_1600_kst_is_not_a_completed_anchor():
    """(d) The library close (15:30) would make a 16:00 KST fetch look complete; the real close is 16:30."""
    meta = source('2026-11-19T07:00:00+00:00', '2026-11-19T07:01:00+00:00')
    with pytest.raises(ValueError, match='latest completed session is 2026-11-18, source ends 2026-11-19'):
        issue.prepare_asset('KOSPI', KOSPI, meta, datetime(2026, 11, 19, 7, 5, tzinfo=UTC))


def test_csat_day_kospi_accepted_after_real_close_plus_buffer():
    """Positive control for (d): 16:45 KST fetch, issued before the 2026-11-20 09:00 KST open."""
    meta = source('2026-11-19T07:45:00+00:00', '2026-11-19T07:46:00+00:00')
    rows = issue.prepare_asset('KOSPI', KOSPI, meta, datetime(2026, 11, 19, 7, 50, tzinfo=UTC))
    assert {r['forecast_date'] for r in rows} == {'2026-11-19'}
    assert rows[0]['latest_close_utc'] == '2026-11-19T07:45:00+00:00'


def test_csat_day_maturity_fetch_at_1600_kst_is_pending():
    """(d) Scoring: KOSPI forecast 2026-11-12, h=5 matures on the CSAT day 2026-11-19."""
    schedule = mcal.get_calendar('XKRX').schedule('2026-11-12', '2026-11-30')
    index = pd.DatetimeIndex(schedule.index).tz_localize(None)
    frame = pd.DataFrame({'adj_close': 2500. + np.arange(len(index))}, index=index)
    row = {'model': 'pit_baseline_v0.5', 'horizon': 5, 'forecast_date': '2026-11-12', 'asset': 'KOSPI',
           'issued_utc': '2026-11-12T07:00:00+00:00', 'anchor_price': 2500., 'probability': .5, 'run_id': 'origin'}
    meta = {'source': 'Yahoo Finance (yfinance)', 'snapshot_id': 's', 'pointer': {'manifest_sha256': 'h'},
            'fetched_at_utc': '2026-11-19T07:00:00+00:00', 'ingested_at_utc': '2026-11-19T07:01:00+00:00'}
    out, reason = score.score_one(row, frame, meta, datetime(2026, 11, 19, 7, 5, tzinfo=UTC))
    assert out is None and reason.startswith('pending until 2026-11-19T07:45:00')


def ledger_row():
    return {'asset': 'SPY', 'forecast_date': '2026-10-27', 'horizon': 5, 'model': 'pit_baseline_v0.5',
            'probability': .55, 'n_train': 900, 'anchor_price': 101.5, 'currency': 'USD',
            'snapshot_id': 'snapshot', 'snapshot_hash': 'abc'}


@pytest.mark.xfail(strict=True, reason='issuance conflict check compares only probability and snapshot_hash')
@pytest.mark.parametrize('change', [{'anchor_price': 99.0}, {'n_train': 899}])
def test_issuance_conflict_detects_other_input_differences(tmp_path, change):
    """(e) Pre-registration: a re-run with a different input must stop as a conflict, not be ignored."""
    path = tmp_path / 'ledger.sqlite3'
    when = datetime(2026, 10, 28, tzinfo=UTC)
    assert issue.persist(path, [ledger_row()], {}, when)['inserted'] == 1
    with pytest.raises(ValueError):
        issue.persist(path, [dict(ledger_row(), **change)], {}, when)
