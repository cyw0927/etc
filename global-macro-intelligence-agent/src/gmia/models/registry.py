"""Candidate models. All expose fit(X, y) and predict_proba(X) -> P(up).

Imputation and scaling live inside sklearn Pipelines, so they are fitted on the training window only.
Hyperparameters are fixed (no tuning loop) and deliberately conservative to limit overfitting and
selection bias on a few thousand noisy daily samples.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

EPS = 1e-6


class BaseRate:
    """Baseline 1: P(up) = share of up-labels in the training window."""

    name = "baseline_base_rate"

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "BaseRate":
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

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "Momentum":
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
    def __init__(self, name: str, estimator):
        self.name = name
        self.estimator = estimator

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "SklearnModel":
        # a series that did not exist yet in this training window (e.g. BTC before 2014) carries no information
        self.columns_ = [c for c in X.columns if X[c].notna().any()]
        self.estimator.fit(X[self.columns_], y.astype(int))
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.clip(self.estimator.predict_proba(X[self.columns_])[:, 1], EPS, 1 - EPS)


def make_models(horizon: int, random_state: int = 42) -> list:
    return [
        BaseRate(),
        Momentum(feature=f"ret_{horizon}"),
        SklearnModel("logistic_regression", make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(),
            LogisticRegression(C=0.05, max_iter=2000),
        )),
        SklearnModel("hist_gradient_boosting", HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.03, max_iter=200, min_samples_leaf=100,
            l2_regularization=1.0, random_state=random_state,
        )),
        SklearnModel("lightgbm", LGBMClassifier(
            n_estimators=300, learning_rate=0.02, num_leaves=7, min_child_samples=100,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
            random_state=random_state, verbose=-1, n_jobs=1,
        )),
    ]


BASELINES = {"baseline_base_rate", "baseline_momentum"}
