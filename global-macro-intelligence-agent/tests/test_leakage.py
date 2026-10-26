"""Look-ahead (future information) tests."""

import numpy as np
import pandas as pd

from gmia.features.build import asof_strict, build_dataset, make_labels, own_features
from gmia.evaluation.splits import make_folds


def test_own_features_ignore_future_bars(prices):
    px = prices["AAA"]
    cut = px.index[2000]
    full = own_features(px).loc[:cut]
    truncated = own_features(px.loc[:cut])
    pd.testing.assert_frame_equal(full, truncated)


def test_changing_future_prices_does_not_change_past_features(prices):
    base, _ = build_dataset("AAA", prices, [5, 20], ["BBB", "CCC"], [["AAA", "CCC"]])
    t = base.index[1500]
    shocked = {k: v.copy() for k, v in prices.items()}
    for k in shocked:  # wreck every series strictly after t
        shocked[k].loc[shocked[k].index > t, ["close", "adj_close"]] *= 3.0
    after, feats = build_dataset("AAA", shocked, [5, 20], ["BBB", "CCC"], [["AAA", "CCC"]])
    pd.testing.assert_frame_equal(base.loc[:t, feats], after.loc[:t, feats])


def test_other_assets_are_joined_strictly_before_target_date(prices):
    target_idx = prices["AAA"].index[100:110]
    other = pd.DataFrame({"x": np.arange(len(prices["BBB"]))}, index=prices["BBB"].index)
    joined = asof_strict(target_idx, other)
    for t, v in joined["x"].items():
        src_date = other.index[int(v)]
        assert src_date < t


def test_same_day_external_value_is_not_used():
    idx = pd.to_datetime(["2020-01-02", "2020-01-03"])
    ext = pd.DataFrame({"x": [1.0, 2.0]}, index=idx)
    joined = asof_strict(idx, ext)
    assert np.isnan(joined["x"].iloc[0])
    assert joined["x"].iloc[1] == 1.0


def test_labels_are_future_returns_and_not_features(prices):
    px = prices["AAA"]
    lab = make_labels(px["adj_close"], [5])
    t = px.index[100]
    expected = px["adj_close"].iloc[105] / px["adj_close"].iloc[100] - 1
    assert np.isclose(lab.loc[t, "fwd_ret_5"], expected)
    assert lab.loc[t, "y_5"] == float(expected > 0)
    assert lab.loc[t, "label_end_5"] == px.index[105]
    assert lab["y_5"].iloc[-5:].isna().all()
    _, feats = build_dataset("AAA", prices, [5], ["BBB"], [])
    assert not any(c.startswith(("y_", "fwd_ret_", "label_end_", "ret_next")) for c in feats)


def test_calendar_day_horizon_for_daily_asset(prices):
    px = prices["CCC"]  # every calendar day, like BTC
    lab = make_labels(px["adj_close"], [5])
    t = px.index[10]
    assert (lab.loc[t, "label_end_5"] - t).days == 5


def test_purging_removes_overlapping_training_labels(prices):
    lab = make_labels(prices["AAA"]["adj_close"], [20]).dropna(subset=["y_20"])
    folds = make_folds(lab["label_end_20"], 4, 1, 2)
    assert folds[-1].kind == "holdout"
    for f in folds:
        test_start = f.test_index.min()
        assert f.train_index.max() < test_start
        assert (lab.loc[f.train_index, "label_end_20"] < test_start).all()
        assert f.purged >= 19  # about h rows dropped at each boundary


def test_folds_are_time_ordered_and_disjoint(prices):
    lab = make_labels(prices["AAA"]["adj_close"], [5]).dropna(subset=["y_5"])
    folds = make_folds(lab["label_end_5"], 4, 1, 2)
    tests = [f.test_index for f in folds]
    for a, b in zip(tests, tests[1:]):
        assert a.max() < b.min()
    holdout = folds[-1]
    for f in folds[:-1]:
        assert f.test_index.max() < holdout.test_index.min()
