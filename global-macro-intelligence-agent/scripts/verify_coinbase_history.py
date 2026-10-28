"""Recheck stored Coinbase response hashes, boundaries, and normalized candles."""
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from collect_coinbase_history import normalize, windows, RESEARCH

def verify(folder):
    folder=Path(folder).resolve()
    if not folder.is_relative_to(RESEARCH.resolve()): raise ValueError('snapshot outside research directory')
    m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if m['provider']!='Coinbase Exchange' or m['instrument']!='BTC-USD': raise ValueError('wrong instrument')
    expected_windows={(s.isoformat(),e.isoformat()) for s,e in windows(datetime.fromisoformat(m['first_requested_utc']),datetime.fromisoformat(m['last_complete_boundary_utc']))}
    recorded=[(c['start'],c['end']) for c in m['chunks']+m['failures']]
    if len(recorded)!=len(set(recorded)) or set(recorded)!=expected_windows: raise ValueError('missing or overlapping requested window')
    rebuilt={}
    for c in m['chunks']:
        path=(folder/c['file']).resolve()
        if not path.is_relative_to(folder): raise ValueError('unsafe chunk path')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=c['sha256']: raise ValueError('chunk hash mismatch')
        rows=normalize(json.loads(raw),datetime.fromisoformat(c['start']),datetime.fromisoformat(c['end']))
        if len(rows)!=c['rows'] or rebuilt.keys() & rows.keys(): raise ValueError('duplicate or wrong chunk count')
        rebuilt.update(rows)
    normalized=(folder/'candles.json').read_bytes()
    if hashlib.sha256(normalized).hexdigest()!=m['normalized_sha256']: raise ValueError('normalized hash mismatch')
    data=json.loads(normalized); expected=[]
    for t,v in sorted(rebuilt.items()):
        expected.append({'date_utc':datetime.fromtimestamp(t,timezone.utc).date().isoformat(),'low':v[0],'high':v[1],'open':v[2],'close':v[3],'volume':v[4]})
    if data!=expected: raise ValueError('normalized content differs from raw candles')
    timestamps=sorted(rebuilt)
    missing=[t for t in range(timestamps[0],timestamps[-1]+1,86400) if t not in rebuilt] if timestamps else []
    ready=bool(timestamps and not missing and not m['failures'] and expected[-1]['date_utc']==m['latest_expected_day'])
    if ready!=m['ready'] or len(missing)!=len(m['missing_internal_days']): raise ValueError('quality manifest mismatch')
    return {'chunks_checked':len(m['chunks']),'candles_checked':len(data),'missing_days':len(missing),'ready':ready}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder');a=p.parse_args();print(json.dumps(verify(a.folder),indent=2))
if __name__=='__main__':main()

