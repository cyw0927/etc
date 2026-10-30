"""Score v0.5 predictions in a separate append-only ledger; default is read-only preflight."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import sqlite3
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from gmia.config import PROJECT_ROOT
from issue_pit_baseline import load_batch, market_snapshot, market_schedule, utc, MODEL

ROOT = PROJECT_ROOT
FORECASTS = ROOT / 'data/operations/issuance/ledger.sqlite3'
SCORES = ROOT / 'data/operations/issuance/scores.sqlite3'
REGISTRATION = '9b7f609'
# Fields that define a score's result; snapshot identity and fetch times only describe where it came from.
RESULT_FIELDS = ('forecast_run_id','probability','anchor_price','maturity_date','maturity_price','outcome','brier')


def score_one(row, frame, meta, now):
    now = utc(now)
    if row['model'] != MODEL or row['horizon'] not in (5, 20):
        raise ValueError('unsupported prediction protocol')
    origin = pd.Timestamp(row['forecast_date']).normalize()
    schedule = market_schedule(row['asset'], origin.date(), (origin + pd.Timedelta(days=90)).date())
    dates = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    if len(dates) <= row['horizon'] or dates[0] != origin:
        raise ValueError('forecast date or maturity not in market calendar')
    next_open = utc(schedule['market_open'].iloc[1].to_pydatetime())
    if not utc(schedule['market_close'].iloc[0].to_pydatetime()) + timedelta(minutes=15) <= utc(row['issued_utc']) < next_open:
        raise ValueError('forecast was not issued before next open')
    due = dates[row['horizon']]
    completed = utc(schedule['market_close'].iloc[row['horizon']].to_pydatetime()) + timedelta(minutes=15)
    if now < completed:
        return None, f'pending until {completed.isoformat()}'
    if utc(meta['fetched_at_utc']) < completed:
        return None, 'collection began before maturity close plus buffer'
    if utc(meta['ingested_at_utc']) > now:
        raise ValueError('future snapshot ingestion')
    if meta['source'] != 'Yahoo Finance (yfinance)':
        raise ValueError('price provider differs from original protocol')
    expected = dates[:row['horizon']+1]
    observed = frame.loc[(frame.index >= origin) & (frame.index <= due)]
    if not expected.equals(observed.index):
        raise ValueError('missing or extra market session in maturity window')
    px = pd.to_numeric(observed['adj_close'], errors='coerce').to_numpy(float)
    if not np.isfinite(px).all() or (px <= 0).any():
        raise ValueError('invalid price in maturity window')
    anchor = float(row['anchor_price'])
    if not math.isfinite(anchor) or anchor <= 0 or not math.isclose(px[0], anchor, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError('anchor adjusted price revised or invalid; manual review required')
    p = float(row['probability'])
    if not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError('invalid prediction probability')
    outcome = int(px[-1] > anchor)
    return {'asset':row['asset'], 'forecast_date':row['forecast_date'], 'horizon':row['horizon'],
            'model':row['model'], 'forecast_run_id':row['run_id'], 'probability':p,
            'anchor_price':anchor, 'maturity_date':due.strftime('%Y-%m-%d'),
            'maturity_price':float(px[-1]), 'outcome':outcome, 'brier':(p-outcome)**2,
            'snapshot_id':meta['snapshot_id'], 'snapshot_hash':meta['pointer']['manifest_sha256'],
            'fetched_at_utc':meta['fetched_at_utc'], 'ingested_at_utc':meta['ingested_at_utc']}, None


def read_forecasts(path):
    if not path.is_file(): raise FileNotFoundError('original prediction ledger not found')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('forecast ledger failed integrity check')
        return [dict(r) for r in db.execute('SELECT * FROM forecasts WHERE model=? ORDER BY asset,forecast_date,horizon',(MODEL,))]


def scored_keys(path):
    """Keys that already have a first score (read-only); they are not re-scored."""
    if not path.is_file():
        return set()
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='scores'").fetchone():
            return set()
        return {tuple(r) for r in db.execute('SELECT asset,forecast_date,horizon,model FROM scores')}


def save_scores(path, rows, manifest, now):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=30)
    try:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS score_runs(run_id TEXT PRIMARY KEY, scored_at_utc TEXT NOT NULL, manifest_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS scores(asset TEXT NOT NULL, forecast_date TEXT NOT NULL, horizon INTEGER NOT NULL, model TEXT NOT NULL,
            forecast_run_id TEXT NOT NULL, probability REAL NOT NULL, anchor_price REAL NOT NULL, maturity_date TEXT NOT NULL,
            maturity_price REAL NOT NULL, outcome INTEGER NOT NULL CHECK(outcome IN (0,1)), brier REAL NOT NULL,
            snapshot_id TEXT NOT NULL, snapshot_hash TEXT NOT NULL, fetched_at_utc TEXT NOT NULL, ingested_at_utc TEXT NOT NULL,
            score_run_id TEXT NOT NULL, PRIMARY KEY(asset, forecast_date, horizon, model));
          CREATE TRIGGER IF NOT EXISTS score_no_update BEFORE UPDATE ON scores BEGIN SELECT RAISE(ABORT,'append-only'); END;
          CREATE TRIGGER IF NOT EXISTS score_no_delete BEFORE DELETE ON scores BEGIN SELECT RAISE(ABORT,'append-only'); END;
          CREATE TRIGGER IF NOT EXISTS run_no_update BEFORE UPDATE ON score_runs BEGIN SELECT RAISE(ABORT,'append-only'); END;
          CREATE TRIGGER IF NOT EXISTS run_no_delete BEFORE DELETE ON score_runs BEGIN SELECT RAISE(ABORT,'append-only'); END;
        ''')
        db.execute('BEGIN IMMEDIATE')
        # Preregistration 9b7f609: a re-score with different inputs keeps the existing first score and is
        # REPORTED; it must not abort the other, newly matured scores in the same run. A later snapshot
        # (new snapshot_id/hash/fetch time) that reproduces the same result is simply "already scored".
        new_rows, already, conflicts = [], 0, []
        for r in rows:
            old=db.execute(f'SELECT {",".join(RESULT_FIELDS)} FROM scores WHERE asset=? AND forecast_date=? AND horizon=? AND model=?', (r['asset'],r['forecast_date'],r['horizon'],r['model'])).fetchone()
            if old is None:
                new_rows.append(r)
                continue
            changed=[k for k,v in zip(RESULT_FIELDS,old) if v != r[k]]
            if changed:
                conflicts.append({'asset':r['asset'],'forecast_date':r['forecast_date'],'horizon':r['horizon'],
                                  'model':r['model'],'fields':changed,'kept':'existing first score'})
            else:
                already += 1
        run=uuid.uuid4().hex
        db.execute('INSERT INTO score_runs VALUES(?,?,?)',(run,utc(now).isoformat(),json.dumps({**manifest,'conflicts':conflicts},sort_keys=True)))
        before=db.total_changes
        db.executemany('''INSERT INTO scores VALUES(:asset,:forecast_date,:horizon,:model,:forecast_run_id,:probability,:anchor_price,:maturity_date,:maturity_price,:outcome,:brier,:snapshot_id,:snapshot_hash,:fetched_at_utc,:ingested_at_utc,:score_run_id)''',[{**r,'score_run_id':run} for r in new_rows])
        inserted=db.total_changes-before
        db.commit()
        return {'inserted':inserted,'already_scored':already,'conflicts':conflicts,
                'duplicates':len(rows)-inserted,'score_run_id':run}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',required=True)
    p.add_argument('--write',action='store_true')
    args=p.parse_args()
    subprocess.run(['git','merge-base','--is-ancestor',REGISTRATION,'HEAD'],cwd=ROOT,check=True)
    now=datetime.now(timezone.utc)
    batch, info=load_batch(args.batch)
    forecasts=read_forecasts(FORECASTS)
    done=scored_keys(SCORES)
    frames={}; errors={}; rows=[]; pending=[]; blocked=[]; already=0
    for f in forecasts:
        asset=f['asset']
        if (asset,f['forecast_date'],f['horizon'],f['model']) in done:
            already+=1
            continue
        try:
            if asset not in frames: frames[asset]=market_snapshot(batch,info,asset,now)
            result, reason=score_one(f,*frames[asset],now)
            ident={'asset':asset,'forecast_date':f['forecast_date'],'horizon':f['horizon']}
            if result: rows.append(result)
            else: pending.append({**ident,'reason':reason})
        except Exception as exc:
            blocked.append({'asset':asset,'forecast_date':f['forecast_date'],'horizon':f['horizon'],'reason':str(exc)})
    report={'predictions':len(forecasts),'already_scored':already,'ready':len(rows),'pending':pending,'blocked':blocked,'written':False}
    if args.write and rows:
        subprocess.run(['git','ls-files','--error-unmatch','scripts/score_pit_baseline.py','docs/preregistration_v0.5_scoring.md'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=ROOT,check=True)
        manifest={'batch_id':batch.name,'batch_manifest_sha256':hashlib.sha256((batch/'batch_manifest.json').read_bytes()).hexdigest(),
                  'git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  'registration':REGISTRATION,'forecast_ledger':'read-only', 'mode':'first score only',
                  'score_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        report.update(save_scores(SCORES,rows,manifest,now)); report['written']=True
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()


