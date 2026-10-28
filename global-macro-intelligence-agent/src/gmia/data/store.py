"""Immutable snapshots with an atomic current pointer; legacy files remain readable.

Hashes detect accidental changes, not a writer able to replace manifests.
Ingest time alone does not establish historical publication time.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class SnapshotIntegrityError(ValueError):
    """Published snapshot failed verification; never fall back silently."""


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str,
                      allow_nan=False).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def save_series(df: pd.DataFrame, meta: dict, path: Path) -> None:
    """Publish snapshot first, atomically replace pointer last on the same volume.

    Concurrent writers publish independent snapshots; last pointer wins. Interrupted writes
    leave unreferenced directories for manual recovery. No automatic garbage collection.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_id = uuid.uuid4().hex
    folder = path.parent / "_snapshots" / path.stem / snapshot_id
    folder.mkdir(parents=True, exist_ok=False)
    parquet = df.to_parquet(index=True)
    metadata = _json_bytes(meta)
    _write_new(folder / "series.parquet", parquet)
    _write_new(folder / "meta.json", metadata)
    manifest = {
        "schema_version": 1, "snapshot_id": snapshot_id,
        "ingested_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": meta.get("source"), "fetched_at_utc": meta.get("fetched_at_utc"),
        "rows": len(df), "columns": [str(c) for c in df.columns],
        "parquet_sha256": _digest(parquet), "metadata_sha256": _digest(metadata),
        "availability_status": "ingest_only_not_historical_pit",
    }
    manifest_bytes = _json_bytes(manifest)
    _write_new(folder / "manifest.json", manifest_bytes)
    pointer = {"schema_version": 1,
               "manifest": (folder / "manifest.json").relative_to(path.parent).as_posix(),
               "manifest_sha256": _digest(manifest_bytes)}
    temp = path.parent / f".{path.stem}.{snapshot_id}.tmp"
    try:
        _write_new(temp, _json_bytes(pointer))
        for attempt in range(6):
            try:
                os.replace(temp, path.with_suffix(".snapshot.json"))
                break
            except PermissionError:
                # Windows antivirus/sync/readers can briefly hold the destination open.
                if attempt == 5:
                    raise
                time.sleep(0.01 * 2 ** attempt)
    finally:
        temp.unlink(missing_ok=True)


def load_snapshot(path: Path, pointer: dict) -> tuple[pd.DataFrame, dict]:
    """Load a pinned pointer from run_meta, independently of the current pointer."""
    try:
        if pointer["schema_version"] != 1:
            raise ValueError("unsupported pointer version")
        relative = Path(pointer["manifest"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe manifest path")
        root = Path(path).parent.resolve()
        manifest_path = (root / relative).resolve()
        if not manifest_path.is_relative_to(root):
            raise ValueError("manifest escapes snapshot root")
        raw_manifest = manifest_path.read_bytes()
        if _digest(raw_manifest) != pointer["manifest_sha256"]:
            raise ValueError("manifest hash mismatch")
        manifest = json.loads(raw_manifest)
        if manifest["schema_version"] != 1:
            raise ValueError("unsupported manifest version")
        data = (manifest_path.parent / "series.parquet").read_bytes()
        metadata = (manifest_path.parent / "meta.json").read_bytes()
        if _digest(data) != manifest["parquet_sha256"] or _digest(metadata) != manifest["metadata_sha256"]:
            raise ValueError("data/metadata hash mismatch")
        df = pd.read_parquet(io.BytesIO(data))
        if len(df) != manifest["rows"] or [str(c) for c in df.columns] != manifest["columns"]:
            raise ValueError("shape mismatch")
        meta = json.loads(metadata)
        meta["_snapshot"] = pointer
        meta["_snapshot_id"] = manifest["snapshot_id"]
        meta["_integrity"] = "sha256_verified"
        return df, meta
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise SnapshotIntegrityError(f"snapshot verification failed for {path}: {exc}") from exc


def load_series(path: Path) -> tuple[pd.DataFrame, dict] | None:
    path = Path(path)
    pointer_path = path.with_suffix(".snapshot.json")
    if pointer_path.exists():
        try:
            pointer = json.loads(pointer_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise SnapshotIntegrityError(f"invalid snapshot pointer: {pointer_path}") from exc
        return load_snapshot(path, pointer)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    meta_path = path.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["_integrity"] = "legacy_unverified"
    return df, meta
