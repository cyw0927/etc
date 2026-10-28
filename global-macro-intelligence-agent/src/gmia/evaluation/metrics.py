"""Probability-forecast metrics. Prediction quality is evaluated separately from strategy P&L."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(ece)


def classification_metrics(y, p) -> dict:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    pred = (p > 0.5).astype(float)
    both = len(np.unique(y)) == 2
    return {
        "n": int(len(y)),
        "up_rate": float(y.mean()),
        "mean_prob": float(p.mean()),
        "accuracy": float((pred == y).mean()),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)) if both else np.nan,
        "roc_auc": float(roc_auc_score(y, p)) if both else np.nan,
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "ece": expected_calibration_error(y, p),
        "pred_up_share": float(pred.mean()),
    }


def reliability_table(y, p, bins: int = 10) -> pd.DataFrame:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.any():
            rows.append({"bin_low": edges[b], "bin_high": edges[b + 1], "mean_prob": p[m].mean(),
                         "observed_up_rate": y[m].mean(), "count": int(m.sum())})
    return pd.DataFrame(rows)
