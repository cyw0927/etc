import importlib.util,json,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_coinbase_history as collector
spec=importlib.util.spec_from_file_location('verify_coinbase_history',Path(__file__).resolve().parents[1]/'scripts'/'verify_coinbase_history.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_verify_integrity_and_tamper(tmp_path,monkeypatch):
    monkeypatch.setattr(mod,'RESEARCH',tmp_path); monkeypatch.setattr(collector.time,'sleep',lambda n:None)
    start=datetime(2020,1,1,tzinfo=timezone.utc);end=start+timedelta(days=2)
    class Response:
        content=json.dumps([[int(start.timestamp()),90,110,100,105,2],[int((start+timedelta(days=1)).timestamp()),90,110,100,105,2]]).encode()
        def raise_for_status(self):pass
        def json(self):return json.loads(self.content)
    class Session:
        def get(self,*a,**k):return Response()
    folder=tmp_path/'snapshot';collector.collect(folder,start,end,Session())
    assert mod.verify(folder)['candles_checked']==2
    (folder/'chunks'/'000.json').write_bytes(b'changed')
    with pytest.raises(ValueError):mod.verify(folder)
