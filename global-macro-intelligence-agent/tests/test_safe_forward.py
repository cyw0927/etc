"""Synthetic checks of conservative forward-window eligibility; no live data."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('safe_forward',Path(__file__).resolve().parents[1]/'scripts/safe_forward.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def frame(dates):
    return pd.DataFrame({'adj_close':[100.0+i for i in range(len(dates))]},index=pd.DatetimeIndex(dates))


def test_btc_missing_day_blocks_scoring():
    dates=pd.to_datetime(['2026-10-26','2026-10-28','2026-10-29','2026-10-30','2026-10-31','2026-11-01'])
    result=module.validate_window('BTC',frame(dates),'2026-10-26',5,'2026-10-28T05:35:00+00:00',datetime(2026,11,5,tzinfo=timezone.utc))
    assert 'missing/extra' in result


def test_exchange_window_requires_complete_sessions_and_timely_issue():
    dates=pd.bdate_range('2026-10-26',periods=6)
    px=frame(dates); now=datetime(2026,11,10,tzinfo=timezone.utc)
    assert module.validate_window('SPY',px,'2026-10-26',5,'2026-10-27T19:00:00+00:00',now) is None
    assert 'recorded after' in module.validate_window('SPY',px,'2026-10-26',5,'2026-10-27T21:00:00+00:00',now)
    px.iloc[2,0]=float('nan')
    assert 'invalid price' in module.validate_window('SPY',px,'2026-10-26',5,'2026-10-27T19:00:00+00:00',now)


def test_unsupported_vendor_calendar_never_silently_accepted():
    px=frame(pd.bdate_range('2026-10-26',periods=6))
    with pytest.raises(ValueError,match='not verified'):
        module.validate_window('WTI',px,'2026-10-26',5,'2026-10-27T00:00:00+00:00',datetime(2026,11,10,tzinfo=timezone.utc))


def test_full_safe_scoring_backups_and_skips_unsupported_asset(tmp_path, monkeypatch):
    import json
    import sqlite3
    from datetime import timedelta
    from gmia.config import load_config
    from gmia.data.store import load_series, save_series
    from gmia.evaluation.forward import append_forecasts

    ops=tmp_path/'operations'; batches=ops/'collections'; batch=batches/'test-batch'; raw=batch/'raw'
    raw.mkdir(parents=True)
    ledger=tmp_path/'ledger.sqlite3'
    monkeypatch.setattr(module,'OPS',ops)
    monkeypatch.setattr(module,'BATCHES',batches)
    monkeypatch.setattr(module,'LEDGER',ledger)
    px=frame(pd.bdate_range('2026-10-01',periods=6))
    fetched='2026-10-09T19:00:00+00:00'  # after Oct 8 close, before Oct 9 close
    snapshots={}
    for asset in ('SPY','WTI'):
        path=raw/'market'/f'{asset}.parquet'
        save_series(px,{'source':'synthetic test','fetched_at_utc':fetched},path)
        snapshots['market/'+asset]={'pointer':load_series(path)[1]['_snapshot']}
    (batch/'batch_manifest.json').write_text(json.dumps({'batch_id':batch.name,'ready':True,'snapshots':snapshots}),encoding='utf-8')
    forecasts=[{'target':asset,'forecast_date':'2026-10-01','horizon':5,
                'p_up_all_models':{'baseline_base_rate':0.5}} for asset in ('SPY','WTI')]
    append_forecasts(ledger,forecasts,{'SPY':px,'WTI':px},load_config(),'synthetic','sha',
                     datetime(2026,10,2,1,tzinfo=timezone.utc))
    module.score(str(batch))
    with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('select count(*) from forecasts').fetchone()[0]==2
        assert db.execute('select asset from scores').fetchall()==[('SPY',)]
        first=db.execute('select * from scores').fetchall()
    score_dir=next((ops/'scores').iterdir())
    report=json.loads((score_dir/'score_result.json').read_text(encoding='utf-8'))
    assert report['results']['scored']==1 and 'WTI' in report['blocked']
    with sqlite3.connect((score_dir/'before-scoring.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('select count(*) from forecasts').fetchone()[0]==2
        assert db.execute('select count(*) from scores').fetchone()[0]==0
    module.score(str(batch))
    with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('select * from scores').fetchall()==first


def test_btc_latest_completed_candle_detects_missing_even_before_maturity():
    px=frame(pd.to_datetime(['2026-10-25','2026-10-26']))
    before=datetime(2026,10,28,0,14,tzinfo=timezone.utc)
    after=datetime(2026,10,28,0,15,tzinfo=timezone.utc)
    assert module.latest_completed_missing('BTC',px,before) is None
    assert '2026-10-27' in module.latest_completed_missing('BTC',px,after)


# v0.4.2 (docs/preregistration_v0.4.2.md): per-forecast holds and the validated allow-list
def _btc_batch(tmp_path, monkeypatch, days, fetched):
    import json
    from gmia.data.store import load_series, save_series
    ops=tmp_path/'operations'; batches=ops/'collections'; batch=batches/'btc-batch'; raw=batch/'raw'
    raw.mkdir(parents=True)
    ledger=tmp_path/'ledger.sqlite3'
    monkeypatch.setattr(module,'OPS',ops); monkeypatch.setattr(module,'BATCHES',batches); monkeypatch.setattr(module,'LEDGER',ledger)
    px=frame(days)
    path=raw/'market'/'BTC.parquet'
    save_series(px,{'source':'synthetic test','fetched_at_utc':fetched},path)
    (batch/'batch_manifest.json').write_text(json.dumps({'batch_id':batch.name,'ready':True,
        'snapshots':{'market/BTC':{'pointer':load_series(path)[1]['_snapshot']}}}),encoding='utf-8')
    return ops,batch,ledger,px


def test_btc_gap_holds_only_the_affected_forecast(tmp_path, monkeypatch):
    import json
    import sqlite3
    from gmia.config import load_config
    from gmia.evaluation.forward import append_forecasts
    days=pd.date_range('2026-10-01','2026-10-19',freq='D').drop(pd.Timestamp('2026-10-12'))
    ops,batch,ledger,px=_btc_batch(tmp_path,monkeypatch,days,'2026-10-20T01:00:00+00:00')
    for date,recorded in (('2026-10-02','2026-10-03T01:00:00+00:00'),('2026-10-09','2026-10-10T01:00:00+00:00')):
        append_forecasts(ledger,[{'target':'BTC','forecast_date':date,'horizon':5,'p_up_all_models':{'baseline_base_rate':0.5}}],
                         {'BTC':px},load_config(),'synthetic','sha',datetime.fromisoformat(recorded))
    module.score(str(batch))
    with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('select forecast_date from scores').fetchall()==[('2026-10-02',)]
    report=json.loads((next((ops/'scores').iterdir())/'score_result.json').read_text(encoding='utf-8'))
    assert 'BTC' not in report['blocked'] and report['allowed_assets']==['BTC']
    assert any(item.startswith('2026-10-09/5') for item in report['held']['BTC'])
    assert report['results']['held']==1 and report['results']['scored']==1


def test_score_pending_only_scores_the_validated_allow_list(tmp_path):
    from gmia.config import load_config
    from gmia.evaluation.forward import append_forecasts, read_scores, score_pending
    cfg=load_config(); ledger=tmp_path/'ledger.sqlite3'
    px=frame(pd.bdate_range('2026-10-01',periods=12))
    for date in ('2026-10-01','2026-10-02'):
        append_forecasts(ledger,[{'target':'SPY','forecast_date':date,'horizon':5,'p_up_all_models':{'baseline_base_rate':0.5}}],
                         {'SPY':px},cfg,'r','sha',datetime(2026,10,2,20,30,tzinfo=timezone.utc) if date=='2026-10-02'
                         else datetime(2026,10,2,1,tzinfo=timezone.utc))
    source={'SPY':{'fetched_at_utc':'2026-11-15T00:00:00+00:00'}}
    now=datetime(2026,11,15,tzinfo=timezone.utc)
    out=score_pending(ledger,cfg,{'SPY':px},source,now_utc=now,eligible={('2026-10-01','SPY',5)})
    assert out['scored']==1 and out['held']==1
    assert read_scores(ledger)['forecast_date'].tolist()==['2026-10-01']
    # without an allow-list the v0.4/v0.4.1 behaviour is unchanged
    assert score_pending(ledger,cfg,{'SPY':px},source,now_utc=now)['scored']==1


def test_stale_batch_holds_the_whole_asset_for_this_run(tmp_path, monkeypatch):
    import json
    days=pd.date_range('2026-10-01','2026-10-18',freq='D')  # 10-19 should exist at this fetch time
    ops,batch,ledger,px=_btc_batch(tmp_path,monkeypatch,days,'2026-10-20T01:00:00+00:00')
    from gmia.config import load_config
    from gmia.evaluation.forward import append_forecasts
    append_forecasts(ledger,[{'target':'BTC','forecast_date':'2026-10-02','horizon':5,'p_up_all_models':{'baseline_base_rate':0.5}}],
                     {'BTC':px},load_config(),'synthetic','sha',datetime(2026,10,3,1,tzinfo=timezone.utc))
    module.score(str(batch))
    report=json.loads((next((ops/'scores').iterdir())/'score_result.json').read_text(encoding='utf-8'))
    assert 'latest completed session missing' in report['blocked']['BTC'][0]
    assert report['results']['scored']==0
