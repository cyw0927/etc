"""Cached loaders for the dashboard. Reads only stored real data and run artifacts — never generates data."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from gmia.config import ARTIFACTS_DIR, load_config
from gmia.data import fred, market

LATEST = ARTIFACTS_DIR / "latest"


@st.cache_data(ttl="10m")
def config() -> dict:
    return load_config()


@st.cache_data(ttl="10m")
def prices() -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    cfg = config()
    out, metas = {}, {}
    for key in cfg["assets"]:
        loaded = market.load_asset(cfg["data"]["raw_dir"], key)
        if loaded is not None:
            out[key], metas[key] = loaded
    return out, metas


@st.cache_data(ttl="10m")
def fred_series(kind: str) -> tuple[dict[str, pd.Series], dict[str, dict]]:
    cfg = config()
    out, metas = {}, {}
    for sid in cfg.get(kind, {}):
        loaded = fred.load_fred(cfg["data"]["raw_dir"], sid, kind)
        if loaded is not None:
            out[sid], metas[sid] = loaded[0].iloc[:, 0], loaded[1]
    return out, metas


def has_run() -> bool:
    return (LATEST / "forecasts.json").exists()


@st.cache_data(ttl="10m")
def run_artifacts() -> dict:
    return {
        "forecasts": json.loads((LATEST / "forecasts.json").read_text(encoding="utf-8")),
        "meta": json.loads((LATEST / "run_meta.json").read_text(encoding="utf-8")),
        "summary": pd.read_csv(LATEST / "metrics_summary.csv"),
        "folds": pd.read_csv(LATEST / "fold_metrics.csv", parse_dates=["test_start", "test_end"]),
        "reliability": pd.read_csv(LATEST / "reliability.csv"),
        "curves": pd.read_parquet(LATEST / "equity_curves.parquet"),
    }


MODEL_LABELS = {
    "baseline_base_rate": "B1 과거 상승비율",
    "baseline_momentum": "B2 모멘텀 규칙",
    "logistic_regression": "M1 로지스틱 회귀",
    "hist_gradient_boosting": "M2 HistGradientBoosting",
    "lightgbm": "M3 LightGBM",
}
