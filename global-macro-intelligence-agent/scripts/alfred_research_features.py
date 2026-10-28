"""Date-level retrospective ALFRED features for research. Never certify historical ingestion."""
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict
import hashlib,json
from pathlib import Path
import pandas as pd
from gmia.config import PROJECT_ROOT
from collect_alfred_web import parse_zip,selected_dates,SERIES

ROOT=PROJECT_ROOT/'data/operations/source_research'

def load_revisions(folder):
    folder=Path(folder).resolve()
    if not folder.is_relative_to(ROOT.resolve()):raise ValueError('archive outside research root')
    m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if not m.get('ready') or m.get('failures') or set(m.get('series',{}))!=set(SERIES): raise ValueError('incomplete vintage archive')
    available={};events={};metadata=[]
    for sid in SERIES:
        info=m['series'][sid];path=(folder/info['file']).resolve()
        if not path.is_relative_to(folder):raise ValueError('unsafe form path')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=info['sha256']:raise ValueError('form hash mismatch')
        _,found=selected_dates(raw.decode('utf-8'))
        wanted=[d.isoformat() for d in found]
        if wanted!=info['vintage_dates']:raise ValueError('vintage list mismatch')
        available[sid]=wanted
    for item in m['sources']:
        sid=item['series']
        if sid not in SERIES: raise ValueError('unexpected series')
        path=(folder/item['file']).resolve()
        if not path.is_relative_to(folder):raise ValueError('unsafe archive path')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('vintage archive hash mismatch')
        received=datetime.fromisoformat(item['response_received_utc'])
        started=datetime.fromisoformat(item['request_started_utc'])
        if received.tzinfo is None or started.tzinfo is None or received<started:raise ValueError('invalid collection times')
        rows=parse_zip(raw,sid)
        if len(rows)!=item['rows']:raise ValueError('archive row count mismatch')
        for row in rows:
            key=(sid,row['observation_date'],row['realtime_start_date'])
            if key in events and events[key]!=row:raise ValueError('conflicting vintage period')
            events[key]=row
        metadata.extend((sid,d) for d in item['vintage_dates'])
    for sid in SERIES:
        submitted=[d for s,d in metadata if s==sid]
        if submitted!=available[sid]:raise ValueError('missing or reordered vintage batches')
    grouped=defaultdict(list)
    for (sid,obs,start),row in events.items():grouped[(sid,obs)].append(row)
    for key, rows in grouped.items():
        rows.sort(key=lambda x:x['realtime_start_date'])
        for a,b in zip(rows,rows[1:]):
            if a['realtime_end_date'] is None or a['realtime_end_date']>=b['realtime_start_date']:raise ValueError('overlapping vintage periods')
    result={s:[] for s in SERIES}
    for (sid,obs,start),row in events.items(): result[sid].append(row)
    for sid in SERIES:result[sid].sort(key=lambda r:(r['realtime_start_date'],r['observation_date']))
    return result,m

def historical_features(events, decisions):
    """Assume a 2-day UTC lag on ALFRED date, with no claim of actual past receipt."""
    index=pd.DatetimeIndex(decisions)
    if index.tz is None or not index.is_monotonic_increasing or not index.is_unique:raise ValueError('ordered timezone-aware decisions required')
    columns={}
    for sid in SERIES:
        rows=events[sid]; state={};n=0;values=[]
        for t in index:
            asof=(t.to_pydatetime().astimezone(timezone.utc)-timedelta(days=2)).date().isoformat()
            while n<len(rows) and rows[n]['realtime_start_date']<=asof:
                state[rows[n]['observation_date']]=rows[n];n+=1
            eligible=[r for obs,r in state.items() if obs<=asof and (r['realtime_end_date'] is None or asof<=r['realtime_end_date'])]
            values.append(max(eligible,key=lambda x:x['observation_date'])['value'] if eligible else float('nan'))
        columns[sid+'_lag2d']=values
    return pd.DataFrame(columns,index=index)
