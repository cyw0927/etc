"""Train preregistered retrospective ALFRED/SPY research model, never issue a forecast."""
import argparse,hashlib,json,math,os,subprocess,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from gmia.config import PROJECT_ROOT
from gmia.models.registry import CompleteCaseLogit
from issue_pit_baseline import load_batch,market_snapshot,market_schedule,utc
from alfred_research_features import load_revisions,historical_features,SERIES,ROOT as RESEARCH

REGISTRATION='6aa1723'

def train_input(frame,meta,revisions,now):
    now=utc(now)
    if frame.empty or not frame.index.is_unique or not frame.index.is_monotonic_increasing:raise ValueError('invalid price index')
    schedule=market_schedule('SPY',frame.index.min().date(),frame.index.max().date())
    days=pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    if len(frame.index.difference(days)):raise ValueError('unexpected non-exchange bar')
    if days[-1]!=frame.index.max():raise ValueError('last price not an exchange session')
    anchor_close=utc(schedule['market_close'].iloc[-1].to_pydatetime())+timedelta(minutes=15)
    if not anchor_close<=utc(meta['fetched_at_utc'])<=utc(meta['ingested_at_utc'])<=now:raise ValueError('invalid snapshot chronology')
    close=pd.to_numeric(frame['adj_close'].reindex(days),errors='coerce')
    valid=pd.Series(np.isfinite(close.to_numpy()) & (close.to_numpy()>0),index=days)
    h=5
    full=valid.astype(int).rolling(h+1,min_periods=h+1).sum().shift(-h).eq(h+1)
    labels=(close.shift(-h)>close).where(full & close.shift(-h).notna())
    decisions=pd.DatetimeIndex(schedule['market_close']+pd.Timedelta(minutes=15))
    features=historical_features(revisions,decisions);features.index=days
    eligible=labels.notna() & features.notna().all(axis=1)
    eligible &= days>=pd.Timestamp('2005-01-01')
    X=features.loc[eligible];y=labels.loc[eligible].astype(int)
    if len(y)<252 or y.nunique()!=2:raise ValueError('insufficient complete classes or observations')
    return X,y

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--vintages',required=True);parser.add_argument('--price-batch',required=True);parser.add_argument('--train',action='store_true');a=parser.parse_args()
    subprocess.run(['git','merge-base','--is-ancestor',REGISTRATION,'HEAD'],cwd=PROJECT_ROOT,check=True)
    now=datetime.now(timezone.utc);folder=Path(a.vintages).resolve(); revisions,source=load_revisions(folder)
    if any(utc(x['response_received_utc'])>now for x in source['sources']):raise ValueError('future source ingestion')
    batch,info=load_batch(a.price_batch);frame,meta=market_snapshot(batch,info,'SPY',now)
    X,y=train_input(frame,meta,revisions,now)
    report={'mode':'retrospective_research_training_only','rows':len(y),'from':str(y.index.min().date()),'to':str(y.index.max().date()),'features':list(X.columns),'model_trained':False,'forecasts_issued':0,'performance_evaluated':False}
    if a.train:
        paths=['scripts/train_alfred_research.py','scripts/alfred_research_features.py','scripts/collect_alfred_web.py','docs/preregistration_macro_research_training.md']
        subprocess.run(['git','ls-files','--error-unmatch',*paths],cwd=PROJECT_ROOT,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=PROJECT_ROOT,check=True)
        model=CompleteCaseLogit('research_macro_lag2d',list(X.columns),C=1.0).fit(X,y)
        if model.pipe_ is None:raise ValueError('model failed to train')
        scaler=model.pipe_.named_steps['standardscaler'];reg=model.pipe_.named_steps['logisticregression']
        result={'report':{**report,'model_trained':True},'parameters':{'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'coefficients':reg.coef_[0].tolist(),'intercept':reg.intercept_.tolist()},
                'source_manifest_sha256':hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
                'price_snapshot':meta,'price_batch':batch.name,'price_batch_manifest_sha256':hashlib.sha256((batch/'batch_manifest.json').read_bytes()).hexdigest(),'registration':REGISTRATION,
                'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip(),
                'trained_utc':datetime.now(timezone.utc).isoformat(),
                'limitations':'date-level lag assumption; historical ingestion unverified; price vintage reconstructed; no performance evaluation; not an issuing model'}
        out=RESEARCH/('macro-training-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-')+uuid.uuid4().hex[:10]);out.mkdir(parents=True,exist_ok=False)
        with (out/'model.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        report.update({'model_trained':True,'output':str(out),'model_sha256':hashlib.sha256((out/'model.json').read_bytes()).hexdigest()})
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()

