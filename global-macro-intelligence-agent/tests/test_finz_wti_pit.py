import hashlib
import json
import pytest
from gmia.features.finz_wti_pit import features_at


def snapshot(tmp_path, rows, received="2026-10-29T03:27:00+00:00"):
    tmp_path.mkdir(exist_ok=True)
    raw = json.dumps({"count": len(rows), "data": rows}).encode()
    (tmp_path / "continuous.json").write_bytes(raw)
    (tmp_path / "individual.json").write_bytes(raw)
    manifest = {"source": "FinzData", "model_use": False, "responses": {"continuous": {
        "received_utc": received, "sha256": hashlib.sha256(raw).hexdigest(), "params": {"adjust": "none"}},
        "individual": {"received_utc": received, "sha256": hashlib.sha256(raw).hexdigest()}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


def row(day, contract="CLZ26", status="final", close=70.0):
    return {"root": "CL", "date": day, "contract": contract, "status": status, "close": close}


def test_observed_time_controls_access(tmp_path):
    p = snapshot(tmp_path, [row("2026-10-26"), row("2026-10-27", close=77)])
    with pytest.raises(ValueError, match="no snapshot"):
        features_at([p], "2026-10-29T03:26:59+00:00")
    assert features_at([p], "2026-10-29T03:27:00+00:00")["wti_same_contract_return"] == pytest.approx(.1)


def test_final_and_roll_gate(tmp_path):
    p = snapshot(tmp_path, [row("2026-10-26"), row("2026-10-27", status="preliminary")])
    with pytest.raises(ValueError, match="not final"):
        features_at([p], "2026-10-30T00:00:00+00:00")
    p = snapshot(tmp_path, [row("2026-10-26", "CLX26"), row("2026-10-27", "CLZ26")])
    with pytest.raises(ValueError, match="contract change"):
        features_at([p], "2026-10-30T00:00:00+00:00")


def test_reject_tampering_and_naive_time(tmp_path):
    p = snapshot(tmp_path, [row("2026-10-26"), row("2026-10-27")])
    with pytest.raises(ValueError, match="timezone"):
        features_at([p], "2026-10-30T00:00:00")
    (p / "continuous.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        features_at([p], "2026-10-30T00:00:00+00:00")


def test_missing_weekday_and_stale_snapshot_are_blocked(tmp_path):
    p = snapshot(tmp_path, [row("2026-10-23"), row("2026-10-27")])
    with pytest.raises(ValueError, match="missing session"):
        features_at([p], "2026-10-29T03:27:00+00:00")
    p = snapshot(tmp_path, [row("2026-10-26"), row("2026-10-27")])
    with pytest.raises(ValueError, match="stale"):
        features_at([p], "2026-11-05T00:00:00+00:00")


def test_individual_contract_disagreement_blocked(tmp_path):
    p = snapshot(tmp_path, [row("2026-10-26"), row("2026-10-27")])
    data = json.loads((p / "individual.json").read_text())
    data["data"][1]["close"] = 99
    raw = json.dumps(data).encode()
    (p / "individual.json").write_bytes(raw)
    manifest = json.loads((p / "manifest.json").read_text())
    manifest["responses"]["individual"]["sha256"] = hashlib.sha256(raw).hexdigest()
    (p / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="disagree"):
        features_at([p], "2026-10-29T03:27:00+00:00")
