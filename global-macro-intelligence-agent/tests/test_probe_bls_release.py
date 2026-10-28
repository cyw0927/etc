from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('probe_bls_release', Path(__file__).resolve().parents[1]/'scripts'/'probe_bls_release.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

def test_exact_cpi_embargo_and_dst():
    raw=b'<html>Transmission of material in this release is embargoed until 8:30 a.m. (ET) Wednesday, October 14, 2026 USDL-26-1574 <p>CONSUMER PRICE INDEX - SEPTEMBER 2026</p></html>'
    parsed=mod.parse_release(raw)
    assert parsed['observation_month']=='2026-09-01'
    assert parsed['embargo_end_utc']=='2026-10-14T12:30:00+00:00'
    with pytest.raises(ValueError): mod.parse_release(raw.replace(b'Wednesday',b'Thursday'))
    with pytest.raises(ValueError): mod.parse_release(raw.replace(b'(ET)',b'(UTC)'))
