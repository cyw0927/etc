from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import pytest
import pandas_market_calendars as mcal

from gmia.data.availability_v05 import Vintage, latest_known

spec = importlib.util.spec_from_file_location('issue_pit_baseline', Path(__file__).resolve().parents[1] / 'scripts' / 'issue_pit_baseline.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
UTC = timezone.utc

def test_release_revision_and_ingestion_boundaries():
    t = datetime(2024, 1, 1, 12, tzinfo=UTC)
    first = Vintage('CPI', t, t + timedelta(minutes=2), None, 'verified_release', 1)
    revision = Vintage('CPI', t + timedelta(days=1), t + timedelta(days=1, minutes=5), None, 'verified_release', 2)
    assert not first.available(t + timedelta(minutes=1))
    assert latest_known([first, revision], t + timedelta(days=1, minutes=1))['CPI'].value == 1
    assert latest_known([first, revision], t + timedelta(days=1, minutes=5))['CPI'].value == 2
    assert not Vintage('CPI', t, t, None, 'unknown', 1).available(t)
    assert not Vintage('CPI', None, t, None, 'verified_release', 1).available(t)
    with pytest.raises(ValueError): first.available(datetime(2024, 1, 1))

def fixture_prices():
    schedule = mcal.get_calendar('NYSE').schedule('2023-01-01', '2026-10-27')
    index = pd.DatetimeIndex(schedule.index).tz_localize(None)
    values = 100 + np.arange(len(index)) / 100 + np.sin(np.arange(len(index)))
    return pd.DataFrame({'adj_close':values}, index=index)

def metadata():
    return {'fetched_at_utc':'2026-10-27T21:00:00+00:00','ingested_at_utc':'2026-10-27T21:01:00+00:00', 'snapshot_id':'snapshot', 'pointer':{'manifest_sha256':'abc'}}

def test_exchange_windows_and_missing_session():
    frame = fixture_prices()
    decision = datetime(2026, 10, 28, 0, tzinfo=UTC)
    result = mod.prepare_asset('SPY', frame, metadata(), decision)
    assert len(result) == 2
    for row in result:
        h = row['horizon']
        expected = (frame.adj_close.shift(-h).iloc[:-h] > frame.adj_close.iloc[:-h]).mean()
        assert row['probability'] == pytest.approx(expected)
        assert row['n_train'] == len(frame)-h
    removed = frame.drop(frame.index[300])
    after = mod.prepare_asset('SPY', removed, metadata(), decision)
    for a, b in zip(result, after): assert a['n_train'] - b['n_train'] == a['horizon'] + 1

def test_close_ingestion_next_open_and_missing_anchor():
    frame=fixture_prices()
    with pytest.raises(ValueError): mod.prepare_asset('SPY',frame,metadata(),datetime(2026,10,27,20,10,tzinfo=UTC))
    with pytest.raises(ValueError): mod.prepare_asset('SPY',frame,metadata(),datetime(2026,10,28,14,tzinfo=UTC))
    with pytest.raises(ValueError): mod.prepare_asset('SPY',frame.iloc[:-1],metadata(),datetime(2026,10,28,0,tzinfo=UTC))
    late = dict(metadata(), ingested_at_utc='2026-10-28T01:00:00+00:00')
    with pytest.raises(ValueError): mod.prepare_asset('SPY',frame,late,datetime(2026,10,28,0,tzinfo=UTC))

def test_calendar_dst_and_holiday():
    s=mod.market_schedule('SPY','2026-03-06','2026-03-09')
    assert s['market_open'].iloc[0].hour == 14
    assert s['market_open'].iloc[1].hour == 13
    s=mod.market_schedule('SPY','2026-11-25','2026-11-27')
    assert pd.Timestamp('2026-11-26') not in s.index
    with pytest.raises(ValueError): mod.market_schedule('BTC','2026-01-01','2026-01-02')

def test_ledger_idempotence_immutability_and_atomic_conflict(tmp_path):
    row=mod.prepare_asset('SPY',fixture_prices(),metadata(),datetime(2026,10,28,0,tzinfo=UTC))[0]
    when=datetime(2026,10,28,0,tzinfo=UTC)
    path=tmp_path/'ledger.sqlite3'
    assert mod.persist(path,[row],{},when)['inserted'] == 1
    assert mod.persist(path,[row],{},when)['duplicates'] == 1
    new=dict(row, horizon=20)
    conflict=dict(row, probability=0.123)
    with pytest.raises(ValueError): mod.persist(path,[new,conflict],{},when)
    with sqlite3.connect(path) as db:
        assert db.execute('select count(*) from forecasts').fetchone()[0] == 1
        assert db.execute('select count(*) from issuance_runs').fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError): db.execute('delete from forecasts')
