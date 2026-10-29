"""Issue a separate forecast only when fixed official release evidence and FRED pages agree."""
import argparse,hashlib,json,subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from gmia.config import PROJECT_ROOT
from alfred_research_features import load_revisions,ROOT as RESEARCH
from collect_fred_pages import parse,SERIES
from issue_macro_forward import load_model,snapshot_timing,live_features,predict,insert_forecast,MODEL_HASH
from issue_pit_baseline import load_batch,market_snapshot,market_schedule,prepare_asset,utc
REGISTRATION='c726a91'
MODEL='macro_release_checked_v1'
LEDGER=PROJECT_ROOT/'data/operations/macro_release_forward/ledger.sqlite3'
# Official initial release/embargo or scheduled time. This is NOT ALFRED's exact vintage publication time.
EVENTS={
 'CPIAUCSL':('2026-10-14','08:30','embargo_until','https://www.bls.gov/news.release/archives/cpi_10142026.htm'),
 'UNRATE':('2026-10-02','08:30','embargo_until','https://www.bls.gov/news.release/archives/empsit_10022026.htm'),
 'INDPRO':('2026-10-16','09:15','release_statement','https://www.federalreserve.gov/releases/g17/20261016/g17.pdf'),
 'M2SL':('2026-10-27','13:00','scheduled','https://www.federalreserve.gov/newsevents/2026-october.htm')}

def compare_evidence(folder,feature_rows,decision):
    folder=Path(folder).resolve();decision=utc(decision)
    if not folder.is_relative_to(RESEARCH.resolve()):raise ValueError('FRED snapshot outside research root')
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('ready') or manifest.get('errors') or set(manifest.get('series',{}))!=set(SERIES):raise ValueError('incomplete FRED pages')
    result={}
    for sid in SERIES:
        item=manifest['series'][sid]; path=(folder/item['file']).resolve()
        if not path.is_relative_to(folder) or item['url']!='https://fred.stlouisfed.org/series/'+sid:raise ValueError('wrong FRED source identity')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('FRED page hash mismatch')
        actual=parse(raw)
        if any(actual[k]!=item[k] for k in actual):raise ValueError('FRED metadata mismatch')
        start=utc(item['request_started_utc']);received=utc(item['received_utc']);updated=utc(actual['fred_updated_minute_utc'])
        day,clock,kind,url=EVENTS[sid]
        release=datetime.fromisoformat(day+'T'+clock).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
        row=feature_rows[sid]
        if row['observation_date']!='2026-09-01' or actual['observation_date']!=row['observation_date'] or actual['value']!=row['value'] or row['realtime_start_date']!=day:
            raise ValueError('official release identity, FRED value or ALFRED revision does not match: '+sid)
        if updated.date().isoformat()!=day or not (release<=updated and updated+timedelta(minutes=1)<=start<=received<=decision):
            raise ValueError('unverified publication/update/collection order: '+sid)
        if decision-start>timedelta(minutes=15):raise ValueError('FRED page too old: '+sid)
        result[sid]={'official_release_reference_utc':release.isoformat(),'official_release_type':kind,'official_release_url':url,
          'fred_last_update_minute_utc':updated.isoformat(),'fred_update_precision':'minute; latest series update, not exact value publication',
          'fred_page_sha256':item['sha256'],'fred_request_started_utc':start.isoformat(),'fred_received_utc':received.isoformat(),
          'observation_date':row['observation_date'],'value':row['value'],'alfred_revision_date':row['realtime_start_date']}
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('model','vintages','fred-pages','price-batch'):p.add_argument('--'+key,required=True)
    p.add_argument('--issue',action='store_true');a=p.parse_args()
    subprocess.run(['git','merge-base','--is-ancestor',REGISTRATION,'HEAD'],cwd=PROJECT_ROOT,check=True)
    model=load_model(a.model);folder=Path(a.vintages).resolve();events,source=load_revisions(folder);batch,info=load_batch(a.price_batch)
    now=datetime.now(timezone.utc); collection=snapshot_timing(source,now)
    if utc(model['trained_utc'])>now:raise ValueError('model training time in future')
    frame,meta=market_snapshot(batch,info,'SPY',now);base=prepare_asset('SPY',frame,meta,now)[0]
    if len(market_schedule('SPY',model['report']['to'],base['forecast_date']))<6:raise ValueError('training label not mature')
    values,rows=live_features(events,now);checked=compare_evidence(a.fred_pages,rows,now);prob=predict(model,values)
    fred=Path(a.fred_pages).resolve()
    manifest={'model_hash':MODEL_HASH,'model_trained_utc':model['trained_utc'],'training_end':model['report']['to'],
      'alfred_snapshot':folder.name,'alfred_manifest_sha256':hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
      'fred_snapshot':fred.name,'fred_manifest_sha256':hashlib.sha256((fred/'manifest.json').read_bytes()).hexdigest(),
      'fred_and_release_evidence':checked,'alfred_collection':collection,'features':rows,'price_source':meta,'price_batch':batch.name,
      'price_batch_manifest_sha256':hashlib.sha256((batch/'batch_manifest.json').read_bytes()).hexdigest(),
      'registration':REGISTRATION,'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip(),
      'limitations':'release reference is embargo or schedule, FRED is latest series update, no exact historical ALFRED vintage publication proven'}
    input_hash=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    row={'asset':'SPY','forecast_date':base['forecast_date'],'horizon':5,'model':MODEL,'probability':prob,'anchor_price':base['anchor_price'],'input_hash':input_hash}
    report={'forecast_date':row['forecast_date'],'model':MODEL,'probability':prob,'issued':False,'official_and_fred_checks':len(checked)}
    if a.issue:
        paths=['scripts/issue_release_checked.py','scripts/collect_fred_pages.py','docs/preregistration_release_checked.md']
        subprocess.run(['git','ls-files','--error-unmatch',*paths],cwd=PROJECT_ROOT,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=PROJECT_ROOT,check=True)
        final=datetime.now(timezone.utc);snapshot_timing(source,final)
        if live_features(events,final)[1]!=rows or compare_evidence(fred,rows,final)!=checked:raise ValueError('evidence changed during issue')
        manifest['collection']={'earliest_request_utc':min(utc(collection['earliest_request_utc']),*(utc(x['fred_request_started_utc']) for x in checked.values())).isoformat()}
        # Input hash is recomputed after the final collection gate is attached.
        row['input_hash']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        report.update(insert_forecast(LEDGER,row,manifest,base['next_open_utc'],final.date()));report['issued']=bool(report['inserted']);report['ledger']=str(LEDGER)
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()

