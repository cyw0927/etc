import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("collect_finz_wti", Path(__file__).parents[1] / "scripts" / "collect_finz_wti.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(day, contract, close=70):
    return {"root": "CL", "date": day, "contract": contract, "close": close}


def test_continuous_records_observed_contract_switch():
    payload = {"count": 2, "data": [row("2026-10-12", "CLX26"), row("2026-10-13", "CLZ26")]}
    result = module.validate(payload, "continuous")
    assert result["observed_switches"] == [{"date": "2026-10-13", "from": "CLX26", "to": "CLZ26"}]


def test_rejects_duplicate_and_incomplete_data():
    r = row("2026-10-12", "CLX26")
    with pytest.raises(ValueError):
        module.validate({"count": 2, "data": [r, r]}, "individual")
    with pytest.raises(ValueError):
        module.validate({"count": 2, "data": [r]}, "individual")
    with pytest.raises(ValueError):
        module.validate({"count": 1, "data": [row("2026-10-12", "CLX26", float("nan"))]}, "individual")


def test_negative_oil_price_is_valid():
    result = module.validate({"count": 1, "data": [row("2020-04-20", "CLK20", -37.63)]}, "individual")
    assert result["rows"] == 1
