from datetime import datetime, timedelta, timezone
import importlib.util, json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('coinbase_history',Path(__file__).resolve().parents[1]/'scripts'/'collect_coinbase_history.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
UTC=timezone.utc

def candle(date):
    t=int(datetime.fromisoformat(date).replace(tzinfo=UTC).timestamp()); return [t,90,110,100,105,2]

def test_windows_and_utc_boundary():
    assert mod.boundary(datetime(2026,10,28,0,14,tzinfo=UTC)).day==27
    assert mod.boundary(datetime(2026,10,28,0,15,tzinfo=UTC)).day==28
    a=datetime(2020,1,1,tzinfo=UTC); b=a+timedelta(days=501)
    assert [(e-s).days for s,e in mod.windows(a,b)]==[250,250,1]
    with pytest.raises(ValueError): list(mod.windows(a,b,300))

def test_normalize_filters_overlap_and_detects_invalid():
    s=datetime(2020,1,1,tzinfo=UTC);e=s+timedelta(days=2)
    data=[candle('2019-12-31'),candle('2020-01-01'),candle('2020-01-02'),candle('2020-01-03')]
    assert len(mod.normalize(data,s,e))==2
    with pytest.raises(ValueError): mod.normalize([data[1],data[1]],s,e)
    with pytest.raises(ValueError): mod.normalize([[data[1][0],90,100,101,99,2]],s,e)

def test_snapshot_missing_and_no_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.time,'sleep',lambda n:None)
    class Response:
        content=json.dumps([candle('2020-01-01'),candle('2020-01-03')]).encode()
        def raise_for_status(self): pass
        def json(self): return json.loads(self.content)
    class Session:
        def get(self,*a,**kw): return Response()
    path=tmp_path/'snapshot';s=datetime(2020,1,1,tzinfo=UTC);e=s+timedelta(days=3)
    report=mod.collect(path,s,e,Session())
    assert report['missing_internal_days']==['2020-01-02'] and not report['ready']
    with pytest.raises(FileExistsError): mod.collect(path,s,e,Session())
