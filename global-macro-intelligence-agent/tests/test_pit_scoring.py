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

def test_separate_score_db_first_score_is_kept(tmp_path):
    row,frame,meta=fixture(); now=datetime(2026,11,6,tzinfo=UTC)
    score,_=mod.score_one(row,frame,meta,now); path=tmp_path/'scores.sqlite3'
    assert mod.save_scores(path,[score],{},now)['inserted']==1
    assert mod.save_scores(path,[score],{},now)['already_scored']==1
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute('delete from scores')
        with pytest.raises(sqlite3.IntegrityError): db.execute('update scores set outcome=0')


def test_later_batch_rescore_does_not_block_new_maturities(tmp_path):
    """Regression: a second batch used to raise on the already-scored row and roll back every new score."""
    row,frame,meta=fixture(); now=datetime(2026,11,6,tzinfo=UTC)
    first,_=mod.score_one(row,frame,meta,now); path=tmp_path/'scores.sqlite3'
    mod.save_scores(path,[first],{},now)
    later_meta=dict(meta,snapshot_id='snapshot-2',pointer={'manifest_sha256':'hash-2'},
                    fetched_at_utc='2026-11-26T22:00:00+00:00',ingested_at_utc='2026-11-26T22:01:00+00:00')
    later=datetime(2026,11,27,tzinfo=UTC)
    same_again,_=mod.score_one(row,frame,later_meta,later)
    h20,_=mod.score_one(dict(row,horizon=20),frame,later_meta,later)
    out=mod.save_scores(path,[same_again,h20],{},later)
    assert out['inserted']==1 and out['already_scored']==1 and out['conflicts']==[]
    with sqlite3.connect(path) as db:
        rows=db.execute('select horizon,snapshot_id from scores order by horizon').fetchall()
    assert rows==[(5,'snapshot'),(20,'snapshot-2')]  # first score keeps its original provenance


def test_conflicting_rescore_is_reported_and_existing_kept(tmp_path):
    row,frame,meta=fixture(); now=datetime(2026,11,6,tzinfo=UTC)
    score,_=mod.score_one(row,frame,meta,now); path=tmp_path/'scores.sqlite3'
    mod.save_scores(path,[score],{},now)
    revised=dict(score,maturity_price=90.,outcome=0,brier=.36,snapshot_id='snapshot-2')
    out=mod.save_scores(path,[revised,dict(score,horizon=20)],{},now)
    assert out['inserted']==1
    assert out['conflicts'][0]['fields']==['maturity_price','outcome','brier']
    with sqlite3.connect(path) as db:
        assert db.execute('select outcome from scores where horizon=5').fetchone()==(1,)
        assert 'maturity_price' in db.execute('select manifest_json from score_runs order by rowid desc').fetchone()[0]


def test_main_skips_forecasts_that_already_have_a_score(tmp_path):
    row,frame,meta=fixture(); now=datetime(2026,11,6,tzinfo=UTC)
    score,_=mod.score_one(row,frame,meta,now); path=tmp_path/'scores.sqlite3'
    assert mod.scored_keys(path)==set()
    mod.save_scores(path,[score],{},now)
    assert mod.scored_keys(path)=={('SPY','2026-10-27',5,'pit_baseline_v0.5')}
