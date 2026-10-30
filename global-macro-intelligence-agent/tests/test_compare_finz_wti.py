import importlib.util
import json
import hashlib
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("compare_finz_wti", Path(__file__).parents[1] / "scripts" / "compare_finz_wti.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def snapshot(path, time, price):
    path.mkdir()
    raw = json.dumps({"count": 1, "data": [{"root": "CL", "date": "2026-10-27",
                      "contract": "CLZ26", "close": price, "status": "final"}]}).encode()
    (path / "continuous.json").write_bytes(raw)
    meta = {"source": "FinzData", "responses": {"continuous": {"received_utc": time,
            "sha256": hashlib.sha256(raw).hexdigest(), "params": {"adjust": "none"}}}}
    (path / "manifest.json").write_text(json.dumps(meta))
    return path


def test_detect_change_without_claiming_exact_revision_time(tmp_path):
    a = snapshot(tmp_path / "a", "2026-10-29T03:00:00+00:00", 70)
    b = snapshot(tmp_path / "b", "2026-10-29T04:00:00+00:00", 71)
    assert mod.compare(a, b)["changed_days"] == [{"date": "2026-10-27", "fields": ["close"]}]
    with pytest.raises(ValueError, match="ordered"):
        mod.compare(b, a)
    (a / "continuous.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        mod.compare(a, b)
