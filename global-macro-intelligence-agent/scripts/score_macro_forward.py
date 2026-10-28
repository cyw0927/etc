"""Score mature macro forward predictions; writes only the isolated macro ledger with --write."""
import argparse,json,sqlite3,subprocess
from datetime import datetime,timezone
from pathlib import Path
from gmia.config import PROJECT_ROOT
from issue_pit_baseline import load_batch,market_snapshot
from issue_macro_forward import LEDGER,REGISTRATION,MODEL_NAME
from score_pit_baseline import score_one

def pending(path):
    if not path.is_file():raise FileNotFoundError('macro forward ledger not found')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        if db.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('ledger integrity failure')
        return [dict(r) for r in db.execute('''SELECT f.* FROM forecasts f LEFT JOIN scores s
          ON f.asset=s.asset AND f.forecast_date=s.forecast_date AND f.horizon=s.horizon AND f.model=s.model
          WHERE s.model IS NULL ORDER BY f.forecast_date''')]

def score_candidate(row,frame,meta,now):
    if row['model']!=MODEL_NAME or row['asset']!='SPY' or row['horizon']!=5:raise ValueError('unsupported forward model')
    # Use the preregistered v0.5 five-session label validator; never write to its ledger.
    original={**row,'model':'pit_baseline_v0.5','run_id':row['issued_utc']}
    scored,reason=score_one(original,frame,meta,now)
    if scored is not None:scored['model']=MODEL_NAME
    return scored,reason

def save(path,rows,details,now):
    db=sqlite3.connect(path,timeout=30)
    try:
        db.execute('BEGIN IMMEDIATE');inserted=0
        for row in rows:
            f=db.execute('SELECT probability,anchor_price,issued_utc FROM forecasts WHERE asset=? AND forecast_date=? AND horizon=? AND model=?',(row['asset'],row['forecast_date'],row['horizon'],row['model'])).fetchone()
            if f is None or f!=(row['probability'],row['anchor_price'],row['forecast_run_id']):raise ValueError('prediction changed during scoring')
            old=db.execute('SELECT maturity_date,maturity_price,outcome,brier,snapshot_hash FROM scores WHERE asset=? AND forecast_date=? AND horizon=? AND model=?',(row['asset'],row['forecast_date'],row['horizon'],row['model'])).fetchone()
            value=(row['maturity_date'],row['maturity_price'],row['outcome'],row['brier'],row['snapshot_hash'])
            if old:
                if old!=value:raise ValueError('first score differs; refusing overwrite')
                continue
            db.execute('INSERT INTO scores VALUES(?,?,?,?,?,?,?,?,?,?,?)',(row['asset'],row['forecast_date'],row['horizon'],row['model'],*value,now.isoformat(),json.dumps(details,sort_keys=True)));inserted+=1
        db.commit();return inserted
    except Exception:db.rollback();raise
    finally:db.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True);p.add_argument('--write',action='store_true');a=p.parse_args()
    subprocess.run(['git','merge-base','--is-ancestor',REGISTRATION,'HEAD'],cwd=PROJECT_ROOT,check=True)
    now=datetime.now(timezone.utc); batch,info=load_batch(a.batch);frames={};ready=[];waiting=[];blocked=[]
    for row in pending(LEDGER):
        try:
            if row['asset'] not in frames:frames[row['asset']]=market_snapshot(batch,info,row['asset'],now)
            result,reason=score_candidate(row,*frames[row['asset']],now)
            if result:ready.append(result)
            else:waiting.append({'forecast_date':row['forecast_date'],'reason':reason})
        except Exception as e:blocked.append({'forecast_date':row['forecast_date'],'reason':str(e)})
    report={'ready':len(ready),'pending':waiting,'blocked':blocked,'inserted':0}
    if a.write and ready:
        paths=['scripts/score_macro_forward.py','scripts/issue_macro_forward.py','docs/preregistration_macro_forward.md']
        subprocess.run(['git','ls-files','--error-unmatch',*paths],cwd=PROJECT_ROOT,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=PROJECT_ROOT,check=True)
        details={'batch':batch.name,'registration':REGISTRATION,'source_snapshots':{k:v[1] for k,v in frames.items()},'note':'first descriptive Brier score only; no inference'}
        report['inserted']=save(LEDGER,ready,details,now)
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
