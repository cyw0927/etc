"""Local manual collection and conservative forward scoring; no scheduling or trading."""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_market_calendars as calendars
import gmia.config as config
from gmia.data.sessions import apply_schedule_overrides

ROOT = config.PROJECT_ROOT
OPS = ROOT / 'data/operations'
BATCHES = OPS / 'collections'
LEDGER = ROOT / 'data/ledger/forward.sqlite3'
CALENDARS = {'SPY':'NYSE','QQQ':'NASDAQ','GOLD':'NYSE','KOSPI':'XKRX','NIKKEI':'JPX'}


def unique(parent):
    path = parent / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_new(path, obj):
    with path.open('x', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        f.flush(); os.fsync(f.fileno())


def aware(s):
    dt = datetime.fromisoformat(s.replace('Z','+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None: raise ValueError('naive timestamp')
    return dt.astimezone(timezone.utc)


def expected_dates(asset, start, end):
    if asset == 'BTC':
        return pd.date_range(start,end,freq='D'), None
    if asset not in CALENDARS:
        raise ValueError('provider-specific session calendar not verified')
    schedule = apply_schedule_overrides(CALENDARS[asset],
                                        calendars.get_calendar(CALENDARS[asset]).schedule(start_date=start, end_date=end))
    if schedule.empty: raise ValueError('empty exchange schedule')
    return pd.DatetimeIndex(schedule.index).tz_localize(None).normalize(), schedule


def latest_completed_missing(asset, px, fetched):
    """Require the latest session completed at fetch time to be present."""
    if asset == 'BTC':
        day=pd.Timestamp(fetched).normalize()
        completed_today=fetched.hour>0 or fetched.minute>=15
        expected=(day-pd.Timedelta(days=1 if completed_today else 2)).tz_localize(None)
    elif asset in CALENDARS:
        schedule=apply_schedule_overrides(CALENDARS[asset],calendars.get_calendar(CALENDARS[asset]).schedule(
            start_date=(fetched-timedelta(days=14)).date(),end_date=(fetched+timedelta(days=1)).date()))
        done=schedule[schedule['market_close']+pd.Timedelta(minutes=15)<=pd.Timestamp(fetched)]
        if done.empty: return 'could not establish latest completed market session'
        expected=pd.Timestamp(done.index[-1]).tz_localize(None).normalize()
    else:
        return 'provider-specific session calendar not verified'
    if expected not in px.index: return f'latest completed session missing: {expected.date()}'
    return None


def validate_window(asset, px, origin, h, recorded, now):
    """Return reason for blocking; None only if a complete, mature window is checkable."""
    if not px.index.is_unique or not px.index.is_monotonic_increasing:
        return 'duplicate or unsorted bars'
    origin = pd.Timestamp(origin).normalize()
    if origin not in px.index: return 'anchor missing'
    pos = int(px.index.get_loc(origin))
    if pos+h >= len(px): return 'not mature in collected data'
    end = px.index[pos+h]
    expected,schedule = expected_dates(asset, origin, end)
    observed = pd.DatetimeIndex(px.index[pos:pos+h+1]).normalize()
    if not expected.equals(observed): return 'missing/extra calendar session in label window'
    values = pd.to_numeric(px.iloc[pos:pos+h+1]['adj_close'],errors='coerce').to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any(): return 'invalid price in label window'
    if asset == 'BTC':
        # UTC candle ends at next midnight. Use +15 min, later than legacy 23:59+15.
        next_end = (origin + pd.Timedelta(days=2,minutes=15)).to_pydatetime().replace(tzinfo=timezone.utc)
        mature_end = (end + pd.Timedelta(days=1,minutes=15)).to_pydatetime().replace(tzinfo=timezone.utc)
    else:
        if len(schedule)<2: return 'missing next session in calendar'
        next_end = (schedule['market_close'].iloc[1] + pd.Timedelta(minutes=15)).to_pydatetime()
        mature_end = (schedule['market_close'].iloc[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    if now < mature_end: return 'market close or buffer not complete'
    # v0.4.2 rule 4: calendar-based timely issuance (in addition to v0.4.1's provider-next-bar rule).
    if aware(recorded) >= next_end: return 'recorded after independent next-session completion'
    return None


def collect():
    batch=unique(BATCHES); config.ARTIFACTS_DIR=batch/'logs'
    from gmia.data.collect import collect_all
    from gmia.data.store import load_series
    cfg=config.load_config(); cfg['data']['raw_dir']=str(batch/'raw')
    # No vintage key is loaded by this command; monthly series remain display-only.
    os.environ.pop('FRED_API_KEY',None)
    summary=collect_all(cfg)
    expected={**{f'market/{k}':batch/'raw/market'/f'{k}.parquet' for k in cfg['assets']},
              **{f'fred/{kind}/{k}':batch/f'raw/fred/{kind}'/f'{k}.parquet' for kind in ('rates','macro') for k in cfg.get(kind,{})}}
    verified={}
    for name,path in expected.items():
        try:
            loaded=load_series(path)
            if loaded is None: raise ValueError('missing')
            frame,meta=loaded
            if frame.empty or meta.get('_integrity')!='sha256_verified': raise ValueError('empty or unverified')
            when=aware(meta['fetched_at_utc'])
            if when < aware(summary['started_utc']) or when > aware(summary['finished_utc']): raise ValueError('fetch time outside batch')
            verified[name]={'pointer':meta['_snapshot'],'fetched_at_utc':meta['fetched_at_utc'],'rows':len(frame),'end':str(frame.index.max())}
        except Exception as e:
            summary['failures'].append({'source':'verification','id':name,'error':str(e)})
    ready=not summary['failures'] and len(verified)==len(expected)
    manifest={'batch_id':batch.name,'ready':ready,'started_utc':summary['started_utc'],
              'finished_utc':summary['finished_utc'],'snapshots':verified,
              'failures':summary['failures'],'calendar_version':version('pandas-market-calendars')}
    write_new(batch/'batch_manifest.json',manifest)
    print(json.dumps({'batch':str(batch),'ready':ready,'verified':len(verified),'expected':len(expected),'failures':summary['failures']},ensure_ascii=False))
    if not ready: raise SystemExit(1)


def score(batch_path):
    batch=Path(batch_path).resolve()
    if not batch.is_relative_to(BATCHES.resolve()) or not (batch/'batch_manifest.json').is_file():
        raise ValueError('Batch must be a completed collection under data/operations/collections')
    manifest=json.loads((batch/'batch_manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('ready') or manifest['batch_id']!=batch.name: raise ValueError('Incomplete batch')
    if not LEDGER.is_file(): raise FileNotFoundError('Existing ledger required; refusing to create one')
    session=unique(OPS/'scores'); config.ARTIFACTS_DIR=session/'logs'
    from gmia.data.market import load_asset
    from gmia.evaluation.backup import backup_ledger
    from gmia.evaluation.forward import ASSETS, score_pending, forward_significance, read_scores
    cfg=config.load_config(); cfg['data']['raw_dir']=str(batch/'raw')
    # docs/preregistration_v0.4.2.md: batch/asset checks hold an asset for this run; label-window and
    # calendar-timeliness checks hold only the failing forecast; scoring uses the validated allow-list.
    prices={}; metas={}; blocked={}; held={}; eligible=set(); now=datetime.now(timezone.utc)
    with sqlite3.connect(LEDGER.as_uri()+'?mode=ro',uri=True) as db:
        pending=db.execute('''SELECT f.asset,f.forecast_date,f.horizon,f.recorded_utc FROM forecasts f
          LEFT JOIN scores s ON s.forecast_date=f.forecast_date AND s.asset=f.asset AND s.horizon=f.horizon AND s.model=f.model
          WHERE s.model IS NULL GROUP BY f.asset,f.forecast_date,f.horizon,f.recorded_utc''').fetchall()
    for asset in ASSETS:
        try:
            expected=manifest['snapshots']['market/'+asset]
            frame, meta=load_asset(str(batch/'raw'),asset)
            if meta['_integrity']!='sha256_verified' or meta['_snapshot']!=expected['pointer']:
                raise ValueError('snapshot pointer/hash mismatch')
            if aware(meta['fetched_at_utc'])>now: raise ValueError('future source timestamp')
            latest_issue=latest_completed_missing(asset,frame,aware(meta['fetched_at_utc']))
            if latest_issue: blocked[asset]=[latest_issue]; continue
            for _,origin,h,recorded in [row for row in pending if row[0]==asset]:
                reason=validate_window(asset,frame,origin,h,recorded,now)
                if reason is None: eligible.add((origin,asset,int(h)))
                elif reason!='not mature in collected data': held.setdefault(asset,[]).append(f'{origin}/{h}: {reason}')
            prices[asset],metas[asset]=frame,meta
        except Exception as e: blocked[asset]=[str(e)]
    backup=backup_ledger(LEDGER,session/'before-scoring.sqlite3')
    intent={'batch_id':batch.name,'batch_manifest':manifest,'backup':backup,'blocked':blocked,'held':held,
            'eligible':sorted([list(k) for k in eligible]),'allowed_assets':sorted(prices),'at_utc':now.isoformat(),
            'note':'v0.4.2: asset held for batch problems, forecast held for window/timeliness problems; FX/WTI held'}
    write_new(session/'preflight.json',intent)
    # Concurrent use of legacy scorer is outside this guard. Only this command must write the ledger.
    lock=OPS/'score.lock'
    lock.mkdir(exist_ok=False)
    try:
        result=score_pending(LEDGER,cfg,prices,metas,now_utc=now,eligible=eligible)
        significant=forward_significance(read_scores(LEDGER))
        significant.to_csv(session/'forward_significance.csv',index=False)
        report={'batch':str(batch),'pre_score_backup':str(session/'before-scoring.sqlite3'),
                'blocked':blocked,'held':held,'allowed_assets':sorted(prices),'results':result,
                'eligible_comparisons':int(significant['enough_data'].sum()),
                'supported_candidates':int(significant['supported'].sum()),'output':str(session)}
        write_new(session/'score_result.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        lock.rmdir()


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('collect'); s=sub.add_parser('score'); s.add_argument('--batch',required=True)
    a=p.parse_args()
    if a.cmd=='collect': collect()
    else: score(a.batch)

if __name__=='__main__': main()
