"""Validate Coinbase Exchange BTC-USD daily buckets; independent research source, not Yahoo replacement."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import requests

UTC=timezone.utc
URL='https://api.exchange.coinbase.com/products/BTC-USD/candles'

def parse_daily(payload, fetched_at, count):
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None: raise ValueError('timezone required')
    now=fetched_at.astimezone(UTC)
    end=now.replace(hour=0,minute=0,second=0,microsecond=0)
    # Give the provider 15 minutes after bucket close; this is a buffer, not a vendor guarantee.
    if now < end+timedelta(minutes=15): end-=timedelta(days=1)
    expected=[int((end-timedelta(days=i)).timestamp()) for i in range(count,0,-1)]
    buckets={}
    if not isinstance(payload,list): raise ValueError('invalid response')
    for r in payload:
        if not isinstance(r,list) or len(r)<6: raise ValueError('invalid candle')
        t=r[0]
        if not isinstance(t,int) or t%86400 != 0: raise ValueError('non-UTC daily bucket')
        if t in buckets: raise ValueError('duplicate candle')
        values=[float(v) for v in r[1:6]]
        if not all(math.isfinite(v) for v in values) or min(values[:4])<=0 or values[4]<0: raise ValueError('invalid candle values')
        low,high,open_,close,volume=values
        if not low<=min(open_,close)<=max(open_,close)<=high: raise ValueError('invalid OHLC')
        buckets[t]=values
    missing=[datetime.fromtimestamp(t,UTC).date().isoformat() for t in expected if t not in buckets]
    if missing: raise ValueError('missing UTC daily buckets: '+','.join(missing))
    return [{'date_utc':datetime.fromtimestamp(t,UTC).date().isoformat(),'close':buckets[t][3]} for t in expected]

def main():
    started=datetime.now(UTC)
    start=started-timedelta(days=10)
    response=requests.get(URL,params={'granularity':86400,'start':start.isoformat(),'end':started.isoformat()},timeout=20)
    response.raise_for_status()
    finished=datetime.now(UTC)
    # Only intervals already complete when the request began can be used.
    bars=parse_daily(response.json(),started,7)
    print(json.dumps({'provider':'Coinbase Exchange','instrument':'BTC-USD','request_start_utc':started.isoformat(),
       'response_end_utc':finished.isoformat(),'raw_response_sha256':hashlib.sha256(response.content).hexdigest(),
       'verified_daily_buckets':len(bars),'first_day_utc':bars[0]['date_utc'],'last_day_utc':bars[-1]['date_utc'],
       'mode':'read-only provider probe; not Yahoo, not a forecast, not stored'},indent=2))

if __name__=='__main__': main()
