import altair as alt
import pandas as pd
import streamlit as st

import dash_data as dd

if not dd.has_run():
    st.error("모델 실행 결과가 없습니다. `python scripts/run_all.py`를 먼저 실행하세요.", title="결과 없음")
    st.stop()

art = dd.run_artifacts()
summary, folds, rel, curves = art["summary"], art["folds"], art["reliability"], art["curves"]
cfg = dd.config()

with st.container(horizontal=True, vertical_alignment="bottom"):
    target = st.selectbox("자산", sorted(summary["target"].unique()))
    horizon = st.segmented_control("예측 기간(봉)", sorted(summary["horizon"].unique()), default=5)
    kind = st.segmented_control("구간", ["validation", "holdout"], default="holdout",
                                format_func={"validation": "워크포워드 검증", "holdout": "최근 2년 홀드아웃"}.get)
horizon, kind = horizon or 5, kind or "holdout"
fc = next(f for f in art["forecasts"] if f["target"] == target and f["horizon"] == horizon)
v = fc["verdict"]

s = summary[(summary["target"] == target) & (summary["horizon"] == horizon) & (summary["kind"] == kind)].copy()
s["모델"] = s["model"].map(dd.MODEL_LABELS)
s["선택"] = s["model"] == v["selected_model"]

with st.container(horizontal=True):
    st.metric("선택 모델", dd.MODEL_LABELS[v["selected_model"]], border=True)
    st.metric("홀드아웃 Brier (모델 / 기준)", f"{v['holdout_brier']:.4f} / {v['holdout_brier_base_rate']:.4f}", border=True)
    st.metric("검증 폴드 중 기준모델 초과 비율",
              "—" if pd.isna(v["share_val_folds_beating_base_rate"]) else f"{v['share_val_folds_beating_base_rate']:.0%}",
              border=True)
if not v["holdout_beats_base_rate"]:
    st.warning("선택된 모델이 최근 2년 홀드아웃에서 기준모델(과거 상승비율)보다 낫지 않습니다.", title="기준모델 미달")

with st.container(border=True):
    st.subheader("모델별 예측 성능")
    st.dataframe(
        s[["모델", "선택", "n", "up_rate", "accuracy", "balanced_accuracy", "roc_auc", "brier", "log_loss", "ece"]],
        hide_index=True, alt="모델별 분류 성능",
        column_config={"up_rate": st.column_config.NumberColumn("실제 상승비율", format="percent"),
                       "accuracy": st.column_config.NumberColumn("Accuracy", format="percent"),
                       "balanced_accuracy": st.column_config.NumberColumn("Balanced acc.", format="percent"),
                       "roc_auc": st.column_config.NumberColumn("AUC", format="%.3f"),
                       "brier": st.column_config.NumberColumn("Brier", format="%.4f"),
                       "log_loss": st.column_config.NumberColumn("Log loss", format="%.4f"),
                       "ece": st.column_config.NumberColumn("ECE(보정오차)", format="%.3f")})

col1, col2 = st.columns(2)
with col1, st.container(border=True, height="stretch"):
    st.subheader("단순 규칙 누적 수익률")
    st.caption(f"P(상승) > {cfg['strategy']['threshold']}이면 보유, 아니면 현금. 신호 다음 봉 종가에 체결"
               f"(지연 {cfg['strategy']['execution_lag_bars']}봉), 회전당 비용 {cfg['strategy']['cost_bps']}bp. "
               "예측 성능과 별개인 참고 지표입니다.")
    c = curves[(curves["target"] == target) & (curves["horizon"] == horizon) & (curves["kind"] == kind)]
    models = st.pills("모델", list(dd.MODEL_LABELS), default=[v["selected_model"], "logistic_regression"],
                      selection_mode="multi", format_func=dd.MODEL_LABELS.get)
    lines = [c[c["model"] == m][["date", "strategy_net"]].assign(series=dd.MODEL_LABELS[m]) for m in models or []]
    bh = c[c["model"] == "baseline_base_rate"][["date", "buy_and_hold"]].rename(columns={"buy_and_hold": "strategy_net"})
    lines.append(bh.assign(series="매수 후 보유"))
    df = pd.concat(lines)
    st.altair_chart(alt.Chart(df).mark_line().encode(
        x=alt.X("date:T", title=None), y=alt.Y("strategy_net:Q", title="누적 가치 (시작 = 1)"), color="series:N"),
        alt="모델 신호 규칙과 매수 후 보유의 누적 가치")
    st.dataframe(s[["모델", "strategy_total_return", "strategy_max_drawdown", "strategy_ann_vol", "exposure",
                    "buy_hold_total_return", "buy_hold_max_drawdown"]], hide_index=True, alt="전략 성과 요약",
                 column_config={k: st.column_config.NumberColumn(label, format="percent") for k, label in [
                     ("strategy_total_return", "누적(비용후)"), ("strategy_max_drawdown", "MDD"),
                     ("strategy_ann_vol", "연변동성"), ("exposure", "보유비중"),
                     ("buy_hold_total_return", "보유 누적"), ("buy_hold_max_drawdown", "보유 MDD")]})

with col2, st.container(border=True, height="stretch"):
    st.subheader("확률 보정 (reliability)")
    st.caption("점선(대각선)에 가까울수록 '70%라고 말하면 실제로 70% 오르는' 잘 보정된 확률입니다.")
    r = rel[(rel["target"] == target) & (rel["horizon"] == horizon) & (rel["kind"] == kind)].copy()
    r["모델"] = r["model"].map(dd.MODEL_LABELS)
    diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(strokeDash=[4, 4], color="gray").encode(x="x", y="y")
    pts = alt.Chart(r).mark_line(point=True).encode(
        x=alt.X("mean_prob:Q", title="예측 확률", scale=alt.Scale(domain=[0, 1])),
        y=alt.Y("observed_up_rate:Q", title="실제 상승 비율", scale=alt.Scale(domain=[0, 1])),
        color="모델:N", tooltip=["모델", "count", alt.Tooltip("mean_prob:Q", format=".2f"),
                               alt.Tooltip("observed_up_rate:Q", format=".2f")])
    st.altair_chart(diag + pts, alt="모델별 확률 보정 곡선")

with st.container(border=True):
    st.subheader("시기별 성능 (워크포워드 검증 폴드 + 홀드아웃)")
    f = folds[(folds["target"] == target) & (folds["horizon"] == horizon)].copy()
    f["모델"] = f["model"].map(dd.MODEL_LABELS)
    metric = st.segmented_control("지표", ["brier", "roc_auc"], default="brier",
                                  format_func={"brier": "Brier (낮을수록 좋음)", "roc_auc": "AUC (0.5 = 무작위)"}.get)
    metric = metric or "brier"
    st.altair_chart(alt.Chart(f).mark_line(point=True).encode(
        x=alt.X("test_start:T", title="검증 구간 시작"), y=alt.Y(f"{metric}:Q", scale=alt.Scale(zero=False)),
        color="모델:N", tooltip=["fold", "모델", alt.Tooltip(f"{metric}:Q", format=".4f")]),
        alt="폴드별 성능 추이")
    st.markdown(f"**실패한 시기** (선택 모델의 AUC<0.5 또는 기준모델보다 나쁜 Brier): "
                f"{', '.join(v['failed_folds']) or '없음'}")
