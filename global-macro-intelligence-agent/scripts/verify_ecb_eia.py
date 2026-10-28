"""Independent source verification for ECB reference FX and EIA WTI spot; not model inputs."""
import csv, hashlib, io, json, math, os, uuid
from datetime import datetime, timezone
import requests
import xlrd
from gmia.config import PROJECT_ROOT
UTC=timezone.utc
ECB='https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.csv'
EIA='https://www.eia.gov/dnav/pet/hist_xls/RWTCd.xls'

def inspect_ecb(raw, now=None):
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not {'Date','USD','JPY','KRW'}.issubset(set(reader.fieldnames or [])): raise ValueError('required ECB columns missing')
    rows=[]
    for row in reader:
        try:
            day=datetime.strptime(row['Date'],'%Y-%m-%d').date()
            if day.weekday() >= 5: raise RuntimeError('ECB reference contains a weekend date')
            usd,jpy,krw=(float(row[k]) for k in ('USD','JPY','KRW'))
            if not all(math.isfinite(v) and v>0 for v in (usd,jpy,krw)): raise ValueError()
            rows.append((day,usd,jpy,krw))
        except (ValueError,TypeError): continue
    if not rows: raise ValueError('no comparable reference rates')
    rows.sort();
    if len({r[0] for r in rows})!=len(rows): raise ValueError('duplicate date')
    day,usd,jpy,krw=rows[-1]
    today=(now or datetime.now(UTC).date())
    if day>today or (today-day).days>7: raise ValueError('ECB reference data stale or future dated')
    return {'first_date':rows[0][0].isoformat(),'last_date':day.isoformat(),'valid_rows':len(rows),
            'latest_usdjpy_reference':jpy/usd,'latest_usdkrw_reference':krw/usd,
            'definition':'EURJPY/EURUSD and EURKRW/EURUSD; ECB reference, not New York close'}


def inspect_eia(raw, now=None):
    book=xlrd.open_workbook(file_contents=raw)
    sheet=book.sheet_by_name('Data 1')
    if sheet.cell_value(1,1)!='RWTC' or 'WTI Spot' not in sheet.cell_value(2,1):
        raise ValueError('unexpected EIA series identity')
    seen={}
    for i in range(3,sheet.nrows):
        stamp=sheet.cell_value(i,0); price=sheet.cell_value(i,1)
        if not isinstance(stamp,(int,float)) or not isinstance(price,(int,float)) or not math.isfinite(price):
            raise ValueError('invalid EIA date or price')
        d=xlrd.xldate_as_datetime(stamp,book.datemode).date()
        if d in seen or d.weekday()>=5: raise ValueError('duplicate or weekend EIA date')
        seen[d]=float(price)
    if not seen: raise ValueError('empty EIA spot series')
    latest=max(seen);today=now or datetime.now(UTC).date()
    if latest>today or (today-latest).days>14: raise ValueError('EIA spot data stale or future dated')
    return {'first_date':min(seen).isoformat(),'last_date':latest.isoformat(),'valid_rows':len(seen),
            'definition':'EIA Cushing WTI spot, not NYMEX continuous future',
            'warning':'current historical file does not establish historical release or revision timing'}

def main():
    now=datetime.now(UTC)
    out=PROJECT_ROOT/'data/operations/source_research'/('ecb-eia-'+now.strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:10]);out.mkdir(parents=True,exist_ok=False)
    results={}
    for name,url in [('ecb_reference.csv',ECB),('eia_wti_spot.xls',EIA)]:
        started=datetime.now(UTC); evidence={}
        try:
            r=requests.get(url,timeout=45); r.raise_for_status()
            with (out/name).open('xb') as f: f.write(r.content);f.flush();os.fsync(f.fileno())
            evidence={'file':name,'sha256':hashlib.sha256(r.content).hexdigest(),'bytes':len(r.content)}
            details=inspect_ecb(r.content) if name.endswith('.csv') else inspect_eia(r.content)
            results[name]={'url':url,'request_started_utc':started.isoformat(),'response_received_utc':datetime.now(UTC).isoformat(),'sha256':hashlib.sha256(r.content).hexdigest(),'bytes':len(r.content),**details}
        except (requests.RequestException,ValueError,UnicodeDecodeError,RuntimeError,xlrd.XLRDError) as e: results[name]={'url':url,'error':str(e),**evidence}
    with (out/'manifest.json').open('x',encoding='utf-8') as f: json.dump(results,f,indent=2);f.flush();os.fsync(f.fileno())
    print(json.dumps({'directory':str(out),'results':results},indent=2))

if __name__=='__main__':main()




