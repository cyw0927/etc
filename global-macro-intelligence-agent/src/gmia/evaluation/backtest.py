"""Walk-forward evaluation of all candidate models for one (target, horizon).

Model selection uses the pooled walk-forward VALIDATION predictions only. The holdout (most recent
period) is scored once for every model and reported as-is, including when it is worse than the baselines.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gmia.evaluation.metrics import classification_metrics, reliability_table
from gmia.evaluation.splits import make_folds
from gmia.evaluation.strategy import long_flat_backtest
from gmia.models.registry import BASELINES, make_models


class InsufficientHistory(ValueError):
    pass


def bars_per_year(index: pd.DatetimeIndex) -> float:
    span_years = (index.max() - index.min()).days / 365.25
    return len(index) / span_years if span_years > 0 else 252.0


def run_walk_forward(ds: pd.DataFrame, feature_cols: list[str], h: int, cfg: dict) -> dict:
    v, s = cfg["validation"], cfg["strategy"]
    lab = ds[ds[f"y_{h}"].notna()]
    folds = make_folds(lab[f"label_end_{h}"], v["min_train_years"], v["val_block_years"], v["holdout_years"])
    if not any(f.kind == "validation" for f in folds) or not any(f.kind == "holdout" for f in folds):
        raise InsufficientHistory(f"not enough history for walk-forward validation ({len(lab)} labelled rows)")

    X, y = lab[feature_cols], lab[f"y_{h}"]
    preds, fold_rows = [], []
    for fold in folds:
        for model in make_models(h, cfg["modeling"]["random_state"]):
            model.fit(X.loc[fold.train_index], y.loc[fold.train_index])
            p = model.predict_proba(X.loc[fold.test_index])
            preds.append(pd.DataFrame({
                "date": fold.test_index, "fold": fold.name, "kind": fold.kind, "model": model.name, "p": p,
                "y": y.loc[fold.test_index].values, "fwd_ret": lab.loc[fold.test_index, f"fwd_ret_{h}"].values,
                "ret_next_1": lab.loc[fold.test_index, "ret_next_1"].values,
            }))
            fold_rows.append({**fold.describe(), "model": model.name,
                              **classification_metrics(y.loc[fold.test_index], p)})
    preds = pd.concat(preds, ignore_index=True)
    fold_metrics = pd.DataFrame(fold_rows)

    bpy = bars_per_year(lab.index)
    summary_rows, reliab, curves = [], [], []
    for (kind, model), g in preds.groupby(["kind", "model"], sort=False):
        g = g.sort_values("date")
        m = classification_metrics(g["y"], g["p"])
        strat, curve = long_flat_backtest(
            g.set_index("date")["p"], g.set_index("date")["ret_next_1"],
            s["threshold"], s["execution_lag_bars"], s["cost_bps"], bpy)
        summary_rows.append({"kind": kind, "model": model, "period_start": g["date"].min(),
                             "period_end": g["date"].max(), **m, **strat})
        r = reliability_table(g["y"], g["p"])
        r.insert(0, "model", model)
        r.insert(0, "kind", kind)
        reliab.append(r)
        curve = curve.reset_index().rename(columns={"index": "date"})
        curve.insert(0, "model", model)
        curve.insert(0, "kind", kind)
        curves.append(curve)
    summary = pd.DataFrame(summary_rows)

    val = summary[summary["kind"] == "validation"].set_index("model")
    hold = summary[summary["kind"] == "holdout"].set_index("model")
    metric = v.get("selection_metric", "brier")
    selected = str(val[metric].idxmin())

    vf = fold_metrics[fold_metrics["kind"] == "validation"].pivot(index="fold", columns="model", values="brier")
    stability = float((vf[selected] < vf["baseline_base_rate"]).mean()) if selected != "baseline_base_rate" else np.nan
    failed = fold_metrics[(fold_metrics["model"] == selected) & (
        (fold_metrics["roc_auc"] < 0.5) | (fold_metrics["brier"] > fold_metrics["fold"].map(
            fold_metrics[fold_metrics["model"] == "baseline_base_rate"].set_index("fold")["brier"])))]

    verdict = {
        "selected_model": selected,
        "selected_is_baseline": selected in BASELINES,
        "validation_brier": float(val.loc[selected, "brier"]),
        "validation_brier_base_rate": float(val.loc["baseline_base_rate", "brier"]),
        "holdout_brier": float(hold.loc[selected, "brier"]),
        "holdout_brier_base_rate": float(hold.loc["baseline_base_rate", "brier"]),
        "holdout_brier_momentum": float(hold.loc["baseline_momentum", "brier"]),
        "holdout_auc": float(hold.loc[selected, "roc_auc"]),
        "holdout_beats_base_rate": bool(hold.loc[selected, "brier"] < hold.loc["baseline_base_rate", "brier"]),
        "holdout_beats_momentum": bool(hold.loc[selected, "brier"] < hold.loc["baseline_momentum", "brier"]),
        "share_val_folds_beating_base_rate": stability,
        "failed_folds": failed["fold"].tolist(),
        "n_validation_folds": int((fold_metrics[fold_metrics["model"] == selected]["kind"] == "validation").sum()),
    }
    return {
        "folds": [f.describe() for f in folds],
        "fold_metrics": fold_metrics, "summary": summary, "predictions": preds,
        "reliability": pd.concat(reliab, ignore_index=True), "curves": pd.concat(curves, ignore_index=True),
        "verdict": verdict, "bars_per_year": bpy,
    }
