from datetime import date
import importlib.util,io,zipfile
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('alfred_web',Path(__file__).resolve().parents[1]/'scripts'/'collect_alfred_web.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_form_select_and_preceding_vintage():
    h='<input id="form_obs_start_date" value="2000-01-01"><input id="form_obs_end_date" value="2020-01-01"><select id="form_selected_vintage_dates"><option value="2004-12-01"></option><option value="2005-01-02"></option></select>'
    _,v=mod.selected_dates(h);assert v==[date(2004,12,1),date(2005,1,2)]
    with pytest.raises(ValueError):mod.selected_dates(h.replace('2005-01-02','bad'))

def test_archive_schema_and_periods():
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z: z.writestr('data.csv','period_start_date,CPIAUCSL,realtime_start_date,realtime_end_date\n2005-01-01,100.2,2005-02-01,2005-02-20\n2005-02-01,,2005-03-01,2005-03-20\n')
    assert mod.parse_zip(b.getvalue(),'CPIAUCSL')[0]['value']==100.2
    with pytest.raises(ValueError):mod.parse_zip(b.getvalue(),'UNRATE')

