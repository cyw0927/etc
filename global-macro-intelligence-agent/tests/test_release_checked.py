import hashlib,json,sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect_fred_pages as fred
import issue_release_checked as issuer
UTC=timezone.utc

def page(value,day,clock,zone='CDT'):
    return f'''<input id="coed" value="2026-09-01"><span class="series-meta-observation-value">{value}</span><span class="series-meta-updated-date">{day}</span><span class="series-meta-updated-time">{clock} {zone}</span><a href="/releases/calendar?rid=1"><span class="series-meta-updated-date">Nov 24, 2026</span></a>'''.encode()

def test_page_extract_update_not_next_release_and_dst():
    x=fred.parse(page('23,413.9','Oct 27, 2026','12:01 PM'))
    assert x['value']==23413.9 and x['fred_updated_minute_utc']=='2026-10-27T17:01:00+00:00'
    with pytest.raises(ValueError):fred.parse(page('1','Oct 27, 2026','12:01 PM','CST'))

def test_evidence_checks_value_hash_and_times(tmp_path,monkeypatch):
    monkeypatch.setattr(issuer,'RESEARCH',tmp_path)
    folder=tmp_path/'snap';folder.mkdir()
    inputs={'CPIAUCSL':('336.298','Oct 14, 2026','08:08 AM'),'UNRATE':('4.2','Oct 02, 2026','08:24 AM'),
            'INDPRO':('103.9506','Oct 16, 2026','08:20 AM'),'M2SL':('23413.9','Oct 27, 2026','12:01 PM')}
    manifest={'ready':True,'errors':[],'series':{}};features={}
    for sid,(value,day,clock) in inputs.items():
        raw=page(value,day,clock);name=sid+'.html';(folder/name).write_bytes(raw); parsed=fred.parse(raw)
        manifest['series'][sid]={'url':'https://fred.stlouisfed.org/series/'+sid,'file':name,'sha256':hashlib.sha256(raw).hexdigest(),
            'request_started_utc':'2026-10-29T01:00:00+00:00','received_utc':'2026-10-29T01:00:01+00:00',**parsed}
        features[sid]={'observation_date':'2026-09-01','value':float(value),'realtime_start_date':issuer.EVENTS[sid][0]}
    (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    now=datetime(2026,10,29,2,tzinfo=UTC)
    assert len(issuer.compare_evidence(folder,features,now))==4
    wrong={**features,'M2SL':{**features['M2SL'],'value':0}}
    with pytest.raises(ValueError):issuer.compare_evidence(folder,wrong,now)
    with pytest.raises(ValueError):issuer.compare_evidence(folder,features,now-timedelta(hours=2))
    (folder/'M2SL.html').write_bytes(b'tampered')
    with pytest.raises(ValueError):issuer.compare_evidence(folder,features,now)
