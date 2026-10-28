from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('probe_coinbase_btc', Path(__file__).resolve().parents[1] / 'scripts' / 'probe_coinbase_btc.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def candle(day):
    t=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())
    return [t,90,110,100,105,4]

def test_btc_utc_gap_incomplete_and_order():
    now=datetime(2026,10,28,0,5,tzinfo=timezone.utc)
    rows=[candle('2026-10-25'),candle('2026-10-26'),candle('2026-10-27')]
    assert [b['date_utc'] for b in mod.parse_daily(rows,now,2)]==['2026-10-25','2026-10-26']
    now=datetime(2026,10,28,0,15,tzinfo=timezone.utc)
    assert [b['date_utc'] for b in mod.parse_daily(rows,now,2)]==['2026-10-26','2026-10-27']
    with pytest.raises(ValueError): mod.parse_daily([rows[0],rows[2]],now,2)
    with pytest.raises(ValueError): mod.parse_daily(rows+[rows[0]],now,2)
    with pytest.raises(ValueError): mod.parse_daily([dict()],now,2)
