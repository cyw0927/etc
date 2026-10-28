import importlib.util
from pathlib import Path
import pytest
from datetime import date
spec=importlib.util.spec_from_file_location('verify_ecb_eia',Path(__file__).resolve().parents[1]/'scripts'/'verify_ecb_eia.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_cross_rate_and_missing_currency():
    raw=b'Date,USD,JPY,KRW\n2026-01-02,1.25,150,1500\n2026-01-01,1,140,1400\n'
    result=mod.inspect_ecb(raw, date(2026,1,2))
    assert result['latest_usdjpy_reference']==120 and result['latest_usdkrw_reference']==1200
    with pytest.raises(ValueError):mod.inspect_ecb(b'Date,USD,JPY\n2026-01-02,1,150\n')
    with pytest.raises(RuntimeError):mod.inspect_ecb(raw.replace(b'2026-01-02',b'2026-01-03'),date(2026,1,3))
    with pytest.raises(ValueError):mod.inspect_ecb(raw,date(2026,2,2))



def test_eia_identity_negative_price_and_duplicates(monkeypatch):
    class Sheet:
        nrows=5
        def cell_value(self,r,c):
            data={(1,1):'RWTC',(2,1):'WTI Spot',(3,0):46023.,(3,1):-37.63,(4,0):46024.,(4,1):5.}
            return data[(r,c)]
    class Book:
        datemode=0
        def sheet_by_name(self,name): return Sheet()
    monkeypatch.setattr(mod.xlrd,'open_workbook',lambda **k:Book())
    result=mod.inspect_eia(b'placeholder',date(2026,1,3))
    assert result['valid_rows']==2
