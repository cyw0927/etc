import hashlib,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import compare_fred_observations as mod
from collect_fred_pages import SERIES,parse

def make(root,name,time,value):
    folder=root/name;folder.mkdir();series={}
    for sid in SERIES:
        raw=f'<input id="coed" value="2026-09-01"><span class="series-meta-observation-value">{value}</span><span class="series-meta-updated-date">Oct 27, 2026</span><span class="series-meta-updated-time">12:01 PM CDT</span>'.encode()
        filename=sid+'.html';(folder/filename).write_bytes(raw)
        series[sid]={'file':filename,'url':'https://fred.stlouisfed.org/series/'+sid,'sha256':hashlib.sha256(raw).hexdigest(),'request_started_utc':time,'received_utc':time,**parse(raw)}
    (folder/'manifest.json').write_text(json.dumps({'ready':True,'errors':[],'series':series}),encoding='utf8')
    return folder

def test_comparison_and_tampering(tmp_path,monkeypatch):
    monkeypatch.setattr(mod,'ROOT',tmp_path)
    a=make(tmp_path,'a','2026-10-29T00:00:00+00:00','1');b=make(tmp_path,'b','2026-10-29T01:00:00+00:00','2')
    out=mod.compare(a,b);assert all(v['latest_value_changed'] for v in out.values())
    with pytest.raises(ValueError):mod.compare(b,a)
    (b/'M2SL.html').write_bytes(b'changed')
    with pytest.raises(ValueError):mod.compare(a,b)
