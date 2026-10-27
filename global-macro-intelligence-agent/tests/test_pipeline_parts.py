"""Cleaning, models, metrics, strategy and walk-forward on synthetic data (unit tests only)."""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from gmia.data.clean import clean_prices, drop_incomplete_bars
from gmia.data.fred import realtime_feature
from gmia.evaluation.backtest import run_walk_forward
from gmia.evaluation.metrics import classification_metrics, expected_calibration_error
from gmia.evaluation.strategy import long_flat_backtest
from gmia.features.build import build_dataset
from gmia.models.predict import latest_forecast
from gmia.models.registry import BaseRate, Momentum, make_models


def test_clean_removes_duplicates_and_nonpositive_close():
    idx = pd.to_datetime(["2020-01-02", "2020-01-02", "2020-01-03", "2020-01-06"])
    df = pd.DataFrame({"open": [1, 1, 2, 3], "high": [1, 1, 2, 3], "low": [1, 1, -5, 3],
                       "close": [1.0, 1.1, -2.0, 3.0], "adj_close": [1.0, 1.1, -2.0, 3.0], "volume": [1, 1, 1, 1]}, index=idx)
    out, rep = clean_prices(df)
    assert rep["duplicates_removed"] == 1
    assert out.loc["2020-01-02", "close"] == 1.1  # last delivered row kept
    assert np.isnan(out.loc["2020-01-03", "close"])
    assert rep["nonpositive_close_rows"] == ["2020-01-03"]
    assert out.index.is_monotonic_increasing


def test_incomplete_bar_is_dropped():
    idx = pd.to_datetime(["2026-10-22", "2026-10-23"])
    df = pd.DataFrame({"close": [1.0, 2.0]}, index=idx)
    # 2026-10-23 15:00 New York: the 16:00 session is not over yet
    now = datetime(2026, 10, 23, 19, 0, tzinfo=timezone.utc)
    out = drop_incomplete_bars(df, "America/New_York", "16:00", now)
    assert list(out.index) == [pd.Timestamp("2026-10-22")]
    later = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)
    assert len(drop_incomplete_bars(df, "America/New_York", "16:00", later)) == 2


def test_realtime_macro_uses_only_published_vintages():
    # Jan..Dec 2019 + Jan 2020 first published on the 15th of the following month; Jan 2020 later revised
    months = pd.date_range("2019-01-01", "2020-01-01", freq="MS")
    rows = [{"realtime_start": d + pd.DateOffset(months=1, days=14), "realtime_end": pd.Timestamp("2262-01-01"),
             "date": d, "value": 100.0 + i} for i, d in enumerate(months)]
    jan = rows[-1]
    jan["realtime_end"] = pd.Timestamp("2020-03-14")
    rows.append({"realtime_start": pd.Timestamp("2020-03-15"), "realtime_end": pd.Timestamp("2262-01-01"),
                 "date": jan["date"], "value": 150.0})
    feat = realtime_feature(pd.DataFrame(rows), "yoy")
    first = feat.loc[pd.Timestamp("2020-02-15")]
    assert first["obs_date"] == pd.Timestamp("2020-01-01")
    assert np.isclose(first["value"], 112.0 / 100.0 - 1)  # first release, not the later revision
    assert np.isclose(feat.loc[pd.Timestamp("2020-03-15"), "value"], 150.0 / 100.0 - 1)


def test_baselines():
    X = pd.DataFrame({"ret_5": [0.1, -0.1, 0.2, -0.2, 0.3, -0.3]})
    y = pd.Series([1, 0, 1, 0, 1, 1], dtype=float)
    br = BaseRate().fit(X, y)
    assert np.allclose(br.predict_proba(X), y.mean())
    mom = Momentum("ret_5").fit(X, y)
    p = mom.predict_proba(X)
    assert p[0] > p[1]  # up-momentum rows get a higher probability in this sample


def test_metrics_perfect_and_constant():
    y = np.array([0, 1, 0, 1])
    m = classification_metrics(y, np.array([0.01, 0.99, 0.01, 0.99]))
    assert m["roc_auc"] == 1.0 and m["accuracy"] == 1.0 and m["brier"] < 0.001
    assert expected_calibration_error(y.astype(float), np.full(4, 0.5)) == 0.0


def test_strategy_uses_lagged_signal_and_costs():
    idx = pd.date_range("2020-01-01", periods=4, freq="B")
    p = pd.Series([0.9, 0.1, 0.9, 0.9], index=idx)
    r = pd.Series([0.01, 0.02, 0.03, 0.04], index=idx)
    stats, curve = long_flat_backtest(p, r, 0.5, lag=1, cost_bps=0, bars_per_year=252)
    assert list(curve["position"]) == [0.0, 1.0, 0.0, 1.0]
    assert np.isclose(stats["strategy_total_return"], 1.02 * 1.04 - 1)
    with_cost, _ = long_flat_backtest(p, r, 0.5, lag=1, cost_bps=100, bars_per_year=252)
    assert with_cost["strategy_total_return"] < stats["strategy_total_return"]


def test_models_handle_feature_missing_in_early_window(prices):
    X = pd.DataFrame({"ret_5": np.random.default_rng(0).normal(size=500), "late": np.nan})
    y = pd.Series(np.random.default_rng(1).integers(0, 2, 500), dtype=float)
    for m in make_models(5, ["ret_5", "late"], hypotheses=False):
        p = m.fit(X, y).predict_proba(X)
        assert np.all((p > 0) & (p < 1))


def test_walk_forward_end_to_end_on_synthetic(prices, cfg):
    ds, feats = build_dataset("AAA", prices, [5], ["BBB"], [["AAA", "BBB"]])
    res = run_walk_forward(ds, feats, 5, cfg)
    s = res["summary"]
    assert set(s["kind"]) == {"validation", "holdout"}
    assert set(s["model"]) == {m.name for m in make_models(5, feats, available=set(ds.columns))}
    assert "h1_trend" in set(s["model"]) and "h3_rates_regime" not in set(s["model"])  # no rates in synthetic data
    # random-walk data has no signal: no model should look meaningfully skilful out of sample
    hold = s[s["kind"] == "holdout"].set_index("model")
    assert (hold["roc_auc"].dropna() < 0.62).all()
    fc = latest_forecast(ds, feats, 5, res["verdict"], cfg)
    assert 0 < fc["p_up"] < 1
    assert fc["forecast_date"] == ds.index[-1].strftime("%Y-%m-%d")
    assert pd.Timestamp(fc["train_end"]) < ds.index[-1]


def test_walk_forward_detects_real_signal(prices, cfg):
    """Sanity: if a feature truly carries the future, the pipeline must find it (wiring check)."""
    ds, feats = build_dataset("AAA", prices, [5], [], [])
    rng = np.random.default_rng(0)
    ds["signal"] = ds["fwd_ret_5"] + rng.normal(0, ds["fwd_ret_5"].std() * 0.5, len(ds))
    res = run_walk_forward(ds, feats + ["signal"], 5, cfg)
    hold = res["summary"].query("kind == 'holdout'").set_index("model")
    assert hold.loc["logistic_regression", "roc_auc"] > 0.75
    assert res["verdict"]["selected_model"] not in ("baseline_base_rate", "baseline_momentum")
