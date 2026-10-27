"""v0.4 append-only forward ledger. All series in these tests are synthetic only."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from gmia.config import load_config
from gmia.evaluation.forward import (
    FAMILY_SIZE, MIN_PAIRS, MODELS, append_forecasts, bar_completion_utc,
    forward_significance, read_forecasts, read_scores, score_pending,
)


def _utc(date: str) -> datetime:
    return datetime.fromisoformat(date).replace(tzinfo=timezone.utc)


def _fixture(tmp_path):
    cfg = load_config()
    dates = pd.bdate_range("2026-10-01", periods=25)
    close = 100 + np.arange(len(dates), dtype=float)
    px = pd.DataFrame({"adj_close": close}, index=dates)
    path = tmp_path / "ledger" / "forward.sqlite3"
    fc = {
        "target": "SPY", "horizon": 5, "forecast_date": "2026-10-01",
        "p_up_all_models": {m: 0.55 for m in MODELS},
    }
    return cfg, dates, px, path, fc


def test_first_issued_forecast_survives_repeated_runs(tmp_path):
    cfg, dates, px, path, fc = _fixture(tmp_path)
    r1 = append_forecasts(path, [fc], {"SPY": px}, cfg, "run1", "sha1",
                          recorded_utc=_utc("2026-10-02T01:00:00"))
    assert r1["inserted"] == len(MODELS)
    fc["p_up_all_models"] = {m: 0.99 for m in MODELS}
    r2 = append_forecasts(path, [fc], {"SPY": px}, cfg, "run2", "sha2",
                          recorded_utc=_utc("2026-10-02T02:00:00"))
    assert r2["inserted"] == 0 and r2["duplicates"] == len(MODELS)
    stored = read_forecasts(path)
    assert len(stored) == len(MODELS)
    assert set(stored["git_commit"]) == {"sha1"}
    assert np.allclose(stored["probability"], 0.55)


def test_missing_candidate_is_not_fabricated(tmp_path):
    cfg, _, px, path, fc = _fixture(tmp_path)
    fc["p_up_all_models"].pop("h3_rates_regime")
    r = append_forecasts(path, [fc], {"SPY": px}, cfg, "run1", "sha1",
                         recorded_utc=_utc("2026-10-02T01:00:00"))
    assert r["inserted"] == len(MODELS) - 1
    assert "h3_rates_regime" not in read_forecasts(path)["model"].tolist()


def test_rejects_incomplete_anchor_and_invalid_probability(tmp_path):
    cfg, _, px, path, fc = _fixture(tmp_path)
    with pytest.raises(ValueError, match="incomplete anchor"):
        append_forecasts(path, [fc], {"SPY": px}, cfg, "r", "sha",
                         recorded_utc=_utc("2026-10-01T12:00:00"))
    fc["p_up_all_models"]["baseline_base_rate"] = 1.01
    with pytest.raises(ValueError, match="invalid probability"):
        append_forecasts(path, [fc], {"SPY": px}, cfg, "r", "sha",
                         recorded_utc=_utc("2026-10-02T01:00:00"))
    assert read_forecasts(path).empty if path.exists() else True


def test_maturity_stale_source_and_immutable_scoring(tmp_path):
    cfg, dates, px, path, fc = _fixture(tmp_path)
    append_forecasts(path, [fc], {"SPY": px}, cfg, "r", "sha",
                     recorded_utc=_utc("2026-10-02T01:00:00"))
    before = score_pending(path, cfg, {"SPY": px},
                           {"SPY": {"fetched_at_utc": "2026-10-20T00:00:00+00:00"}},
                           now_utc=_utc("2026-10-03T00:00:00"))
    assert before["not_mature"] == len(MODELS)
    assert read_scores(path).empty

    stale = score_pending(path, cfg, {"SPY": px},
                          {"SPY": {"fetched_at_utc": "2026-10-01T00:00:00+00:00"}},
                          now_utc=_utc("2026-11-15T00:00:00"))
    assert stale["stale_source"] == len(MODELS)
    source = {"SPY": {"fetched_at_utc": "2026-11-15T00:00:00+00:00"}}
    result = score_pending(path, cfg, {"SPY": px}, source, now_utc=_utc("2026-11-15T00:00:00"))
    assert result["scored"] == len(MODELS)
    got = read_scores(path)
    assert set(got["y"]) == {1}
    assert got["label_end"].iloc[0] == dates[5].strftime("%Y-%m-%d")
    assert math.isclose(float(got["realized_return"].iloc[0]), 5 / 100)

    altered = px.copy()
    altered.loc[dates[5], "adj_close"] = 1.0
    again = score_pending(path, cfg, {"SPY": altered}, source, now_utc=_utc("2026-11-15T00:00:00"))
    assert again["scored"] == 0
    assert set(read_scores(path)["y"]) == {1}


def test_late_predictions_excluded_from_scoring(tmp_path):
    cfg, _, px, path, fc = _fixture(tmp_path)
    append_forecasts(path, [fc], {"SPY": px}, cfg, "late", "sha",
                     recorded_utc=_utc("2026-10-20T00:00:00"))
    x = score_pending(path, cfg, {"SPY": px},
                      {"SPY": {"fetched_at_utc": "2026-11-15T00:00:00+00:00"}},
                      now_utc=_utc("2026-11-15T00:00:00"))
    assert x["late_excluded"] == len(MODELS)
    assert read_scores(path).empty


def test_forward_family_fixed_and_insufficient_samples_do_not_support():
    dates = pd.bdate_range("2026-11-01", periods=80).strftime("%Y-%m-%d")
    rows = []
    for i, dt in enumerate(dates):
        y = i % 2
        for model, p in [("baseline_base_rate", 0.5), ("h4_short_reversal", 0.9 if y else 0.1)]:
            rows.append(dict(forecast_date=dt, asset="SPY", horizon=5, model=model,
                             probability=p, y=y))
    result = forward_significance(pd.DataFrame(rows))
    assert len(result) == FAMILY_SIZE == 252
    assert (result["p_one_sided"] == 1).all()
    assert not result["supported"].any()


def test_forward_uses_matched_dates_and_bh_not_unregistered_family():
    dates = pd.bdate_range("2026-01-01", periods=MIN_PAIRS + 5).strftime("%Y-%m-%d")
    rng = np.random.default_rng(42)
    y = rng.integers(0, 2, len(dates))
    rows = []
    for dt, label in zip(dates, y):
        for model, p in [
            ("baseline_base_rate", 0.5),
            ("h4_short_reversal", 0.85 if label else 0.15),
        ]:
            rows.append(dict(forecast_date=dt, asset="SPY", horizon=5,
                             model=model, probability=p, y=label))
    result = forward_significance(pd.DataFrame(rows))
    good = result[(result["asset"] == "SPY") &
                  (result["horizon"] == 5) &
                  (result["model"] == "h4_short_reversal")].iloc[0]
    assert good["n"] == MIN_PAIRS + 5
    assert good["enough_data"] and good["supported"]
    assert good["p_bh_adjusted"] <= 0.10
    assert (result.loc[~result["enough_data"], "p_one_sided"] == 1).all()


def test_spy_and_btc_completed_bar_times_are_different():
    cfg = load_config()
    from gmia.config import asset_specs
    sp = asset_specs(cfg)
    # 2026-10-01 SPY 16:15 New York = 20:15 UTC; BTC 00:14 next day UTC.
    assert bar_completion_utc("2026-10-01", sp["SPY"]) == _utc("2026-10-01T20:15:00")
    assert bar_completion_utc("2026-10-01", sp["BTC"]) == _utc("2026-10-02T00:14:00")
