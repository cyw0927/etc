from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sqlite3
import sys
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
spec=importlib.util.spec_from_file_location('score_pit_baseline', Path(__file__).resolve().parents[1] / 'scripts' / 'score_pit_baseline.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
UTC=timezone.utc

def fixture():
    sch=mcal.get_calendar('NYSE').schedule('2026-10-27','2026-11-30')
    index=pd.DatetimeIndex(sch.index).tz_localize(None)
    frame=pd.DataFrame({'adj_close':100 + np.arange(len(index))}, index=index)
    row={'model':'pit_baseline_v0.5','horizon':5,'forecast_date':'2026-10-27','asset':'SPY','issued_utc':'2026-10-28T00:00:00+00:00','anchor_price':100.,'probability':.6,'run_id':'origin'}
    meta={'source':'Yahoo Finance (yfinance)','fetched_at_utc':'2026-11-05T22:00:00+00:00','ingested_at_utc':'2026-11-05T22:01:00+00:00','snapshot_id':'snapshot','pointer':{'manifest_sha256':'hash'}}
    return row,frame,meta

def test_maturity_real_calendar_and_brier():
    row,frame,meta=fixture()
    out,reason=mod.score_one(row,frame,meta,datetime(2026,11,6,tzinfo=UTC))
    assert reason is None and out['maturity_date']=='2026-11-03'
    assert out['outcome']==1 and out['brier']==pytest.approx(.16)

def test_pending_and_early_collection():
    row,frame,meta=fixture()
    out,reason=mod.score_one(row,frame,meta,datetime(2026,10,30,tzinfo=UTC))
    assert out is None and 'pending' in reason
    meta['fetched_at_utc']='2026-11-03T19:00:00+00:00'
    out,reason=mod.score_one(row,frame,meta,datetime(2026,11,6,tzinfo=UTC))
    assert out is None and 'before maturity' in reason

def test_missing_session_revised_anchor_late_issue_provider():
    row,frame,meta=fixture(); now=datetime(2026,11,6,tzinfo=UTC)
    with pytest.raises(ValueError): mod.score_one(row,frame.drop(frame.index[2]),meta,now)
    modified=frame.copy(); modified.iloc[0,0]=101
    with pytest.raises(ValueError): mod.score_one(row,modified,meta,now)
    with pytest.raises(ValueError): mod.score_one(dict(row,issued_utc='2026-10-28T20:00:00+00:00'),frame,meta,now)
    with pytest.raises(ValueError): mod.score_one(row,frame,dict(meta,source='other'),now)

def test_separate_score_db_atomic_idempotence(tmp_path):
    row,frame,meta=fixture(); now=datetime(2026,11,6,tzinfo=UTC)
    score,_=mod.score_one(row,frame,meta,now); path=tmp_path/'scores.sqlite3'
    assert mod.save_scores(path,[score],{},now)['inserted']==1
    assert mod.save_scores(path,[score],{},now)['duplicates']==1
    altered=dict(score,maturity_price=110.)
    with pytest.raises(ValueError): mod.save_scores(path,[dict(score,horizon=20),altered],{},now)
    with sqlite3.connect(path) as db:
        assert db.execute('select count(*) from scores').fetchone()[0]==1
        assert db.execute('select count(*) from score_runs').fetchone()[0]==2
        with pytest.raises(sqlite3.IntegrityError): db.execute('delete from scores')
