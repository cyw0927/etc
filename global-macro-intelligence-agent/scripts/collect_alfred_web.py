"""Download ALFRED web-form vintage periods without an API key, into a fresh research snapshot."""
from __future__ import annotations
import csv, hashlib, io, json, os, re, uuid, zipfile
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import requests
from gmia.config import PROJECT_ROOT

UTC=timezone.utc
BASE='https://alfred.stlouisfed.org/series/downloaddata'
ROOT=PROJECT_ROOT/'data/operations/source_research'
SERIES=('CPIAUCSL','UNRATE','INDPRO','M2SL')
START=date(2005,1,1)

class Form(HTMLParser):
    def __init__(self): super().__init__(); self.active=False; self.dates=[]; self.fields={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='select' and a.get('id')=='form_selected_vintage_dates': self.active=True
        if tag=='option' and self.active:
            value=a.get('value','')
            try: self.dates.append(date.fromisoformat(value))
            except ValueError: raise ValueError('invalid vintage option')
        if tag=='input' and a.get('id') in ('form_obs_start_date','form_obs_end_date'):
            self.fields[a['id']]=a.get('value','')
    def handle_endtag(self,tag):
        if tag=='select' and self.active: self.active=False

def selected_dates(html, start=START):
    form=Form();form.feed(html)
    if not form.dates or form.dates!=sorted(set(form.dates)) or len(form.fields)!=2: raise ValueError('incomplete or unordered vintage form')
    previous=[x for x in form.dates if x<start]
    dates=([previous[-1]] if previous else [])+[x for x in form.dates if x>=start]
    return form,dates

def parse_zip(raw,sid):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=[x for x in z.namelist() if x!='README.txt' and x.endswith('.csv')]
        if len(names)!=1 or z.getinfo(names[0]).file_size>100_000_000: raise ValueError('unexpected vintage archive')
        reader=csv.DictReader(io.StringIO(z.read(names[0]).decode('utf-8-sig')))
        if reader.fieldnames!=['period_start_date',sid,'realtime_start_date','realtime_end_date']: raise ValueError('unexpected vintage columns')
        records=[]
        for r in reader:
            obs=date.fromisoformat(r['period_start_date']); start=date.fromisoformat(r['realtime_start_date'])
            end=None if r['realtime_end_date'] in ('','.','9999-12-31') else date.fromisoformat(r['realtime_end_date'])
            if end is not None and end<start: raise ValueError('invalid vintage interval')
            if r[sid] in ('','.'): continue
            val=float(r[sid])
            if not __import__('math').isfinite(val): raise ValueError('invalid value')
            records.append({'series':sid,'observation_date':obs.isoformat(),'value':val,'realtime_start_date':start.isoformat(),'realtime_end_date':end.isoformat() if end else None})
        if not records: raise ValueError('empty vintage response')
        return records

def write_new(path,data):
    with path.open('xb') as f: f.write(data);f.flush();os.fsync(f.fileno())

def collect(out,session=None):
    out.mkdir(parents=True,exist_ok=False); session=session or requests.Session(); manifest={'sources':[],'failures':[],'series':{}}
    for sid in SERIES:
        url=BASE+'?seid='+sid
        try:
            begin=datetime.now(UTC);page=session.get(url,timeout=40);page.raise_for_status();form,dates=selected_dates(page.text)
            if not dates: raise ValueError('no vintages for requested period')
            page_name=sid+'-form.html';write_new(out/page_name,page.content)
            form_meta={'file':page_name,'sha256':hashlib.sha256(page.content).hexdigest(),'requested_utc':begin.isoformat(),'received_utc':datetime.now(UTC).isoformat(),'vintage_dates':[d.isoformat() for d in dates]}
            for offset in range(0,len(dates),100):
                group=dates[offset:offset+100]
                data=[('form[units]','lin'),('form[obs_start_date]',START.isoformat()),('form[obs_end_date]',form.fields['form_obs_end_date'])]
                data += [('form[selected_vintage_dates][]',d.isoformat()) for d in group]
                data += [('form[entered_vintage_dates]',''),('form[file_type]','1'),('form[file_format]','csv'),('form[download_data]','')]
                t=datetime.now(UTC);response=session.post(url,data=data,timeout=90);response.raise_for_status(); received=datetime.now(UTC)
                parsed=parse_zip(response.content,sid)
                name=f'{sid}-{offset//100:03d}.zip';write_new(out/name,response.content)
                manifest['sources'].append({'series':sid,'file':name,'sha256':hashlib.sha256(response.content).hexdigest(),
                    'vintage_dates':[d.isoformat() for d in group],'request_started_utc':t.isoformat(),'response_received_utc':received.isoformat(),'rows':len(parsed)})
            manifest['series'][sid]=form_meta
        except (requests.RequestException,ValueError,zipfile.BadZipFile,KeyError) as e:
            manifest['failures'].append({'series':sid,'error':str(e)})
    manifest['ready']=not manifest['failures'] and len(manifest['series'])==len(SERIES)
    manifest['note']='date-level historical revisions; downloads made now; not intraday release or proof of historical ingestion'
    write_new(out/'manifest.json',json.dumps(manifest,indent=2).encode())
    return manifest

def main():
    now=datetime.now(UTC);out=ROOT/('alfred-web-vintages-'+now.strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:10]);m=collect(out)
    print(json.dumps({'directory':str(out),'ready':m['ready'],'archive_count':len(m['sources']),'series':{k:len(v['vintage_dates']) for k,v in m['series'].items()},'failures':m['failures']},indent=2))
    if not m['ready']: raise SystemExit(1)
if __name__=='__main__': main()

