"""Parquet storage with a JSON sidecar describing source, fetch time and quality."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def save_series(df: pd.DataFrame, meta: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    with open(path.with_suffix(".meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)


def load_series(path: Path) -> tuple[pd.DataFrame, dict] | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    meta_path = path.with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return df, meta
