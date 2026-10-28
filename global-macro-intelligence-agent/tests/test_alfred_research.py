import importlib.util,sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import alfred_research_features as af
import train_alfred_research as tr

def events():
    return {s:[{'series':s,'observation_date':'2004-01-01','value':1.,'realtime_start_date':'2004-01-10','realtime_end_date':'2005-02-09'},
               {'series':s,'observation_date':'2004-01-01','value':2.,'realtime_start_date':'2005-02-10','realtime_end_date':None}] for s in af.SERIES}

def test_revision_two_day_lag_and_no_intraday_claim():
    times=pd.to_datetime(['2005-02-11T23:59:00Z','2005-02-12T00:00:00Z'])
    x=af.historical_features(events(),times)
    assert (x.iloc[0]==1.).all()
    assert (x.iloc[1]==2.).all()
    with pytest.raises(ValueError):af.historical_features(events(),pd.to_datetime(['2005-02-11']))

def test_model_input_uses_completed_exchange_window_and_cutoff():
    sch=mcal.get_calendar('NYSE').schedule('2005-01-01','2007-01-31')
    idx=pd.DatetimeIndex(sch.index).tz_localize(None)
    prices=100+np.arange(len(idx))*.01+np.sin(np.arange(len(idx)))
    frame=pd.DataFrame({'adj_close':prices},index=idx)
    meta={'fetched_at_utc':'2007-02-01T00:00:00+00:00','ingested_at_utc':'2007-02-01T00:01:00+00:00'}
    X,y=tr.train_input(frame,meta,events(),datetime(2007,2,1,1,tzinfo=timezone.utc))
    assert len(X)>252 and y.index.max()==idx[-6] and X.index.equals(y.index)
    damaged=frame.drop(idx[100]); X2,y2=tr.train_input(damaged,meta,events(),datetime(2007,2,1,1,tzinfo=timezone.utc))
    assert len(y)-len(y2)==6

