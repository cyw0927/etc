from datetime import date
from decimal import Decimal
import importlib.util,io,sys,zipfile
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
spec=importlib.util.spec_from_file_location('official_fx_wti',Path(__file__).resolve().parents[1]/'scripts'/'verify_official_fx_wti.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_ecb_three_official_feeds_match():
    raw=b'Date,USD,JPY,KRW\n2026-10-27,1.115,175.97,1480.44\n'
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('eurofxref-hist.csv',raw)
    sdmx=b'CURRENCY,TIME_PERIOD,CURRENCY_DENOM,EXR_TYPE,OBS_VALUE\nUSD,2026-10-27,EUR,SP00,1.115\nJPY,2026-10-27,EUR,SP00,175.97\nKRW,2026-10-27,EUR,SP00,1480.44\n'
    xml=b'<root><day time="2026-10-27"><x currency="USD" rate="1.1150"/><x currency="JPY" rate="175.97"/><x currency="KRW" rate="1480.44"/></day></root>'
    assert m.compare_ecb(out.getvalue(),sdmx,xml,date(2026,10,28))['three_currencies_match']
    with pytest.raises(ValueError):m.compare_ecb(out.getvalue(),sdmx,xml.replace(b'175.97',b'175.00'),date(2026,10,28))
