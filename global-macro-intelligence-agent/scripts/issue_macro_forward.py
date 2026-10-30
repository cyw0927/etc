"""Preregistered SPY macro forward prediction; isolated ledger, local manual execution only."""
import argparse,hashlib,json,math,sqlite3,subprocess,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
from gmia.config import PROJECT_ROOT
from alfred_research_features import load_revisions,SERIES,ROOT as RESEARCH
from issue_pit_baseline import load_batch,market_schedule,market_snapshot,prepare_asset,utc

REGISTRATION='81a1d50'
ALIGNMENT='c5e0f06'  # docs/preregistration_macro_alignment.md: inputs use the training decision time
INPUT_CUTOFF_DEFINITION='anchor NYSE session close + 15 min, then ALFRED date <= that UTC date - 2 days (same as training)'
MODEL_HASH='b08139784b0881dc2147584ed873bbb417326a231c78f2623addf28e0b1e568c'
MODEL_NAME='macro_lag2d_fixed_v1'
LEDGER=PROJECT_ROOT/'data/operations/macro_forward/ledger.sqlite3'

def load_model(path):
    path=Path(path).resolve()
    if not path.is_relative_to(RESEARCH.resolve()):raise ValueError('model outside research directory')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MODEL_HASH:raise ValueError('model hash differs from preregistration')
    d=json.loads(raw); keys=[s+'_lag2d' for s in SERIES]
    if d['report']['features']!=keys or not d['report']['model_trained'] or d['report']['forecasts_issued']!=0:raise ValueError('wrong research model')
    p=d['parameters']
    if any(len(p[k])!=4 for k in ('mean','scale','coefficients')) or len(p['intercept'])!=1:raise ValueError('invalid model dimensions')
    if not all(math.isfinite(float(v)) for k in ('mean','scale','coefficients','intercept') for v in p[k]) or min(p['scale'])<=0:raise ValueError('invalid model parameters')
    return d

def snapshot_timing(manifest,decision):
    decision=utc(decision);times=[]
    for x in manifest['sources']:
        start=utc(x['request_started_utc']);end=utc(x['response_received_utc'])
        if end<start:raise ValueError('source collection time inversion')
        times.append((start,end))
    for x in manifest['series'].values():
        start=utc(x['requested_utc']);end=utc(x['received_utc'])
        if end<start:raise ValueError('form collection time inversion')
        times.append((start,end))
    if not times or min(t[0] for t in times)<decision-timedelta(hours=36) or max(t[1] for t in times)>decision:
        raise ValueError('macro snapshot too old or not yet received')
    return {'earliest_request_utc':min(t[0] for t in times).isoformat(),'last_receipt_utc':max(t[1] for t in times).isoformat()}

def live_features(events, decision):
    cutoff=(utc(decision)-timedelta(days=2)).date().isoformat();values=[]; evidence={}
    for sid in SERIES:
        rows=[r for r in events[sid] if r['realtime_start_date']<=cutoff and r['observation_date']<=cutoff and (r['realtime_end_date'] is None or cutoff<=r['realtime_end_date'])]
        if not rows:raise ValueError('missing point-in-time feature: '+sid)
        obs=max(r['observation_date'] for r in rows); latest=[r for r in rows if r['observation_date']==obs]
        if len(latest)!=1:raise ValueError('ambiguous feature revision')
        row=latest[0];value=float(row['value'])
        if not math.isfinite(value):raise ValueError('invalid feature')
        values.append(value);evidence[sid]={'observation_date':obs,'value':value,'realtime_start_date':row['realtime_start_date'],'realtime_end_date':row['realtime_end_date'],
                                       'exact_release_time':'unknown','eligibility':'ALFRED date plus conservative two-day lag'}
    return values,evidence

def anchor_decision(forecast_date):
    """Training decision time for an anchor session: NYSE close + 15 minutes (train_alfred_research.py)."""
    sched=market_schedule('SPY',forecast_date,forecast_date)
    if len(sched)!=1:raise ValueError('forecast date is not a NYSE session')
    return utc(sched['market_close'].iloc[0].to_pydatetime())+timedelta(minutes=15)

def input_features(events, forecast_date):
    """Macro inputs for an anchor, independent of the wall-clock issue time (alignment c5e0f06)."""
    decision=anchor_decision(forecast_date)
    values,evidence=live_features(events,decision)
    return values,evidence,decision

def predict(model, values):
    if len(values)!=4:raise ValueError('incorrect feature count')
    p=model['parameters'];z=sum(((v-a)/b)*c for v,a,b,c in zip(values,p['mean'],p['scale'],p['coefficients']))+p['intercept'][0]
    if not math.isfinite(z):raise ValueError('non-finite model output')
    probability=1/(1+math.exp(-min(700,max(-700,z))))
    return min(1-1e-6,max(1e-6,probability))

