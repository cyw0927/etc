"""Synthetic fixtures only: crashes, corruption, revisions and availability boundaries."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import pytest

from gmia.data import store
from gmia.data.pit import Availability
from gmia.evaluation.backup import backup_ledger
from gmia.evaluation.forward import append_forecasts, db_session, read_forecasts, read_scores, score_pending
from gmia.config import load_config


def utc(day):
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def frame(value=100.0):
    return pd.DataFrame({"adj_close": [value, value + 1]}, index=pd.date_range("2020-01-01", periods=2))


def test_snapshot_revision_is_pinned_and_roundtrips(tmp_path):
    path = tmp_path / "SPY.parquet"
    store.save_series(frame(), {"source": "synthetic test"}, path)
    original, meta = store.load_series(path)
    store.save_series(frame(200), {"source": "synthetic test revision"}, path)
    pd.testing.assert_frame_equal(store.load_snapshot(path, meta["_snapshot"])[0], original)
    pd.testing.assert_frame_equal(store.load_series(path)[0], frame(200), check_freq=False)
    assert meta["_integrity"] == "sha256_verified"
    assert len(list((tmp_path / "_snapshots" / "SPY").iterdir())) == 2


@pytest.mark.parametrize("filename", ["series.parquet", "meta.json", "manifest.json"])
def test_corruption_fails_closed_even_with_legacy_file(tmp_path, filename):
    path = tmp_path / "SPY.parquet"
    frame().to_parquet(path)
    store.save_series(frame(), {}, path)
    pointer = json.loads(path.with_suffix(".snapshot.json").read_text())
    target = (tmp_path / pointer["manifest"]).parent / filename
    target.write_bytes(b"corrupt")
    with pytest.raises(store.SnapshotIntegrityError):
        store.load_series(path)


def test_crash_before_publish_preserves_current_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "SPY.parquet"
    store.save_series(frame(), {}, path)
    def crash(*args):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(store.os, "replace", crash)
    with pytest.raises(OSError, match="publication failure"):
        store.save_series(frame(200), {}, path)
    pd.testing.assert_frame_equal(store.load_series(path)[0], frame(), check_freq=False)


def test_concurrent_writers_publish_only_complete_snapshots(tmp_path):
    path = tmp_path / "SPY.parquet"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: store.save_series(frame(n), {"value": n}, path), range(100, 108)))
    df, meta = store.load_series(path)
    assert df["adj_close"].iloc[0] == meta["value"]


def test_legacy_is_explicit_and_pointer_traversal_rejected(tmp_path):
    path = tmp_path / "SPY.parquet"
    frame().to_parquet(path)
    assert store.load_series(path)[1]["_integrity"] == "legacy_unverified"
    with pytest.raises(store.SnapshotIntegrityError, match="unsafe"):
        store.load_snapshot(path, {"schema_version": 1, "manifest": "../manifest.json"})
    path.with_suffix(".snapshot.json").write_text("invalid json")
    with pytest.raises(store.SnapshotIntegrityError):
        store.load_series(path)


def test_availability_release_ingest_and_revision_boundaries():
    release = utc("2026-01-02T13:00:00")
    ingest = utc("2026-01-03T13:00:00")
    point = Availability(release, ingest, "exact_release")
    assert not point.eligible(release)
    assert point.eligible(release, live_replay=False)
    assert point.eligible(ingest)
    revision = Availability(utc("2026-02-02T13:00:00"), ingest, "exact_release")
    assert not revision.eligible(ingest, live_replay=False)
    for evidence in ("conservative_lag", "unknown"):
        assert not Availability(release, ingest, evidence).eligible(ingest)
    assert not Availability(None, ingest, "unknown").eligible(ingest)
    with pytest.raises(ValueError, match="timezone"):
        Availability(datetime(2026, 1, 1), ingest, "exact_release")


def test_ledger_mutations_blocked_backup_restores_first_rows(tmp_path):
    cfg = load_config()
    dates = pd.bdate_range("2026-10-01", periods=8)
    px = pd.DataFrame({"adj_close": range(100, 108)}, index=dates)
    path = tmp_path / "forward.sqlite3"
    fc = {"target": "SPY", "horizon": 5, "forecast_date": "2026-10-01",
          "p_up_all_models": {"baseline_base_rate": 0.55}}
    append_forecasts(path, [fc], {"SPY": px}, cfg, "r", "sha", utc("2026-10-02T01:00:00"))
    future = score_pending(path, cfg, {"SPY": px},
                           {"SPY": {"fetched_at_utc": "2026-12-01T00:00:00+00:00"}},
                           now_utc=utc("2026-11-01T00:00:00"))
    assert future["invalid"] == 1 and read_scores(path).empty
    score_pending(path, cfg, {"SPY": px},
                  {"SPY": {"fetched_at_utc": "2026-11-01T00:00:00+00:00"}},
                  now_utc=utc("2026-11-01T00:00:00"))
    for table in ("forecasts", "scores"):
        for statement in (f"DELETE FROM {table}", f"UPDATE {table} SET asset='QQQ'"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"), db_session(path) as db:
                db.execute(statement)
    backup = tmp_path / "backup.sqlite3"
    assert backup_ledger(path, backup)["rows"] == {"forecasts": 1, "scores": 1}
    pd.testing.assert_frame_equal(read_forecasts(path), read_forecasts(backup))
    pd.testing.assert_frame_equal(read_scores(path), read_scores(backup))
    with pytest.raises(FileExistsError):
        backup_ledger(path, backup)
    with pytest.raises(FileExistsError):
        backup_ledger(path, path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"), db_session(backup) as db:
        db.execute("DELETE FROM scores")
