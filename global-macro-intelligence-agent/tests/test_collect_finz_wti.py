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


class _Response:
    def __init__(self, payload, status=200):
        import json
        self.payload, self.status_code, self.content = payload, status, json.dumps(payload).encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self.payload


def _fake_api(fail_on=None):
    daily = {"count": 2, "data": [row("2026-10-27", "CLZ26", 70.0), row("2026-10-28", "CLZ26", 71.0)]}
    replies = {"/v1/futures/contracts": {"count": 1, "data": [{"contract": "CLZ26"}]}, "/v1/futures/daily": daily}

    def get(url, params=None, headers=None, timeout=None):
        assert headers == {"X-API-Key": "test-key"}
        path = url.replace(module.BASE, "")
        if fail_on and params.get("continuous") == fail_on:
            return _Response({"error": "rate limited"}, status=429)
        return _Response(replies[path])
    return get


def test_snapshot_is_published_only_after_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("FINZDATA_API_KEY", "test-key")
    monkeypatch.setattr(module.requests, "get", _fake_api())
    module.main()
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 1 and names[0].startswith("finz-wti-") and not names[0].endswith(".partial")
    assert sorted(p.name for p in (tmp_path / names[0]).iterdir()) == ["continuous.json", "contracts.json", "individual.json", "manifest.json"]
    assert names[0] in capsys.readouterr().out


def test_interrupted_run_leaves_no_complete_looking_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("FINZDATA_API_KEY", "test-key")
    monkeypatch.setattr(module.requests, "get", _fake_api(fail_on="true"))  # continuous request gets 429
    with pytest.raises(SystemExit):
        module.main()
    assert not list(tmp_path.glob("finz-wti-*"))
    partial = list(tmp_path.glob(".finz-wti-*.partial"))
    assert len(partial) == 1 and [p.name for p in partial[0].iterdir()] == ["contracts.json"]
    err = capsys.readouterr().err
    assert '"http_status": 429' in err and "test-key" not in err


def test_data_project_override_moves_snapshot_root(monkeypatch, tmp_path):
    import importlib
    monkeypatch.setenv("GMIA_DATA_PROJECT", str(tmp_path))
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    assert fresh.ROOT == tmp_path / "data" / "operations" / "source_research"