def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS forecasts(asset TEXT NOT NULL, forecast_date TEXT NOT NULL, horizon INTEGER NOT NULL,
       model TEXT NOT NULL, probability REAL NOT NULL, anchor_price REAL NOT NULL, issued_utc TEXT NOT NULL,
       input_hash TEXT NOT NULL, manifest_json TEXT NOT NULL, PRIMARY KEY(asset,forecast_date,horizon,model));
      CREATE TABLE IF NOT EXISTS scores(asset TEXT NOT NULL, forecast_date TEXT NOT NULL, horizon INTEGER NOT NULL, model TEXT NOT NULL,
       maturity_date TEXT NOT NULL, maturity_price REAL NOT NULL, outcome INTEGER NOT NULL, brier REAL NOT NULL,
       snapshot_hash TEXT NOT NULL, scored_utc TEXT NOT NULL, details_json TEXT NOT NULL, PRIMARY KEY(asset,forecast_date,horizon,model));
      CREATE TRIGGER IF NOT EXISTS forecasts_no_update BEFORE UPDATE ON forecasts BEGIN SELECT RAISE(ABORT,'append-only'); END;
      CREATE TRIGGER IF NOT EXISTS forecasts_no_delete BEFORE DELETE ON forecasts BEGIN SELECT RAISE(ABORT,'append-only'); END;
      CREATE TRIGGER IF NOT EXISTS scores_no_update BEFORE UPDATE ON scores BEGIN SELECT RAISE(ABORT,'append-only'); END;
      CREATE TRIGGER IF NOT EXISTS scores_no_delete BEFORE DELETE ON scores BEGIN SELECT RAISE(ABORT,'append-only'); END;''');db.commit()

def insert_forecast(path,row,manifest,next_open,decision_date):
    path.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(path,timeout=30)
    try:
        initialize(db);db.execute('BEGIN IMMEDIATE');issued=datetime.now(timezone.utc)
        if issued.date()!=decision_date:raise ValueError('UTC date changed before commit')
        if issued>=utc(next_open):raise ValueError('next market opened before commit')
        if issued-utc(manifest['collection']['earliest_request_utc'])>timedelta(hours=36):raise ValueError('macro snapshot expired before commit')
        prior=db.execute('SELECT probability,anchor_price,input_hash FROM forecasts WHERE asset=? AND forecast_date=? AND horizon=? AND model=?',(row['asset'],row['forecast_date'],row['horizon'],row['model'])).fetchone()
        if prior:
            if prior!=(row['probability'],row['anchor_price'],row['input_hash']):raise ValueError('existing forecast differs; no overwrite')
            db.rollback();return {'inserted':0,'duplicate':1}
        db.execute('INSERT INTO forecasts VALUES(?,?,?,?,?,?,?,?,?)',(row['asset'],row['forecast_date'],row['horizon'],row['model'],row['probability'],row['anchor_price'],issued.isoformat(),row['input_hash'],json.dumps(manifest,sort_keys=True)))
        db.commit();return {'inserted':1,'duplicate':0,'issued_utc':issued.isoformat()}
    except Exception:db.rollback();raise
    finally:db.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',required=True);p.add_argument('--vintages',required=True);p.add_argument('--price-batch',required=True);p.add_argument('--issue',action='store_true');a=p.parse_args()
    for commit in (REGISTRATION,ALIGNMENT):subprocess.run(['git','merge-base','--is-ancestor',commit,'HEAD'],cwd=PROJECT_ROOT,check=True)
    model=load_model(a.model);folder=Path(a.vintages).resolve();events,source=load_revisions(folder);batch,info=load_batch(a.price_batch)
    now=datetime.now(timezone.utc);meta_timing=snapshot_timing(source,now)
    if utc(model['trained_utc'])>now:raise ValueError('model training is in the future')
    frame,meta=market_snapshot(batch,info,'SPY',now);base=prepare_asset('SPY',frame,meta,now)[0]
    if base['horizon']!=5:raise ValueError('incorrect horizon')
    # A training label must have matured by this snapshot's anchor.
    sched=market_schedule('SPY',model['report']['to'],base['forecast_date'])
    if len(sched)<6:raise ValueError('training label not mature by forecast anchor')
    values,evidence,input_decision=input_features(events,base['forecast_date']);prob=predict(model,values)
    manifest={'model_hash':MODEL_HASH,'model_trained_utc':model['trained_utc'],'training_end':model['report']['to'],
              'input_decision_utc':input_decision.isoformat(),'input_cutoff_definition':INPUT_CUTOFF_DEFINITION,'alignment':ALIGNMENT,
              'macro_manifest_hash':hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),'macro_snapshot':folder.name,
              'collection':meta_timing,'features':evidence,'price_source':meta,'price_batch':batch.name,
              'registration':REGISTRATION,'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip(),
              'release_time_warning':'exact intraday release unknown; retrospective daily vintage and two-day lag are research assumptions'}
    fingerprint=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    row={'asset':'SPY','forecast_date':base['forecast_date'],'horizon':5,'model':MODEL_NAME,'probability':prob,'anchor_price':base['anchor_price'],'input_hash':fingerprint}
    report={'mode':'research_macro_forward','forecast_date':row['forecast_date'],'model':MODEL_NAME,'issued':False,'probability':prob,'warning':manifest['release_time_warning']}
    if a.issue:
        paths=['scripts/issue_macro_forward.py','scripts/alfred_research_features.py','scripts/collect_alfred_web.py','docs/preregistration_macro_forward.md','docs/preregistration_macro_alignment.md']
        subprocess.run(['git','ls-files','--error-unmatch',*paths],cwd=PROJECT_ROOT,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=PROJECT_ROOT,check=True)
        # Inputs no longer depend on the wall clock; re-check them and the collection window at commit time.
        final=datetime.now(timezone.utc);snapshot_timing(source,final)
        if input_features(events,base['forecast_date'])[1]!=evidence:raise ValueError('vintage inputs changed; repeat preflight')
        report.update(insert_forecast(LEDGER,row,manifest,base['next_open_utc'],final.date()));report['issued']=bool(report['inserted']);report['ledger']=str(LEDGER)
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()

