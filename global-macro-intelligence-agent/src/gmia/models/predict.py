"""Latest-data forecast with the model chosen on walk-forward validation."""

from __future__ import annotations

import numpy as np
import pandas as pd

from gmia.models.registry import make_models, required_columns


def reliability_label(verdict: dict, min_auc: float) -> str:
    if verdict["selected_model"] == "baseline_base_rate":
        return ("참고 신뢰도 낮음 — 학습 모델이 검증에서 기준모델을 넘지 못해 과거 상승비율을 그대로 출력함 "
                "(방향 예측력 없음)")
    if not verdict["holdout_beats_base_rate"]:
        return "참고 신뢰도 낮음 — 최근 홀드아웃에서 기준모델(과거 상승비율)보다 나쁨"
    if not np.isfinite(verdict["holdout_auc"]) or verdict["holdout_auc"] < min_auc:
        return f"참고 신뢰도 낮음 — 변별력 약함 (홀드아웃 AUC {verdict['holdout_auc']:.3f} < {min_auc})"
    if not verdict.get("selected_supported", False):
        return "참고 신뢰도 낮음 — 기준모델 대비 개선이 다중비교 보정 후 통계적으로 유의하지 않음"
    return ("참고 신뢰도 보통(잠정) — 사전 등록 기준을 통과했지만 홀드아웃 재사용 문제가 있어 "
            "전진 검증 전까지 잠정 결과")


def latest_forecast(ds: pd.DataFrame, feature_cols: list[str], h: int, verdict: dict, cfg: dict) -> dict:
    lab = ds[ds[f"y_{h}"].notna()]
    m_cfg = cfg["modeling"]
    model_kw = {"random_state": m_cfg["random_state"], "hypotheses": m_cfg.get("hypotheses", True),
                "calibrated": m_cfg.get("calibrated", True), "available": set(ds.columns)}
    models = make_models(h, feature_cols, **model_kw)
    cols = required_columns(models)
    x_last = ds[cols].iloc[[-1]]
    asof = ds.index[-1]
    probs, selected = {}, None
    for model in models:
        model.fit(lab[cols], lab[f"y_{h}"], label_end=lab[f"label_end_{h}"])
        probs[model.name] = float(model.predict_proba(x_last)[0])
        if model.name == verdict["selected_model"]:
            selected = model
    used = selected.columns
    missing = [c for c in used if pd.isna(x_last[c].iloc[0])]
    return {
        "horizon": h,
        "forecast_date": asof.strftime("%Y-%m-%d"),
        "selected_model": verdict["selected_model"],
        "p_up": probs[verdict["selected_model"]],
        "p_up_all_models": probs,
        "train_start": lab.index.min().strftime("%Y-%m-%d"),
        "train_end": lab.index.max().strftime("%Y-%m-%d"),
        "n_train": int(len(lab)),
        "selected_features": list(used),
        "feature_completeness": 1 - len(missing) / len(used) if used else 1.0,
        "missing_features": missing,
    }
