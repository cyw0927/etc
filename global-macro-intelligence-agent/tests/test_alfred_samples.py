import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('collect_alfred_samples',Path(__file__).resolve().parents[1]/'scripts'/'collect_alfred_samples.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def test_identity_missing_duplicate_and_finite():
    data=b'observation_date,CPIAUCSL_20200301\n2020-01-01,257.971\n2020-02-01,.\n'
    assert mod.parse(data,'CPIAUCSL','2020-03-01')=={'2020-01-01':257.971}
    with pytest.raises(ValueError):mod.parse(data,'UNRATE','2020-03-01')
    with pytest.raises(ValueError):mod.parse(data+b'2020-01-01,1\n','CPIAUCSL','2020-03-01')
    with pytest.raises(ValueError):mod.parse(data.replace(b'257.971',b'NaN'),'CPIAUCSL','2020-03-01')
