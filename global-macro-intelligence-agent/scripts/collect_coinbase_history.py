"""Collect Coinbase Exchange BTC-USD daily history in a new independent research snapshot."""
from __future__ import annotations
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from gmia.config import PROJECT_ROOT

UTC=timezone.utc
URL='https://api.exchange.coinbase.com/products/BTC-USD/candles'
RESEARCH=PROJECT_ROOT/'data/operations/source_research'

def boundary(now):
    if now.tzinfo is None or now.utcoffset() is None: raise ValueError('timezone required')
    now=now.astimezone(UTC)
    midnight=now.replace(hour=0,minute=0,second=0,microsecond=0)
    return midnight if now>=midnight+timedelta(minutes=15) else midnight-timedelta(days=1)

def windows(start,end,days=250):
    if start.tzinfo is None or end.tzinfo is None or days<1 or days>299 or start>=end: raise ValueError('invalid window')
    while start<end:
        next_=min(start+timedelta(days=days),end)
        yield start,next_
        start=next_

def normalize(payload,start,end):
    if not isinstance(payload,list): raise ValueError('invalid candle response')
    result={}
    lo=int(start.timestamp()); hi=int(end.timestamp())
    for row in payload:
        if not isinstance(row,list) or len(row)<6 or not isinstance(row[0],int) or row[0]%86400: raise ValueError('invalid bucket timestamp')
        ts=row[0]
        # API may include buckets before requested start. Never assign those to this window.
        if not lo<=ts<hi: continue
        if ts in result: raise ValueError('duplicate bucket in response')
        values=[float(v) for v in row[1:6]]
        if not all(math.isfinite(v) for v in values): raise ValueError('non-finite candle')
        low,high,open_,close,volume=values
        if low<=0 or volume<0 or not low<=min(open_,close)<=max(open_,close)<=high: raise ValueError('invalid OHLCV')
        result[ts]=values
    return result

def new_json(path, obj):
    with path.open('x',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())

def collect(output,start,end,session=None):
    output.mkdir(parents=True,exist_ok=False)
    chunks=output/'chunks'; chunks.mkdir()
    session=session or requests.Session(); all_rows={}; sources=[]; failures=[]
    for idx,(begin,finish) in enumerate(windows(start,end)):
        started=datetime.now(UTC); err=None
        for attempt in range(3):
            try:
                res=session.get(URL,params={'granularity':86400,'start':begin.isoformat(),'end':finish.isoformat()},timeout=30)
                res.raise_for_status()
                parsed=normalize(res.json(),begin,finish)
                break
            except (requests.RequestException,ValueError) as e:
                err=str(e)
                if attempt<2: time.sleep(2**attempt)
        else:
            failures.append({'start':begin.isoformat(),'end':finish.isoformat(),'error':err})
            continue
        ended=datetime.now(UTC)
        name=f'{idx:03d}.json'
        with (chunks/name).open('xb') as f: f.write(res.content); f.flush(); os.fsync(f.fileno())
        sources.append({'file':'chunks/'+name,'sha256':hashlib.sha256(res.content).hexdigest(),'start':begin.isoformat(),'end':finish.isoformat(),
                        'request_start_utc':started.isoformat(),'response_end_utc':ended.isoformat(),'rows':len(parsed)})
        if all_rows.keys() & parsed.keys(): raise ValueError('overlap between windows')
        all_rows.update(parsed)
        time.sleep(.15)
    times=sorted(all_rows)
    missing=[]
    if times:
        expected=range(times[0],times[-1]+1,86400)
        missing=[datetime.fromtimestamp(t,UTC).date().isoformat() for t in expected if t not in all_rows]
    rows=[{'date_utc':datetime.fromtimestamp(t,UTC).date().isoformat(),'low':all_rows[t][0],'high':all_rows[t][1],
           'open':all_rows[t][2],'close':all_rows[t][3],'volume':all_rows[t][4]} for t in times]
    new_json(output/'candles.json',rows)
    candle_hash=hashlib.sha256((output/'candles.json').read_bytes()).hexdigest()
    last=(end-timedelta(days=1)).date().isoformat()
    report={'provider':'Coinbase Exchange','instrument':'BTC-USD','not_yahoo':True,'first_requested_utc':start.isoformat(),
            'last_complete_boundary_utc':end.isoformat(),'earliest_returned':rows[0]['date_utc'] if rows else None,
            'latest_returned':rows[-1]['date_utc'] if rows else None,'rows':len(rows),'missing_internal_days':missing,
            'latest_expected_day':last,'latest_day_present':bool(rows and rows[-1]['date_utc']==last),
            'failures':failures,'chunks':sources,'normalized_sha256':candle_hash,
            'ready':bool(rows and not failures and not missing and rows[-1]['date_utc']==last),
            'warning':'no-trade gaps or provider omissions are not filled; current response is not historical point-in-time evidence'}
    new_json(output/'manifest.json',report)
    return report

def main():
    now=datetime.now(UTC); end=boundary(now); start=datetime(2010,1,1,tzinfo=UTC)
    out=RESEARCH/('coinbase-btc-'+now.strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:10])
    report=collect(out,start,end)
    print(json.dumps({k:v for k,v in report.items() if k not in ('chunks','missing_internal_days')} | {'missing_count':len(report['missing_internal_days']),'directory':str(out)},indent=2))
    if not report['ready']: raise SystemExit(1)

if __name__=='__main__': main()

