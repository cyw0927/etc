from datetime import datetime,timedelta,timezone
import sqlite3,sys
from pathlib import Path
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import issue_macro_forward as issue
import score_macro_forward as score
UTC=timezone.utc

def records():
    return {s:[{'observation_date':'2026-09-01','realtime_start_date':'2026-10-14','realtime_end_date':'2026-10-26','value':1.},
               {'observation_date':'2026-09-01','realtime_start_date':'2026-10-27','realtime_end_date':None,'value':2.}] for s in issue.SERIES}

def test_live_feature_lag_and_no_release_time_fabrication():
    values,e=issue.live_features(records(),datetime(2026,10,28,12,tzinfo=UTC))
    assert values==[1.]*4 and all(x['exact_release_time']=='unknown' for x in e.values())
    values,_=issue.live_features(records(),datetime(2026,10,29,1,tzinfo=UTC));assert values==[2.]*4
    missing=records();missing['UNRATE']=[]
    with pytest.raises(ValueError):issue.live_features(missing,datetime(2026,10,28,12,tzinfo=UTC))

def test_snapshot_collection_freshness_and_future():
    now=datetime(2026,10,28,12,tzinfo=UTC)
    src={'sources':[{'request_started_utc':'2026-10-28T10:00:00Z','response_received_utc':'2026-10-28T10:01:00Z'}],
         'series':{'CPI':{'requested_utc':'2026-10-28T09:00:00Z','received_utc':'2026-10-28T09:01:00Z'}}}
    assert issue.snapshot_timing(src,now)['last_receipt_utc']=='2026-10-28T10:01:00+00:00'
    with pytest.raises(ValueError):issue.snapshot_timing(src,now+timedelta(days=2))
    with pytest.raises(ValueError):issue.snapshot_timing(src,now-timedelta(hours=3))

def test_separate_ledger_first_forecast_score_and_immutability(tmp_path):
    now=datetime.now(UTC);path=tmp_path/'macro.sqlite3'
    row={'asset':'SPY','forecast_date':'2026-10-27','horizon':5,'model':issue.MODEL_NAME,'probability':.6,'anchor_price':100.,'input_hash':'abc'}
    meta={'collection':{'earliest_request_utc':now.isoformat()}}
    assert issue.insert_forecast(path,row,meta,now+timedelta(days=1),now.date())['inserted']==1
    assert issue.insert_forecast(path,row,meta,now+timedelta(days=1),now.date())['duplicate']==1
    with pytest.raises(ValueError):issue.insert_forecast(path,dict(row,probability=.7),meta,now+timedelta(days=1),now.date())
    with sqlite3.connect(path) as db:
        issued=db.execute('select issued_utc from forecasts').fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):db.execute('delete from forecasts')
    s={'asset':'SPY','forecast_date':'2026-10-27','horizon':5,'model':issue.MODEL_NAME,'probability':.6,'anchor_price':100.,'forecast_run_id':issued,
       'maturity_date':'2026-11-03','maturity_price':101.,'outcome':1,'brier':.16,'snapshot_hash':'h'}
    assert score.save(path,[s],{},now)==1
    assert score.save(path,[s],{},now)==0
    with pytest.raises(ValueError):score.save(path,[dict(s,outcome=0)],{},now)
    assert score.pending(path)==[]

def test_score_waits_and_uses_exchange_maturity():
    schedule=mcal.get_calendar('NYSE').schedule('2026-10-27','2026-11-10')
    index=pd.DatetimeIndex(schedule.index).tz_localize(None)
    frame=pd.DataFrame({'adj_close':100+np.arange(len(index))},index=index)
    row={'asset':'SPY','forecast_date':'2026-10-27','horizon':5,'model':issue.MODEL_NAME,'probability':.6,'anchor_price':100.,'issued_utc':'2026-10-28T00:00:00Z'}
    meta={'source':'Yahoo Finance (yfinance)','fetched_at_utc':'2026-11-04T00:00:00Z','ingested_at_utc':'2026-11-04T00:01:00Z','snapshot_id':'x','pointer':{'manifest_sha256':'hash'}}
    result,reason=score.score_candidate(row,frame,meta,datetime(2026,10,30,tzinfo=UTC))
    assert result is None and 'pending' in reason
    result,reason=score.score_candidate(row,frame,meta,datetime(2026,11,4,1,tzinfo=UTC))
    assert reason is None and result['maturity_date']=='2026-11-03' and result['model']==issue.MODEL_NAME
    revised=frame.copy();revised.iloc[0,0]=99
    with pytest.raises(ValueError):score.score_candidate(row,revised,meta,datetime(2026,11,4,1,tzinfo=UTC))
