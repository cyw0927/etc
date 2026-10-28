"""Fetch selected ALFRED point-in-time dates as immutable research snapshots, never model-ready."""
import csv, hashlib, io, json, math, os, uuid
from datetime import datetime, timezone
import requests
from gmia.config import PROJECT_ROOT

UTC=timezone.utc
URL='https://alfred.stlouisfed.org/graph/alfredgraph.csv'
SERIES=('CPIAUCSL','UNRATE','INDPRO','M2SL')
VINTAGES=('2020-03-01','2021-03-01','2026-10-27')

def parse(content, series, vintage):
    text=content.decode('utf-8-sig'); reader=csv.DictReader(io.StringIO(text))
    name=series+'_'+vintage.replace('-','')
    if reader.fieldnames != ['observation_date',name]: raise ValueError('unexpected ALFRED CSV identity')
    values={}; seen=set()
    for row in reader:
        key=row['observation_date']; datetime.strptime(key,'%Y-%m-%d')
        if key in seen: raise ValueError('duplicate observation')
        seen.add(key)
        value=row[name]
        if value not in ('.',''):
            number=float(value)
            if not math.isfinite(number): raise ValueError('non-finite observation')
            values[key]=number
    return values

def main():
    started=datetime.now(UTC)
    folder=PROJECT_ROOT/'data/operations/source_research'/('alfred-sampled-'+started.strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:10])
    folder.mkdir(parents=True,exist_ok=False); source=[]; values={}; errors=[]
    for series in SERIES:
        for vintage in VINTAGES:
            begin=datetime.now(UTC)
            try:
                r=requests.get(URL,params={'id':series,'vintage_date':vintage},timeout=30)
                r.raise_for_status(); parsed=parse(r.content,series,vintage)
                name=f'{series}-{vintage}.csv'
                with (folder/name).open('xb') as f: f.write(r.content); f.flush(); os.fsync(f.fileno())
                source.append({'series':series,'vintage_date':vintage,'file':name,'sha256':hashlib.sha256(r.content).hexdigest(),
                    'request_started_utc':begin.isoformat(),'response_received_utc':datetime.now(UTC).isoformat(),'observations':len(parsed)})
                values[(series,vintage)]=parsed
            except (requests.RequestException,ValueError,UnicodeDecodeError) as e: errors.append({'series':series,'vintage_date':vintage,'error':str(e)})
    differences={}
    for sid in SERIES:
        a=values.get((sid,VINTAGES[0]),{});b=values.get((sid,VINTAGES[1]),{})
        both=a.keys() & b.keys()
        differences[sid]={'shared_observations':len(both),'changed':sum(a[k]!=b[k] for k in both)}
    report={'sources':source,'errors':errors,'sample_comparison_2020_2021':differences,
            'warning':'selected dates only, not complete revision history; daily vintages do not establish intraday release or past ingestion',
            'ready_for_live_model':False}
    with (folder/'manifest.json').open('x',encoding='utf-8') as f: json.dump(report,f,indent=2); f.flush(); os.fsync(f.fileno())
    print(json.dumps({'directory':str(folder),'downloaded':len(source),'expected':len(SERIES)*len(VINTAGES),'errors':errors,'sample_comparison_2020_2021':differences,'ready_for_live_model':False},indent=2))

if __name__=='__main__': main()


