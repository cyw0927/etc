"""Verify ECB official ZIP vs SDMX/XML and EIA historical WTI futures; no prediction use."""
import csv,hashlib,io,json,math,os,uuid,zipfile
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET
import requests,xlrd
from gmia.config import PROJECT_ROOT
from verify_ecb_eia import inspect_ecb
UTC=timezone.utc
ROOT=PROJECT_ROOT/'data/operations/source_research'
URLS={'ecb_hist.zip':'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip',
      'ecb_sdmx.csv':'https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+KRW.EUR.SP00.A?lastNObservations=3&format=csvdata',
      'ecb_daily.xml':'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml',
      'eia_rclc1.xls':'https://www.eia.gov/dnav/pet/hist_xls/RCLC1d.xls'}

def compare_ecb(hist,sdmx,xml,now=None):
    with zipfile.ZipFile(io.BytesIO(hist)) as z:
        if z.namelist()!=['eurofxref-hist.csv'] or z.getinfo(z.namelist()[0]).file_size>10_000_000: raise ValueError('unexpected ECB ZIP')
        raw=z.read(z.namelist()[0]); quality=inspect_ecb(raw,now)
    date=quality['last_date']
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    matching=[r for r in rows if r['Date']==date]
    if len(matching)!=1:raise ValueError('ambiguous ECB latest row')
    api=list(csv.DictReader(io.StringIO(sdmx.decode('utf-8-sig'))))
    tree=ET.fromstring(xml); daily_date=[e.attrib['time'] for e in tree.iter() if 'time' in e.attrib]
    if daily_date != [date]:raise ValueError('ECB daily and history dates differ')
    daily={e.attrib['currency']:e.attrib['rate'] for e in tree.iter() if 'currency' in e.attrib and 'rate' in e.attrib}
    for c in ('USD','JPY','KRW'):
        found=[r for r in api if r.get('CURRENCY')==c and r.get('TIME_PERIOD')==date and r.get('CURRENCY_DENOM')=='EUR' and r.get('EXR_TYPE')=='SP00']
        if len(found)!=1 or c not in daily or Decimal(found[0]['OBS_VALUE'])!=Decimal(daily[c]) or Decimal(matching[0][c])!=Decimal(daily[c]):
            raise ValueError('ECB source disagreement for '+c)
    return {'first_date':quality['first_date'],'latest_date':date,'valid_rows':quality['valid_rows'],'three_currencies_match':True,
            'series':'ECB euro reference; USDJPY=EURJPY/EURUSD, USDKRW=EURKRW/EURUSD; not NY close'}

def inspect_futures(raw,now=None):
    book=xlrd.open_workbook(file_contents=raw); s=book.sheet_by_name('Data 1')
    if s.cell_value(1,1)!='RCLC1' or 'Future Contract 1' not in s.cell_value(2,1):raise ValueError('wrong EIA contract series')
    days=[]
    for i in range(3,s.nrows):
        if not isinstance(s.cell_value(i,1),(int,float)) or not math.isfinite(s.cell_value(i,1)):raise ValueError('invalid futures value')
        day=xlrd.xldate_as_datetime(s.cell_value(i,0),book.datemode).date();days.append(day)
    if not days or days!=sorted(set(days)):raise ValueError('missing or duplicate dates')
    today=now or datetime.now(UTC).date()
    if days[-1]>today:raise ValueError('future dated futures observation')
    return {'first_date':days[0].isoformat(),'last_date':days[-1].isoformat(),'rows':len(days),
            'stale':(today-days[-1]).days>14,'definition':'EIA Cushing Crude Oil Future Contract 1; contract identifiers and roll details not provided'}

def main():
    now=datetime.now(UTC);out=ROOT/('official-fx-wti-'+now.strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:10]);out.mkdir(parents=True,exist_ok=False)
    data={};manifest={'sources':{},'checks':{}}
    for name,url in URLS.items():
        t=datetime.now(UTC)
        try:
            res=requests.get(url,timeout=45);res.raise_for_status();data[name]=res.content
            with (out/name).open('xb') as f:f.write(res.content);f.flush();os.fsync(f.fileno())
            manifest['sources'][name]={'url':url,'sha256':hashlib.sha256(res.content).hexdigest(),'started_utc':t.isoformat(),'received_utc':datetime.now(UTC).isoformat(),'last_modified':res.headers.get('Last-Modified')}
        except requests.RequestException as e:manifest['sources'][name]={'url':url,'error':str(e)}
    for name,func,args in [('ecb',compare_ecb,('ecb_hist.zip','ecb_sdmx.csv','ecb_daily.xml')),('eia_futures',inspect_futures,('eia_rclc1.xls',))]:
        try:manifest['checks'][name]=func(*(data[x] for x in args))
        except (KeyError,ValueError,ET.ParseError,zipfile.BadZipFile,xlrd.XLRDError) as e:manifest['checks'][name]={'error':str(e)}
    with (out/'manifest.json').open('x',encoding='utf-8') as f:json.dump(manifest,f,indent=2);f.flush();os.fsync(f.fileno())
    print(json.dumps({'directory':str(out),'checks':manifest['checks']},indent=2))
if __name__=='__main__':main()


