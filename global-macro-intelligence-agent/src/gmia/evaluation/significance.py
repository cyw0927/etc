"""Holdout significance vs the base-rate model, with Benjamini–Hochberg FDR across all tests.

Pre-registered in docs/preregistration_v0.3.md §3:
- d_t = Brier(candidate)_t − Brier(B1)_t on the holdout, one observation per forecast date
- standard error of mean(d) by Newey–West HAC (Bartlett kernel, lag = h) because h-bar labels overlap
- one-sided test H0: E[d] >= 0 vs H1: E[d] < 0, normal approximation
- BH-FDR q = 0.10 over every (non-B1 candidate, asset, horizon)
- "supported" = BH-significant AND pooled validation Brier below B1's
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from gmia.models.registry import HYPOTHESES


def newey_west_se(d: np.ndarray, lag: int) -> float:
    d = np.asarray(d, dtype=float)
    n = len(d)
    e = d - d.mean()
    s = float(e @ e) / n
    for l in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - l / (lag + 1)) * float(e[l:] @ e[:-l]) / n
    return math.sqrt(max(s, 0.0) / n)


def loss_diff_test(y, p_model, p_base, lag: int) -> dict:
    y = np.asarray(y, dtype=float)
    d = (np.asarray(p_model) - y) ** 2 - (np.asarray(p_base) - y) ** 2
    se = newey_west_se(d, lag)
    mean = float(d.mean())
    if se > 0:
        t = mean / se
    else:  # identical forecasts (e.g. a model that collapsed to the base rate)
        t = 0.0 if mean == 0 else math.copysign(math.inf, mean)
    p = 0.5 * (1 + math.erf(t / math.sqrt(2))) if math.isfinite(t) else float(t > 0)
    return {"n": int(len(d)), "mean_brier_diff": mean, "se_hac": se, "t_stat": t, "p_one_sided": p}


def benjamini_hochberg(pvals, q: float) -> tuple[np.ndarray, np.ndarray]:
    """Returns (rejected, adjusted p-values) in the input order."""
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, m + 1)
    adj_sorted = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1.0)
    adj = np.empty(m)
    adj[order] = adj_sorted
    return adj <= q, adj


def significance_table(predictions: pd.DataFrame, summary: pd.DataFrame, q: float = 0.10) -> pd.DataFrame:
    """predictions/summary: concatenated pipeline outputs with target and horizon columns."""
    rows = []
    hold = predictions[predictions["kind"] == "holdout"]
    for (target, h), g in hold.groupby(["target", "horizon"]):
        base = g[g["model"] == "baseline_base_rate"].set_index("date")["p"]
        val = summary[(summary["target"] == target) & (summary["horizon"] == h) & (summary["kind"] == "validation")] \
            .set_index("model")["brier"]
        for model, gm in g.groupby("model"):
            if model == "baseline_base_rate":
                continue
            gm = gm.set_index("date").loc[base.index]
            res = loss_diff_test(gm["y"], gm["p"], base, lag=int(h))
            rows.append({"target": target, "horizon": h, "model": model, **res,
                         "validation_brier": val[model], "validation_brier_base_rate": val["baseline_base_rate"]})
    out = pd.DataFrame(rows)
    out["bh_significant"], out["p_bh_adjusted"] = benjamini_hochberg(out["p_one_sided"], q)
    out["validation_beats_base_rate"] = out["validation_brier"] < out["validation_brier_base_rate"]
    out["supported"] = out["bh_significant"] & out["validation_beats_base_rate"]
    out["fdr_q"] = q
    out["n_tests"] = len(out)
    return out


def sign_consistency(coefs: pd.DataFrame) -> pd.DataFrame:
    """Share of validation folds whose hypothesis coefficient has the pre-registered sign (where one exists)."""
    rows = []
    v = coefs[coefs["kind"] == "validation"]
    for (target, h, model, feature), g in v.groupby(["target", "horizon", "model", "feature"]):
        exp = HYPOTHESES.get(model, {}).get("expected", {}).get(feature)
        if exp is None:
            continue
        sign, assets, horizons = exp
        if (assets and target not in assets) or (horizons and h not in horizons):
            continue
        rows.append({"target": target, "horizon": h, "model": model, "feature": feature, "expected_sign": sign,
                     "n_folds": len(g), "share_expected_sign": float((np.sign(g["coef"]) == sign).mean()),
                     "mean_coef": float(g["coef"].mean())})
    return pd.DataFrame(rows)
