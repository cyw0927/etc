"""Score release-checked forecasts only, using their isolated ledger."""
import argparse,json,subprocess
from datetime import datetime,timezone
from gmia.config import PROJECT_ROOT
from issue_release_checked import LEDGER,MODEL,REGISTRATION
from issue_pit_baseline import load_batch,market_snapshot
from score_pit_baseline import score_one
from score_macro_forward import pending,save

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--batch',required=True);p.add_argument('--write',action='store_true');a=p.parse_args()
    subprocess.run(['git','merge-base','--is-ancestor',REGISTRATION,'HEAD'],cwd=PROJECT_ROOT,check=True)
    batch,info=load_batch(a.batch);now=datetime.now(timezone.utc);frames={};ready=[];waiting=[];blocked=[]
    for row in pending(LEDGER):
        try:
            if row['model']!=MODEL or row['asset']!='SPY' or row['horizon']!=5:raise ValueError('unsupported forecast')
            if row['asset'] not in frames:frames[row['asset']]=market_snapshot(batch,info,row['asset'],now)
            original={**row,'model':'pit_baseline_v0.5','run_id':row['issued_utc']}
            result,reason=score_one(original,*frames[row['asset']],now)
            if result:result['model']=MODEL;ready.append(result)
            else:waiting.append({'forecast_date':row['forecast_date'],'reason':reason})
        except Exception as e:blocked.append({'forecast_date':row['forecast_date'],'reason':str(e)})
    report={'ready':len(ready),'pending':waiting,'blocked':blocked,'inserted':0}
    if a.write and ready:
        paths=['scripts/score_release_checked.py','scripts/issue_release_checked.py','docs/preregistration_release_checked.md']
        subprocess.run(['git','ls-files','--error-unmatch',*paths],cwd=PROJECT_ROOT,check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=PROJECT_ROOT,check=True)
        report['inserted']=save(LEDGER,ready,{'batch':batch.name,'registration':REGISTRATION,'source_snapshots':{k:v[1] for k,v in frames.items()}},now)
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
