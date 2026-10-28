"""Synthetic fixtures. Synthetic data is used ONLY in unit tests, never for real training or forecasts."""

import numpy as np
import pandas as pd
import pytest


def synthetic_prices(start="2010-01-01", periods=3000, freq="B", seed=0, drift=0.0003) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=periods, freq=freq)
    close = 100 * np.exp(np.cumsum(drift + 0.01 * rng.standard_normal(periods)))
    return pd.DataFrame({"open": close, "high": close * 1.005, "low": close * 0.995, "close": close,
                         "adj_close": close, "volume": rng.integers(1_000, 2_000, periods).astype(float)}, index=idx)


@pytest.fixture
def prices():
    return {
        "AAA": synthetic_prices(seed=1),
        "BBB": synthetic_prices(seed=2),
        "CCC": synthetic_prices(start="2009-06-01", periods=4000, freq="D", seed=3),  # trades every day
    }


@pytest.fixture
def cfg():
    return {
        "modeling": {"random_state": 0},
        "validation": {"min_train_years": 4, "val_block_years": 1, "holdout_years": 2, "selection_metric": "brier"},
        "strategy": {"threshold": 0.5, "execution_lag_bars": 1, "cost_bps": 10},
        "reliability": {"min_auc": 0.55},
    }
