"""Latest-data forecast with the model chosen on walk-forward validation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from gmia.models.registry import make_models


def reliability_label(verdict: dict, min_auc: float) -> str:
    if verdict["selected_model"] == "baseline_base_rate":
        return ("참고 신뢰도 낮음 — 학습 모델이 검증에서 기준모델을 넘지 못해 과거 상승비율을 그대로 출력함 "
                "(방향 예측력 없음)")
    if not verdict["holdout_beats_base_rate"]:
        return "참고 신뢰도 낮음 — 최근 홀드아웃에서 기준모델(과거 상승비율)보다 나쁨"
    if not np.isfinite(verdict["holdout_auc"]) or verdict["holdout_auc"] < min_auc:
        return f"참고 신뢰도 낮음 — 변별력 약함 (홀드아웃 AUC {verdict['holdout_auc']:.3f} < {min_auc})"
    return "참고 신뢰도 보통 — 홀드아웃에서 기준모델보다 개선됐지만 단일 기간 검증이며 미래를 보장하지 않음"


def latest_forecast(ds: pd.DataFrame, feature_cols: list[str], h: int, verdict: dict, cfg: dict) -> dict:
    lab = ds[ds[f"y_{h}"].notna()]
    x_last = ds[feature_cols].iloc[[-1]]
    asof = ds.index[-1]
    probs = {}
    for model in make_models(h, cfg["modeling"]["random_state"]):
        model.fit(lab[feature_cols], lab[f"y_{h}"])
        probs[model.name] = float(model.predict_proba(x_last)[0])
    missing = [c for c in feature_cols if pd.isna(x_last[c].iloc[0])]
    return {
        "horizon": h,
        "forecast_date": asof.strftime("%Y-%m-%d"),
        "selected_model": verdict["selected_model"],
        "p_up": probs[verdict["selected_model"]],
        "p_up_all_models": probs,
        "train_start": lab.index.min().strftime("%Y-%m-%d"),
        "train_end": lab.index.max().strftime("%Y-%m-%d"),
        "n_train": int(len(lab)),
        "feature_completeness": 1 - len(missing) / len(feature_cols),
        "missing_features": missing,
        "reliability": reliability_label(verdict, cfg["reliability"]["min_auc"]),
    }
