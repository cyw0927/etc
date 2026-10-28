"""v0.3: calibration / shrinkage, hypothesis models and the pre-registered significance test."""

import math

import numpy as np
import pandas as pd

from gmia.evaluation.significance import benjamini_hochberg, loss_diff_test, newey_west_se, significance_table
from gmia.features.build import build_dataset, hypothesis_own_features
from gmia.models.registry import Calibrated, CompleteCaseLogit


class FixedProb:
    """Test double: returns a stored probability column, records what it was trained on."""

    name = "fixed"
    columns = ["p_raw"]

    def fit(self, X, y, label_end=None):
        self.fit_index_ = X.index
        return self

    def predict_proba(self, X):
        return X["p_raw"].to_numpy()


def _frame(n=500, seed=0, signal=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    p_raw = rng.uniform(0.2, 0.8, n)
    y = (rng.uniform(size=n) < 0.5 + signal * (p_raw - 0.5)).astype(float)
    return pd.DataFrame({"p_raw": p_raw}, index=idx), pd.Series(y, index=idx)


def test_shrink_lambda_matches_closed_form_and_is_clipped():
    X, y = _frame(signal=0.5)
    m = Calibrated("s", FixedProb, "shrink").fit(X, y)
    cut = X.index[int(len(X) * 0.8)]
    calib = X.index >= cut
    b = y[X.index < cut].mean()
    p, yc = X.loc[calib, "p_raw"].to_numpy(), y[calib].to_numpy()
    expected = np.clip(((yc - b) * (p - b)).sum() / ((p - b) ** 2).sum(), 0, 1)
    assert math.isclose(m.lambda_, expected, rel_tol=1e-12)
    assert 0 <= m.lambda_ <= 1
    q = m.predict_proba(X)
    assert np.allclose(q, b + m.lambda_ * (X["p_raw"].to_numpy() - b))


def test_shrink_goes_to_base_rate_when_raw_probabilities_are_noise():
    X, y = _frame(signal=0.0, seed=3)
    m = Calibrated("s", FixedProb, "shrink").fit(X, y)
    assert m.lambda_ < 0.5  # noise forecasts get pulled strongly toward the base rate


def test_calibration_block_is_last_20pct_and_inner_fit_is_purged():
    X, y = _frame(n=500)
    label_end = pd.Series(X.index, index=X.index).shift(-20).fillna(X.index[-1])
    m = Calibrated("s", FixedProb, "platt").fit(X, y, label_end=label_end)
    cut = X.index[400]
    assert m.n_calib_ == 100
    assert m.base_.fit_index_.max() < cut
    assert (label_end.loc[m.base_.fit_index_] < cut).all()
    assert m.n_inner_ == 400 - 20  # last h rows before the calibration block purged


def test_platt_is_monotone_and_bounded():
    X, y = _frame(signal=0.8, seed=5)
    m = Calibrated("p", FixedProb, "platt").fit(X, y)
    grid = pd.DataFrame({"p_raw": np.linspace(0.01, 0.99, 50)}, index=pd.date_range("2030-01-01", periods=50))
    q = m.predict_proba(grid)
    assert np.all(np.diff(q) >= -1e-12) and np.all((q > 0) & (q < 1))


def test_complete_case_logit_uses_prior_for_missing_rows():
    X, y = _frame(n=300)
    X["f"] = X["p_raw"]
    X.loc[X.index[:50], "f"] = np.nan
    m = CompleteCaseLogit("h", ["f"]).fit(X, y)
    p = m.predict_proba(X)
    assert np.allclose(p[:50], y.mean())
    assert set(m.coefficients) == {"f"}


def test_hypothesis_features_only_use_past(prices):
    px = prices["AAA"]
    cut = px.index[2000]
    full = hypothesis_own_features(px).loc[:cut]
    truncated = hypothesis_own_features(px.loc[:cut])
    pd.testing.assert_frame_equal(full, truncated)
    t = px.index[1000]
    assert math.isclose(full.loc[t, "mom_12_1"], px["adj_close"].iloc[1000 - 21] / px["adj_close"].iloc[1000 - 252] - 1)


def test_newey_west_lag0_equals_iid_standard_error():
    d = np.random.default_rng(0).normal(size=400)
    assert math.isclose(newey_west_se(d, 0), d.std() / math.sqrt(len(d)), rel_tol=1e-12)
    # positively autocorrelated losses must widen the standard error
    ar = np.convolve(np.random.default_rng(1).normal(size=420), np.ones(20) / 20, mode="valid")
    assert newey_west_se(ar, 20) > newey_west_se(ar, 0) * 2


def test_benjamini_hochberg_known_example():
    p = [0.01, 0.04, 0.03, 0.20]
    rejected, adj = benjamini_hochberg(p, 0.05)
    assert list(rejected) == [True, False, False, False]
    assert np.allclose(adj, [0.04, 0.0533333, 0.0533333, 0.20], atol=1e-6)


def test_loss_diff_test_detects_better_forecast_and_not_noise():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 800).astype(float)
    base = np.full(800, 0.5)
    good = np.clip(0.5 + 0.3 * (y - 0.5) + rng.normal(0, 0.05, 800), 0.01, 0.99)
    noisy = np.clip(0.5 + rng.normal(0, 0.1, 800), 0.01, 0.99)
    assert loss_diff_test(y, good, base, lag=5)["p_one_sided"] < 0.001
    assert loss_diff_test(y, noisy, base, lag=5)["p_one_sided"] > 0.5  # noise is worse than the base rate


def test_significance_table_and_support_rule():
    dates = pd.date_range("2024-01-01", periods=300, freq="B")
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 300).astype(float)
    preds = []
    for model, p in {"baseline_base_rate": np.full(300, 0.5),
                     "good": np.clip(0.5 + 0.3 * (y - 0.5), 0.01, 0.99),
                     "noise": np.clip(0.5 + rng.normal(0, 0.1, 300), 0.01, 0.99)}.items():
        preds.append(pd.DataFrame({"date": dates, "kind": "holdout", "model": model, "p": p, "y": y,
                                   "target": "AAA", "horizon": 5}))
    summary = pd.DataFrame({"target": "AAA", "horizon": 5, "kind": "validation",
                            "model": ["baseline_base_rate", "good", "noise"], "brier": [0.25, 0.20, 0.26]})
    sig = significance_table(pd.concat(preds), summary, q=0.10).set_index("model")
    assert sig.loc["good", "supported"] and not sig.loc["noise", "supported"]
    assert sig["n_tests"].iloc[0] == 2


def test_v02_models_unchanged_by_extra_columns(prices, cfg):
    """Adding hypothesis columns to the dataset must not change what M1 sees."""
    from gmia.models.registry import make_models

    ds, feats = build_dataset("AAA", prices, [5], ["BBB"], [])
    lab = ds[ds["y_5"].notna()]
    m_all = [m for m in make_models(5, feats, available=set(ds.columns)) if m.name == "logistic_regression"][0]
    m_v02 = [m for m in make_models(5, feats, hypotheses=False, calibrated=False) if m.name == "logistic_regression"][0]
    p_all = m_all.fit(lab, lab["y_5"]).predict_proba(lab)
    p_v02 = m_v02.fit(lab[feats], lab["y_5"]).predict_proba(lab[feats])
    assert np.allclose(p_all, p_v02)
