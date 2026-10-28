"""Extract BLS CPI embargo time and reference month from an archived release, not values/vintages."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
import re
from zoneinfo import ZoneInfo
import requests

URL='https://www.bls.gov/news.release/archives/cpi_10142026.htm'
class Text(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]
    def handle_data(self, data): self.parts.append(data)

def parse_release(raw):
    p=Text(); p.feed(raw.decode('utf-8')); s=' '.join(' '.join(p.parts).split())
    pattern=r'Transmission of material in this release is embargoed until\s+(\d{1,2}:\d{2})\s+([ap])\.m\.\s+\(ET\)\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+ \d{1,2}, \d{4})'
    matches=list(re.finditer(pattern,s,re.I))
    if len(matches)!=1: raise ValueError('unique BLS embargo timestamp not found')
    m=matches[0]; local=datetime.strptime(m.group(4)+' '+m.group(1)+' '+m.group(2).upper()+'M','%B %d, %Y %I:%M %p')
    if local.strftime('%A').lower()!=m.group(3).lower(): raise ValueError('release weekday mismatch')
    references=re.findall(r'CONSUMER PRICE INDEX\s*-\s*([A-Z]+)\s+(\d{4})',s)
    if len(set(references))!=1: raise ValueError('unique CPI reference month not found')
    month,year=references[0]
    observation=datetime.strptime(month+' '+year,'%B %Y').date().isoformat()
    return {'observation_month':observation,'embargo_end_utc':local.replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc).isoformat(),
            'interpretation':'earliest permitted release, not evidence of actual publication or later revision'}

def main():
    started=datetime.now(timezone.utc)
    response=requests.get(URL,timeout=20,allow_redirects=False,headers={'User-Agent':'GMIA research release metadata checker contact unavailable'})
    response.raise_for_status()
    if response.status_code != 200: raise ValueError('unexpected redirect or status')
    finished=datetime.now(timezone.utc)
    result=parse_release(response.content)
    result.update({'url':URL,'request_start_utc':started.isoformat(),'received_utc':finished.isoformat(),
                   'source_sha256':hashlib.sha256(response.content).hexdigest(),'mode':'read-only release evidence probe; no historical PIT claim'})
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
