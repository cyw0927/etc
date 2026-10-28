"""Human-readable run report (Markdown) and console table."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gmia.models.registry import MODEL_LABELS



def _pct(x) -> str:
    return "—" if pd.isna(x) else f"{x * 100:.1f}%"


def _f(x, n=3) -> str:
    return "—" if pd.isna(x) else f"{x:.{n}f}"


def forecast_table(forecasts: list[dict]) -> str:
    lines = ["| 자산 | 기간 | 예측 기준일 | 선택 모델 | P(상승) | 홀드아웃 Brier (모델 / B1) | 홀드아웃 AUC | 신뢰도 |",
             "|---|---|---|---|---|---|---|---|"]
    for fc in forecasts:
        v = fc["verdict"]
        lines.append(
            f"| {fc['target']} | {fc['horizon']} {fc['horizon_unit']} | {fc['forecast_date']} | "
            f"{MODEL_LABELS.get(fc['selected_model'], fc['selected_model'])} | **{_pct(fc['p_up'])}** | "
            f"{_f(v['holdout_brier'], 4)} / {_f(v['holdout_brier_base_rate'], 4)} | {_f(v['holdout_auc'])} | "
            f"{fc['reliability'].split(' — ')[0]} |")
    return "\n".join(lines)


def model_table(summary: pd.DataFrame, target: str, h: int) -> str:
    s = summary[(summary["target"] == target) & (summary["horizon"] == h)]
    lines = ["| 구간 | 모델 | n | 상승비율 | Accuracy | Bal.Acc | AUC | Brier | LogLoss | ECE | 전략 누적(비용후) | 매수후보유 | 전략 MDD | 노출 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in s.iterrows():
        lines.append(
            f"| {r['kind']} | {MODEL_LABELS.get(r['model'], r['model'])} | {r['n']} | {_pct(r['up_rate'])} | "
            f"{_pct(r['accuracy'])} | {_pct(r['balanced_accuracy'])} | {_f(r['roc_auc'])} | {_f(r['brier'], 4)} | "
            f"{_f(r['log_loss'], 4)} | {_f(r['ece'])} | {_pct(r['strategy_total_return'])} | "
            f"{_pct(r['buy_hold_total_return'])} | {_pct(r['strategy_max_drawdown'])} | {_pct(r['exposure'])} |")
    return "\n".join(lines)


def significance_section(sig: pd.DataFrame, coefs: pd.DataFrame) -> list[str]:
    from gmia.evaluation.significance import sign_consistency

    n, q = len(sig), sig["fdr_q"].iloc[0]
    sup = sig[sig["supported"]]
    lines = ["## 사전 등록 판정 (docs/preregistration_v0.3.md)", "",
             f"- 검정 수: {n}개 (B1 제외 후보 × 자산 × 기간), Benjamini–Hochberg FDR q = {q}",
             f"- 홀드아웃 Brier가 B1보다 낮은 조합: {int((sig['mean_brier_diff'] < 0).sum())}개 · "
             f"보정 전 p < 0.05: {int((sig['p_one_sided'] < 0.05).sum())}개 · "
             f"BH 유의: {int(sig['bh_significant'].sum())}개 · **지지됨(BH 유의 + 검증도 B1보다 나음): {len(sup)}개**",
             "- 주의: 이 홀드아웃 기간의 집계 결과는 v0.2에서 이미 공개됐다. 지지된 결과도 전진 검증 전까지 잠정이다.", ""]
    if len(sup):
        lines += ["| 자산 | h | 모델 | 홀드아웃 Brier 차이 | HAC t | p(단측) | p(BH) |", "|---|---|---|---|---|---|---|"]
        for _, r in sup.sort_values("p_one_sided").iterrows():
            lines.append(f"| {r['target']} | {r['horizon']} | {MODEL_LABELS.get(r['model'], r['model'])} | "
                         f"{r['mean_brier_diff']:+.4f} | {r['t_stat']:.2f} | {r['p_one_sided']:.4f} | {r['p_bh_adjusted']:.3f} |")
        lines.append("")
    top = sig.sort_values("p_one_sided").head(10)
    lines += ["보정 전 p값이 가장 작은 10개 (참고):", "",
              "| 자산 | h | 모델 | Brier 차이 | p(단측) | p(BH) | 검증도 B1보다 나음 |", "|---|---|---|---|---|---|---|"]
    for _, r in top.iterrows():
        lines.append(f"| {r['target']} | {r['horizon']} | {MODEL_LABELS.get(r['model'], r['model'])} | "
                     f"{r['mean_brier_diff']:+.4f} | {r['p_one_sided']:.4f} | {r['p_bh_adjusted']:.3f} | "
                     f"{'예' if r['validation_beats_base_rate'] else '아니오'} |")
    lines.append("")
    if not coefs.empty:
        sc = sign_consistency(coefs)
        if not sc.empty:
            lines += ["### 가설 계수 부호 일치 (검증 폴드 중 사전 기대 부호와 같은 비율)", "",
                      "| 가설 | 특징 | 기대 부호 | 자산 | h | 일치 비율 | 평균 계수(표준화) |", "|---|---|---|---|---|---|---|"]
            for _, r in sc.iterrows():
                lines.append(f"| {MODEL_LABELS.get(r['model'], r['model'])} | {r['feature']} | {'+' if r['expected_sign'] > 0 else '−'} | "
                             f"{r['target']} | {r['horizon']} | {_pct(r['share_expected_sign'])} | {r['mean_coef']:+.3f} |")
            lines.append("")
    return lines


def write_report(out_dir: Path, forecasts: list[dict], summary: pd.DataFrame, run_meta: dict,
                 sig: pd.DataFrame | None = None, coefs: pd.DataFrame | None = None) -> None:
    parts = [
        f"# GMIA 실행 보고서 — run `{run_meta['run_id']}`",
        "",
        f"> {run_meta['disclaimer']}",
        "",
        f"- 생성: {run_meta['created_utc']} (UTC) · 코드 커밋: `{run_meta['git_commit']}`",
        f"- 금리 입력: {', '.join(run_meta['rates_used']) or '없음'} · 실시간 거시 입력: {', '.join(run_meta['macro_realtime_used']) or '없음'}",
    ]
    if run_meta.get("macro_note"):
        parts.append(f"- 주의: {run_meta['macro_note']}")
    if run_meta["skipped"]:
        parts.append(f"- 예측 불가/건너뜀: {run_meta['skipped']}")
    parts += ["", "## 최신 예측", "", forecast_table(forecasts), "",
              "- P(상승) = 예측 기준일 종가 대비 h봉 뒤 종가가 높을 확률(모델 출력). 주식·ETF·FX·원유는 거래일, BTC는 달력일.",
              "- 신뢰도는 홀드아웃(최근 2년, 모델 선택에 미사용) 성과와 다중비교 보정 검정으로 정한다. '보통(잠정)'이 최고 등급이다.", ""]
    if sig is not None and not sig.empty:
        parts += significance_section(sig, coefs if coefs is not None else pd.DataFrame())
    parts += ["## 모델별 성능 (검증 = 워크포워드 검증 구간 합산, holdout = 최근 2년)", ""]
    for fc in forecasts:
        v = fc["verdict"]
        parts += [f"### {fc['target']} · {fc['horizon']} {fc['horizon_unit']}", "",
                  f"- 학습 기간(최종 예측용): {fc['train_start']} ~ {fc['train_end']} ({fc['n_train']}개 표본), 데이터 기준일 {fc['data_last_date']}",
                  f"- 선택 모델: {MODEL_LABELS.get(v['selected_model'], v['selected_model'])} (검증 Brier 최소)"
                  + (f" · 홀드아웃 B1 대비 p(단측) {v['selected_p_one_sided']:.3f}, p(BH) {v['selected_p_bh']:.3f}"
                     if v.get("selected_p_one_sided") is not None else ""),
                  f"- 홀드아웃에서 B1 대비 개선: {'예' if v['holdout_beats_base_rate'] else '**아니오**'} · B2 대비 개선: {'예' if v['holdout_beats_momentum'] else '**아니오**'}",
                  f"- 검증 폴드 중 B1보다 Brier가 좋았던 비율: {_pct(v['share_val_folds_beating_base_rate'])} ({v['n_validation_folds']}개 폴드)",
                  f"- 실패 구간(AUC<0.5 또는 B1보다 나쁨): {', '.join(v['failed_folds']) or '없음'}",
                  f"- 입력 결측(예측 시점): {', '.join(fc['missing_features']) or '없음'}", "",
                  model_table(summary, fc["target"], fc["horizon"]), ""]
    (out_dir / "report.md").write_text("\n".join(parts), encoding="utf-8")


def console_summary(forecasts: list[dict]) -> str:
    rows = []
    for fc in forecasts:
        v = fc["verdict"]
        rows.append({"target": fc["target"], "h": fc["horizon"], "asof": fc["forecast_date"],
                     "model": fc["selected_model"], "P(up)": round(fc["p_up"], 3),
                     "hold_brier": round(v["holdout_brier"], 4), "hold_brier_B1": round(v["holdout_brier_base_rate"], 4),
                     "hold_auc": round(v["holdout_auc"], 3), "beats_B1": v["holdout_beats_base_rate"],
                     "reliability": fc["reliability"].split(" — ")[0]})
    return pd.DataFrame(rows).to_string(index=False)
