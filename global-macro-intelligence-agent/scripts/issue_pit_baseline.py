"""v0.5: issue the preregistered standalone historical-base-rate forecast only."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from gmia.config import PROJECT_ROOT, asset_specs, load_config
from gmia.data.store import load_series

ROOT=PROJECT_ROOT
COLLECTIONS=ROOT/'data/operations/collections'
LEDGER=ROOT/'data/operations/issuance/ledger.sqlite3'
REGISTRATION='611da8f'
MARKETS={'SPY':'NYSE','QQQ':'NASDAQ','GOLD':'NYSE','KOSPI':'XKRX','NIKKEI':'JPX'}
BLOCKED={'BTC':'provider UTC bar contract is not independently verified; missing 2026-10-27',
         'USDKRW':'Yahoo FX daily close/session contract is not verified',
         'USDJPY':'Yahoo FX daily close/session contract is not verified',
         'WTI':'Yahoo continuous-futures session and roll contract are not verified'}
HORIZONS=(5,20)
MODEL='pit_baseline_v0.5'


def utc(value):
    if isinstance(value,str): value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None or value.utcoffset() is None: raise ValueError('timezone-aware timestamp required')
    return value.astimezone(timezone.utc)


def load_batch(path):
    batch=Path(path).resolve()
    if not batch.is_relative_to(COLLECTIONS.resolve()): raise ValueError('batch outside collections')
    info=json.loads((batch/'batch_manifest.json').read_text(encoding='utf-8'))
    if not info.get('ready') or info.get('batch_id')!=batch.name: raise ValueError('unverified batch')
    if not info.get('finished_utc'): raise ValueError('batch completion time missing')
    return batch,info


def market_snapshot(batch, info, asset, now):
    """Validate exact pointer/content and collection ordering, including post-response ingest."""
    expected=info['snapshots']['market/'+asset]
    path=batch/'raw/market'/f'{asset}.parquet'
    data,meta=load_series(path)
    if meta.get('_integrity')!='sha256_verified' or meta.get('_snapshot')!=expected['pointer']:
        raise ValueError('snapshot pointer or hash mismatch')
    spec=asset_specs(load_config())[asset]
    if meta.get('key')!=asset or meta.get('ticker')!=spec.ticker: raise ValueError('instrument identity mismatch')
    pointer=meta['_snapshot']; manifest_path=path.parent / pointer['manifest']
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    fetched=utc(meta['fetched_at_utc']); ingested=utc(manifest['ingested_at_utc'])
    if not (utc(info['started_utc'])<=fetched<=ingested<utc(info['finished_utc'])+timedelta(seconds=1) and utc(info['finished_utc'])<=utc(now)):
        raise ValueError('invalid collection/ingest time order')
    if not data.index.is_unique or not data.index.is_monotonic_increasing or data.empty:
        raise ValueError('duplicate, unsorted or empty price index')
    if data.index.tz is not None or not (data.index==data.index.normalize()).all():
        raise ValueError('unexpected bar-date representation')
    return data,{'asset':asset,'ticker':spec.ticker,'pointer':pointer,
                 'snapshot_id':manifest['snapshot_id'],'source':meta.get('source'),
                 'fetched_at_utc':fetched.isoformat(),'ingested_at_utc':ingested.isoformat()}


def market_schedule(asset, start, end):
    if asset not in MARKETS: raise ValueError('unverified provider/session contract')
    schedule=mcal.get_calendar(MARKETS[asset]).schedule(start_date=start,end_date=end)
    if schedule.empty: raise ValueError('empty market calendar')
    return schedule


def prepare_asset(asset, frame, meta, decision):
    """Build B1 probabilities from complete exchange sessions, using no external features."""
    now=utc(decision)
    first=frame.index.min().date(); last=frame.index.max().date()
    schedule=market_schedule(asset, first, (now+timedelta(days=14)).date())
    dates=pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    closed=(schedule['market_close']+pd.Timedelta(minutes=15))<=pd.Timestamp(now)
    complete=dates[closed.to_numpy()]
    if len(complete)==0: raise ValueError('no completed exchange session')
    anchor=complete[-1]
    if pd.Timestamp(last)!=anchor: raise ValueError(f'latest completed session is {anchor.date()}, source ends {last}')
    idx=dates.get_loc(anchor)
    if idx+1>=len(dates): raise ValueError('next session unknown')
    close=utc(schedule['market_close'].iloc[idx].to_pydatetime())+timedelta(minutes=15)
    next_open=utc(schedule['market_open'].iloc[idx+1].to_pydatetime())
    if not (close<=utc(meta['fetched_at_utc'])<=utc(meta['ingested_at_utc'])<=now<next_open):
        raise ValueError('publication, ingestion or next-open timing not satisfied')
    hist=dates[:idx+1]
    price=pd.to_numeric(frame['adj_close'].reindex(hist),errors='coerce')
    if not math.isfinite(float(price.iloc[-1])) or float(price.iloc[-1])<=0: raise ValueError('invalid anchor price')
    ok=pd.Series(np.isfinite(price.to_numpy()) & (price.to_numpy()>0),index=hist)
    result=[]
    for h in HORIZONS:
        full=ok.astype(int).rolling(h+1,min_periods=h+1).sum().shift(-h).eq(h+1)
        future=price.shift(-h)
        labels=(future>price).where(full & future.notna()).dropna()
        if len(labels)<252: raise ValueError(f'insufficient valid h={h} label windows: {len(labels)}')
        p=float(np.clip(labels.astype(float).mean(),1e-6,1-1e-6))
        result.append({'asset':asset,'forecast_date':anchor.strftime('%Y-%m-%d'),'horizon':h,
                       'model':MODEL,'probability':p,'n_train':len(labels),'anchor_price':float(price.iloc[-1]),
                       'currency':asset_specs(load_config())[asset].currency,'snapshot_id':meta['snapshot_id'],
                       'snapshot_hash':meta['pointer']['manifest_sha256'],
                       'latest_close_utc':close.isoformat(),'next_open_utc':next_open.isoformat(),
                       'training_end_date':anchor.strftime('%Y-%m-%d')})
    return result


def initialize(db):
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS issuance_runs(run_id TEXT PRIMARY KEY, issued_utc TEXT NOT NULL, manifest_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS forecasts(
      asset TEXT NOT NULL, forecast_date TEXT NOT NULL, horizon INTEGER NOT NULL, model TEXT NOT NULL,
      probability REAL NOT NULL CHECK(probability>=0 AND probability<=1), n_train INTEGER NOT NULL,
      anchor_price REAL NOT NULL, currency TEXT NOT NULL, snapshot_id TEXT NOT NULL, snapshot_hash TEXT NOT NULL,
      issued_utc TEXT NOT NULL, run_id TEXT NOT NULL REFERENCES issuance_runs(run_id),
      PRIMARY KEY(asset,forecast_date,horizon,model));
    CREATE TRIGGER IF NOT EXISTS forecasts_no_update BEFORE UPDATE ON forecasts BEGIN SELECT RAISE(ABORT,'append-only'); END;
    CREATE TRIGGER IF NOT EXISTS forecasts_no_delete BEFORE DELETE ON forecasts BEGIN SELECT RAISE(ABORT,'append-only'); END;
    CREATE TRIGGER IF NOT EXISTS runs_no_update BEFORE UPDATE ON issuance_runs BEGIN SELECT RAISE(ABORT,'append-only'); END;
    CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON issuance_runs BEGIN SELECT RAISE(ABORT,'append-only'); END;
    ''')
    db.commit()


def persist(path, records, manifest, when):
    """Atomically publish all available forecasts plus their run manifest."""
    path.parent.mkdir(parents=True,exist_ok=True)
    run_id=uuid.uuid4().hex
    db=sqlite3.connect(path,timeout=30)
    try:
        initialize(db); db.execute('BEGIN IMMEDIATE')
        for row in records:
            existing=db.execute('SELECT probability,snapshot_hash FROM forecasts WHERE asset=? AND forecast_date=? AND horizon=? AND model=?',
                                (row['asset'],row['forecast_date'],row['horizon'],row['model'])).fetchone()
            if existing and (abs(existing[0]-row['probability'])>1e-12 or existing[1]!=row['snapshot_hash']):
                raise ValueError('forecast key conflict with a different probability or input snapshot')
        db.execute('INSERT INTO issuance_runs VALUES(?,?,?)',(run_id,utc(when).isoformat(),json.dumps(manifest,ensure_ascii=False,sort_keys=True)))
        before=db.total_changes
        db.executemany('''INSERT OR IGNORE INTO forecasts(asset,forecast_date,horizon,model,probability,n_train,anchor_price,currency,snapshot_id,snapshot_hash,issued_utc,run_id)
                        VALUES(:asset,:forecast_date,:horizon,:model,:probability,:n_train,:anchor_price,:currency,:snapshot_id,:snapshot_hash,:issued_utc,:run_id)''',
                       [{**r,'issued_utc':utc(when).isoformat(),'run_id':run_id} for r in records])
        inserted=db.total_changes-before; db.commit()
        return {'run_id':run_id,'attempted':len(records),'inserted':inserted,'duplicates':len(records)-inserted}
    except Exception:
        db.rollback(); raise
    finally: db.close()


def prepare_batch(batch, info, now):
    records=[]; sources={}; blocked=dict(BLOCKED)
    for asset in MARKETS:
        try:
            frame,meta=market_snapshot(batch,info,asset,now)
            result=prepare_asset(asset,frame,meta,now)
            records.extend(result); sources[asset]=meta
        except Exception as exc:
            blocked[asset]=str(exc)
    return records,sources,blocked


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',required=True)
    parser.add_argument('--issue',action='store_true',help='Publish B1-only predictions to the separate v0.5 ledger')
    args=parser.parse_args()
    subprocess.run(['git','merge-base','--is-ancestor',REGISTRATION,'HEAD'],cwd=ROOT,check=True)
    batch,info=load_batch(args.batch)
    now=datetime.now(timezone.utc)
    records,sources,blocked=prepare_batch(batch,info,now)
    report={'mode':'isolated_baseline_only','batch':str(batch),'pre_registration_commit':REGISTRATION,
            'allowed_assets':sorted(sources),'blocked':blocked,'candidate_records':len(records),
            'statistical_evidence':'not established','actual_issuance':False}
    if args.issue:
        # Ensure code and registration are committed and unchanged, even if unrelated user files are untracked.
        tracked=['scripts/issue_pit_baseline.py','src/gmia/data/availability_v05.py','docs/preregistration_v0.5_pit_baseline.md']
        subprocess.run(['git','ls-files','--error-unmatch',*tracked],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=ROOT,check=True)
        if not records: raise RuntimeError('no eligible assets; nothing issued')
        issued=datetime.now(timezone.utc)
        # Training can take time: recheck every timestamp at the actual publication time.
        for row in records:
            if not utc(row['latest_close_utc'])<=utc(sources[row['asset']]['ingested_at_utc'])<=issued<utc(row['next_open_utc']):
                raise ValueError('market boundary changed before issuance')
        manifest={'batch_id':batch.name,'batch_manifest_sha256':hashlib.sha256((batch/'batch_manifest.json').read_bytes()).hexdigest(),
                  'sources':sources,'blocked':blocked,'model':MODEL,'registration':REGISTRATION,
                  'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  'model_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'python':__import__('platform').python_version(),
                  'packages':{p:version(p) for p in ('pandas','numpy','pandas-market-calendars','exchange-calendars')},
                  'usage':'research baseline; no validated predictive edge'}
        report.update(persist(LEDGER,records,manifest,issued)); report['actual_issuance']=True; report['ledger']=str(LEDGER)
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()


