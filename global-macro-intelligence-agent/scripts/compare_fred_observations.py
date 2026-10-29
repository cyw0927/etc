"""Compare independently captured FRED latest values; no claim of exact revision time."""
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from collect_fred_pages import SERIES,ROOT,parse
from issue_pit_baseline import utc

def snapshot(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT.resolve()):raise ValueError('outside source research directory')
    m=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    if not m.get('ready') or m.get('errors') or set(m.get('series',{}))!=set(SERIES):raise ValueError('incomplete snapshot')
    result={}
    for sid,item in m['series'].items():
        f=(path/item['file']).resolve()
        if not f.is_relative_to(path) or item['url']!='https://fred.stlouisfed.org/series/'+sid:raise ValueError('invalid source')
        b=f.read_bytes()
        if hashlib.sha256(b).hexdigest()!=item['sha256']:raise ValueError('content hash mismatch')
        parsed=parse(b)
        if any(item[k]!=v for k,v in parsed.items()):raise ValueError('metadata mismatch')
        if utc(item['received_utc'])<utc(item['request_started_utc']):raise ValueError('time inversion')
        result[sid]={**parsed,'request_started_utc':item['request_started_utc'],'received_utc':item['received_utc']}
    return result

def compare(first,second):
    a=snapshot(first);b=snapshot(second);out={}
    for sid in SERIES:
        x=a[sid];y=b[sid]
        if utc(x['received_utc'])>utc(y['request_started_utc']):raise ValueError('snapshot sequence overlap')
        changed=(x['observation_date'],x['value'])!=(y['observation_date'],y['value'])
        updated=x['fred_updated_minute_utc']!=y['fred_updated_minute_utc']
        out[sid]={'latest_value_changed':changed,'series_update_time_changed':updated,'old_observed_at_utc':x['received_utc'],
                  'new_observed_at_utc':y['received_utc'],'new_fred_updated_minute_utc':y['fred_updated_minute_utc'],
                  'note':'two observed snapshots only; older period revisions and exact release time not established'}
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);a=p.parse_args()
    print(json.dumps(compare(a.before,a.after),indent=2))
if __name__=='__main__':main()
