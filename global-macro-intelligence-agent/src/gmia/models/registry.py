"""Candidate models. All expose fit(X, y, label_end=None) and predict_proba(X) -> P(up).

Each model reads only its own `columns` from X, so adding hypothesis features to the dataset does not
change the v0.2 models. Imputation and scaling live inside sklearn Pipelines and are fitted on the
training window only. Hyperparameters are fixed (no tuning loop). The v0.3 calibrated variants and
hypothesis models follow docs/preregistration_v0.3.md exactly.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

EPS = 1e-6
CALIB_FRAC = 0.2

EQUITY = ("SPY", "QQQ", "KOSPI", "NIKKEI")

# Pre-registered hypotheses: features and expected coefficient signs (docs/preregistration_v0.3.md §2B).
# expected: feature -> (sign, assets it applies to or None for all, horizons it applies to or None for all)
HYPOTHESES = {
    "h1_trend": {
        "features": ["mom_12_1", "ma_gap_200"],
        "expected": {"mom_12_1": (+1, None, None), "ma_gap_200": (+1, None, None)},
    },
    "h2_vol_regime": {
        "features": ["vol_20", "vol_ratio"],
        "expected": {"vol_20": (-1, EQUITY + ("BTC",), None), "vol_ratio": (-1, EQUITY + ("BTC",), None)},
    },
    "h3_rates_regime": {
        "features": ["us10y_2y", "us2y_chg60", "us10y_chg60"],
        "expected": {"us2y_chg60": (-1, EQUITY, None), "us10y_chg60": (-1, ("GOLD",), None)},
    },
    "h4_short_reversal": {
        "features": ["ret_5", "ret_1"],
        "expected": {"ret_5": (-1, EQUITY, (5,)), "ret_1": (-1, EQUITY, (5,))},
    },
}

MODEL_LABELS = {
    "baseline_base_rate": "B1 과거 상승비율",
    "baseline_momentum": "B2 모멘텀 규칙",
    "logistic_regression": "M1 로지스틱 회귀",
    "hist_gradient_boosting": "M2 HistGradientBoosting",
    "lightgbm": "M3 LightGBM",
    "logistic_regression_shrink": "M1 + 축소",
    "logistic_regression_platt": "M1 + Platt",
    "hist_gradient_boosting_shrink": "M2 + 축소",
    "hist_gradient_boosting_platt": "M2 + Platt",
    "lightgbm_shrink": "M3 + 축소",
    "lightgbm_platt": "M3 + Platt",
    "h1_trend": "H1 추세(모멘텀)",
    "h2_vol_regime": "H2 변동성 레짐",
    "h3_rates_regime": "H3 금리 레짐",
    "h4_short_reversal": "H4 단기 반전",
}
BASELINES = {"baseline_base_rate", "baseline_momentum"}


class BaseRate:
    """Baseline 1: P(up) = share of up-labels in the training window."""

    name = "baseline_base_rate"
    columns: list[str] = []

    def fit(self, X: pd.DataFrame, y: pd.Series, label_end=None) -> "BaseRate":
        self.p_ = float(np.clip(y.mean(), EPS, 1 - EPS))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.full(len(X), self.p_)


class Momentum:
    """Baseline 2: P(up | sign of the past-h return), estimated from training frequencies.

    Uses the target's own trailing return over the same horizon (ret_5 for h=5, ret_20 for h=20).
    """

    name = "baseline_momentum"

    def __init__(self, feature: str):
        self.feature = feature
        self.columns = [feature]

    def fit(self, X: pd.DataFrame, y: pd.Series, label_end=None) -> "Momentum":
        up = X[self.feature] > 0
        prior = float(y.mean())
        # light shrinkage toward the base rate (Laplace-style, 20 pseudo-observations)
        k = 20
        self.p_up_ = float((y[up].sum() + k * prior) / (up.sum() + k))
        self.p_down_ = float((y[~up].sum() + k * prior) / ((~up).sum() + k))
        self.prior_ = prior
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        f = X[self.feature]
        p = np.where(f > 0, self.p_up_, self.p_down_)
        p = np.where(f.isna(), self.prior_, p)
        return np.clip(p, EPS, 1 - EPS)


class SklearnModel:
    def __init__(self, name: str, estimator, columns: list[str]):
        self.name = name
        self.estimator = estimator
        self.columns = list(columns)

    def fit(self, X: pd.DataFrame, y: pd.Series, label_end=None) -> "SklearnModel":
        # a series that did not exist yet in this training window (e.g. BTC before 2014) carries no information
        self.columns_ = [c for c in self.columns if X[c].notna().any()]
        self.estimator.fit(X[self.columns_], y.astype(int))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.clip(self.estimator.predict_proba(X[self.columns_])[:, 1], EPS, 1 - EPS)


class CompleteCaseLogit:
    """Standardized logistic regression on a few features; rows with any missing feature are skipped in
    fitting and get the training base rate at prediction time."""

    def __init__(self, name: str, columns: list[str], C: float = 1.0):
        self.name = name
        self.columns = list(columns)
        self.C = C

    def fit(self, X: pd.DataFrame, y: pd.Series, label_end=None) -> "CompleteCaseLogit":
        ok = X[self.columns].notna().all(axis=1)
        self.prior_ = float(np.clip(y.mean(), EPS, 1 - EPS))
        self.pipe_ = None
        if ok.sum() >= 50 and y[ok].nunique() == 2:
            self.pipe_ = make_pipeline(StandardScaler(), LogisticRegression(C=self.C, max_iter=2000))
            self.pipe_.fit(X.loc[ok, self.columns], y[ok].astype(int))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = np.full(len(X), self.prior_)
        if self.pipe_ is not None:
            ok = X[self.columns].notna().all(axis=1).values
            if ok.any():
                p[ok] = self.pipe_.predict_proba(X.loc[ok, self.columns])[:, 1]
        return np.clip(p, EPS, 1 - EPS)

    @property
    def coefficients(self) -> dict[str, float] | None:
        if self.pipe_ is None:
            return None
        return dict(zip(self.columns, self.pipe_[-1].coef_[0].tolist()))


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return np.log(p / (1 - p))


class Calibrated:
    """Fit the base model on the earlier part of the training window, then learn a probability transform
    on the last CALIB_FRAC of it (purged so no inner-fit label overlaps the calibration block).

    method="shrink": p' = b + lambda (p - b), lambda in [0, 1] minimizes calibration-block Brier
    method="platt":  p' = sigmoid(a + c * logit(p)) fitted on the calibration block
    """

    def __init__(self, name: str, base_factory: Callable[[], object], method: str):
        assert method in ("shrink", "platt")
        self.name = name
        self.base_factory = base_factory
        self.method = method
        self.columns = list(base_factory().columns)

    def fit(self, X: pd.DataFrame, y: pd.Series, label_end: pd.Series | None = None) -> "Calibrated":
        dates = pd.DatetimeIndex(X.index)
        cut = dates.sort_values()[int(len(dates) * (1 - CALIB_FRAC))]
        calib = dates >= cut
        inner = dates < cut
        if label_end is not None:
            inner &= (pd.DatetimeIndex(label_end.loc[X.index]) < cut)
        self.base_ = self.base_factory().fit(X[inner], y[inner])
        self.b_ = float(np.clip(y[inner].mean(), EPS, 1 - EPS))
        p = self.base_.predict_proba(X[calib])
        yc = y[calib].to_numpy(dtype=float)
        if self.method == "shrink":
            dev = p - self.b_
            denom = float((dev ** 2).sum())
            self.lambda_ = float(np.clip(((yc - self.b_) * dev).sum() / denom, 0.0, 1.0)) if denom > 0 else 0.0
        else:
            self.platt_ = LogisticRegression(C=1e6, max_iter=2000).fit(_logit(p).reshape(-1, 1), yc.astype(int)) \
                if len(np.unique(yc)) == 2 else None
        self.n_inner_, self.n_calib_ = int(inner.sum()), int(calib.sum())
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = self.base_.predict_proba(X)
        if self.method == "shrink":
            q = self.b_ + self.lambda_ * (p - self.b_)
        elif self.platt_ is not None:
            q = self.platt_.predict_proba(_logit(p).reshape(-1, 1))[:, 1]
        else:
            q = np.full(len(X), self.b_)
        return np.clip(q, EPS, 1 - EPS)

    @property
    def coefficients(self) -> dict[str, float] | None:
        return getattr(self.base_, "coefficients", None)


def _ml_factories(feature_cols: list[str], random_state: int) -> dict[str, Callable[[], SklearnModel]]:
    return {
        "logistic_regression": lambda: SklearnModel("logistic_regression", make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(),
            LogisticRegression(C=0.05, max_iter=2000),
        ), feature_cols),
        "hist_gradient_boosting": lambda: SklearnModel("hist_gradient_boosting", HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.03, max_iter=200, min_samples_leaf=100,
            l2_regularization=1.0, random_state=random_state,
        ), feature_cols),
        "lightgbm": lambda: SklearnModel("lightgbm", LGBMClassifier(
            n_estimators=300, learning_rate=0.02, num_leaves=7, min_child_samples=100,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
            random_state=random_state, verbose=-1, n_jobs=1,
        ), feature_cols),
    }


def make_models(horizon: int, feature_cols: list[str], random_state: int = 42,
                hypotheses: bool = True, calibrated: bool = True, available: set[str] | None = None) -> list:
    """`available`: dataset columns; hypothesis models whose inputs are missing (e.g. no rates) are skipped."""
    ml = _ml_factories(feature_cols, random_state)
    models = [BaseRate(), Momentum(feature=f"ret_{horizon}")] + [f() for f in ml.values()]
    if calibrated:
        for key, factory in ml.items():
            for method in ("shrink", "platt"):
                models.append(Calibrated(f"{key}_{method}", factory, method))
    if hypotheses:
        for hid, spec in HYPOTHESES.items():
            cols = spec["features"]
            if available is not None and not set(cols) <= available:
                continue
            models.append(Calibrated(hid, lambda cols=cols, hid=hid: CompleteCaseLogit(hid, cols), "shrink"))
    return models


def required_columns(models: list) -> list[str]:
    return list(dict.fromkeys(c for m in models for c in m.columns))
