"""Focused guards for macro research rules that earlier tests left unchecked (synthetic data only)."""
import hashlib,json,sqlite3,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pandas as pd
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import alfred_research_features as af
import collect_fred_pages as fred
import issue_macro_forward as issue
import issue_release_checked as issuer
UTC=timezone.utc

# FRED "Updated" shown in Chicago time; all four values match the 2026-09 observation used by the registered events.
PAGES={'CPIAUCSL':('336.298','Oct 14, 2026','08:08 AM'),'UNRATE':('4.2','Oct 02, 2026','08:24 AM'),
       'INDPRO':('103.9506','Oct 16, 2026','08:20 AM'),'M2SL':('23413.9','Oct 27, 2026','12:01 PM')}
START='2026-10-29T01:00:00+00:00';RECEIVED='2026-10-29T01:00:01+00:00';DECISION=datetime(2026,10,29,1,5,tzinfo=UTC)

def page(value,day,clock):
    return f'''<input id="coed" value="2026-09-01"><span class="series-meta-observation-value">{value}</span><span class="series-meta-updated-date">{day}</span><span class="series-meta-updated-time">{clock} CDT</span>'''.encode()

def snapshot(tmp_path,monkeypatch,pages=None,start=START,received=RECEIVED):
    monkeypatch.setattr(issuer,'RESEARCH',tmp_path)
    folder=tmp_path/'fred';folder.mkdir(exist_ok=True);manifest={'ready':True,'errors':[],'series':{}};features={}
    for sid,(value,day,clock) in {**PAGES,**(pages or {})}.items():
        raw=page(value,day,clock);(folder/(sid+'.html')).write_bytes(raw)
        manifest['series'][sid]={'url':'https://fred.stlouisfed.org/series/'+sid,'file':sid+'.html','sha256':hashlib.sha256(raw).hexdigest(),
            'request_started_utc':start,'received_utc':received,**fred.parse(raw)}
        features[sid]={'observation_date':'2026-09-01','value':float(value),'realtime_start_date':issuer.EVENTS[sid][0]}
    (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return folder,features

def test_release_check_requires_alfred_revision_on_release_day(tmp_path,monkeypatch):
    folder,features=snapshot(tmp_path,monkeypatch)
    assert len(issuer.compare_evidence(folder,features,DECISION))==4
    shifted={**features,'M2SL':{**features['M2SL'],'realtime_start_date':'2026-10-26'}}
    with pytest.raises(ValueError,match='ALFRED revision does not match: M2SL'):issuer.compare_evidence(folder,shifted,DECISION)

def test_release_check_rejects_fred_update_before_official_release(tmp_path,monkeypatch):
    # 07:20 CDT = 12:20 UTC, ten minutes before the 08:30 ET CPI embargo, on the same day.
    folder,features=snapshot(tmp_path,monkeypatch,{'CPIAUCSL':('336.298','Oct 14, 2026','07:20 AM')})
    with pytest.raises(ValueError,match='collection order: CPIAUCSL'):issuer.compare_evidence(folder,features,DECISION)

def test_release_check_requires_fred_update_on_release_day(tmp_path,monkeypatch):
    # After the release time, but one day late.
    folder,features=snapshot(tmp_path,monkeypatch,{'CPIAUCSL':('336.298','Oct 15, 2026','08:08 AM')})
    with pytest.raises(ValueError,match='collection order: CPIAUCSL'):issuer.compare_evidence(folder,features,DECISION)

def test_release_check_requires_fred_update_minute_to_end_before_request(tmp_path,monkeypatch):
    # M2SL updated 17:01 UTC (minute precision); a request at 17:01:30 falls inside that minute.
    decision=datetime(2026,10,27,17,5,tzinfo=UTC)
    folder,features=snapshot(tmp_path,monkeypatch,start='2026-10-27T17:02:00+00:00',received='2026-10-27T17:02:01+00:00')
    assert len(issuer.compare_evidence(folder,features,decision))==4
    folder,features=snapshot(tmp_path,monkeypatch,start='2026-10-27T17:01:30+00:00',received='2026-10-27T17:01:31+00:00')
    with pytest.raises(ValueError,match='collection order: M2SL'):issuer.compare_evidence(folder,features,decision)

FIXED=datetime(2026,10,28,8,49,tzinfo=UTC)
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return FIXED if tz is None else FIXED.astimezone(tz)

def forecast_row():
    return {'asset':'SPY','forecast_date':'2026-10-27','horizon':5,'model':issue.MODEL_NAME,'probability':.6,'anchor_price':100.,'input_hash':'abc'}

def count(path):
    with sqlite3.connect(path) as db:return db.execute('select count(*) from forecasts').fetchone()[0]

def test_insert_blocks_when_utc_date_changed_before_commit(tmp_path,monkeypatch):
    monkeypatch.setattr(issue,'datetime',Clock);path=tmp_path/'ledger.sqlite3'
    manifest={'collection':{'earliest_request_utc':(FIXED-timedelta(hours=1)).isoformat()}}
    with pytest.raises(ValueError,match='UTC date changed'):
        issue.insert_forecast(path,forecast_row(),manifest,FIXED+timedelta(hours=5),(FIXED-timedelta(days=1)).date())
    assert count(path)==0

def test_insert_blocks_after_next_open(tmp_path,monkeypatch):
    monkeypatch.setattr(issue,'datetime',Clock);path=tmp_path/'ledger.sqlite3'
    manifest={'collection':{'earliest_request_utc':(FIXED-timedelta(hours=1)).isoformat()}}
    with pytest.raises(ValueError,match='next market opened'):
        issue.insert_forecast(path,forecast_row(),manifest,FIXED,FIXED.date())
    assert count(path)==0
    assert issue.insert_forecast(path,forecast_row(),manifest,FIXED+timedelta(seconds=1),FIXED.date())['inserted']==1

def test_model_hash_must_match_registration(tmp_path,monkeypatch):
    assert issue.MODEL_HASH=='b08139784b0881dc2147584ed873bbb417326a231c78f2623addf28e0b1e568c'
    monkeypatch.setattr(issue,'RESEARCH',tmp_path)
    model={'report':{'features':[s+'_lag2d' for s in issue.SERIES],'model_trained':True,'forecasts_issued':0},
           'parameters':{'mean':[1.]*4,'scale':[1.]*4,'coefficients':[.1]*4,'intercept':[0.]},'trained_utc':'2026-10-28T08:00:00+00:00'}
    path=tmp_path/'model.json';raw=json.dumps(model).encode();path.write_bytes(raw)
    monkeypatch.setattr(issue,'MODEL_HASH',hashlib.sha256(raw).hexdigest())
    assert issue.load_model(path)['parameters']['coefficients']==[.1]*4
    model['parameters']['coefficients']=[.2]*4;path.write_bytes(json.dumps(model).encode())
    with pytest.raises(ValueError,match='model hash differs'):issue.load_model(path)

def test_training_features_drop_rows_after_realtime_end():
    # Feb observation is withdrawn after 2005-03-10; later decisions must fall back to January, not reuse February.
    events={s:[{'series':s,'observation_date':'2005-01-01','value':1.,'realtime_start_date':'2005-02-01','realtime_end_date':None},
               {'series':s,'observation_date':'2005-02-01','value':2.,'realtime_start_date':'2005-03-01','realtime_end_date':'2005-03-10'}] for s in af.SERIES}
    x=af.historical_features(events,pd.to_datetime(['2005-03-05T21:15:00Z','2005-03-20T21:15:00Z']))
    assert (x.iloc[0]==2.).all() and (x.iloc[1]==1.).all()
