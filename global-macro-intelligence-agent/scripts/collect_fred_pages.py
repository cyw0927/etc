"""Capture FRED pages with reported latest value and update time, in an isolated snapshot."""
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib,json,os,uuid
import requests
from gmia.config import PROJECT_ROOT

UTC=timezone.utc
SERIES=('CPIAUCSL','UNRATE','INDPRO','M2SL')
ROOT=PROJECT_ROOT/'data/operations/source_research'
class Page(HTMLParser):
    def __init__(self):super().__init__();self.coed=[];self.stack=[];self.parts={'series-meta-observation-value':[],'series-meta-updated-date':[],'series-meta-updated-time':[]}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs);classes=a.get('class','').split()
        if tag not in ('input','meta','link','br','hr','img','source','area','wbr'):
            markers=[c for c in classes if c in self.parts]
            if tag=='a' and '/releases/calendar' in a.get('href',''):markers.append('__release_link')
            self.stack.append([tag,markers])
        if tag=='input' and a.get('id')=='coed':self.coed.append(a.get('value'))
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:self.stack=self.stack[:i];break
    def handle_data(self,data):
        inside_release=any('__release_link' in classes for _,classes in self.stack)
        for _,classes in self.stack:
            for c in classes:
                if c in self.parts and not (inside_release and c=='series-meta-updated-date'):self.parts[c].append(data.strip())

def one(items):
    values={x for x in items if x}
    if len(values)!=1:raise ValueError('missing or inconsistent FRED metadata')
    return values.pop()

def parse(raw):
    p=Page();p.feed(raw.decode('utf-8'))
    observation=one(p.coed);datetime.strptime(observation,'%Y-%m-%d')
    val=float(one(p.parts['series-meta-observation-value']).replace(',',''))
    ds=one(p.parts['series-meta-updated-date']); ts=one(p.parts['series-meta-updated-time'])
    clock,zone=ts.rsplit(' ',1)
    if zone not in ('CST','CDT'):raise ValueError('unexpected FRED time zone')
    local=datetime.strptime(ds+' '+clock,'%b %d, %Y %I:%M %p').replace(tzinfo=ZoneInfo('America/Chicago'))
    if local.tzname()!=zone:raise ValueError('FRED DST abbreviation mismatch')
    return {'observation_date':observation,'value':val,'fred_updated_minute_utc':local.astimezone(UTC).isoformat(),
            'fred_updated_precision':'minute; latest series update, not individual first publication'}

def main():
    now=datetime.now(UTC);folder=ROOT/('fred-pages-'+now.strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:10]);folder.mkdir(parents=True,exist_ok=False)
    manifest={'series':{},'errors':[]}
    for sid in SERIES:
        started=datetime.now(UTC);url='https://fred.stlouisfed.org/series/'+sid
        try:
            r=requests.get(url,timeout=25);r.raise_for_status();received=datetime.now(UTC); parsed=parse(r.content)
            file=sid+'.html'
            with (folder/file).open('xb') as f:f.write(r.content);f.flush();os.fsync(f.fileno())
            manifest['series'][sid]={'url':url,'file':file,'sha256':hashlib.sha256(r.content).hexdigest(),'request_started_utc':started.isoformat(),'received_utc':received.isoformat(),**parsed}
        except (requests.RequestException,ValueError,UnicodeError) as e:manifest['errors'].append({'series':sid,'error':str(e)})
    manifest['ready']=not manifest['errors'] and set(manifest['series'])==set(SERIES)
    with (folder/'manifest.json').open('x',encoding='utf-8') as f:json.dump(manifest,f,indent=2);f.flush();os.fsync(f.fileno())
    print(json.dumps({'directory':str(folder),'ready':manifest['ready'],'series':manifest['series'],'errors':manifest['errors']},indent=2))
    if not manifest['ready']:raise SystemExit(1)
if __name__=='__main__':main()


