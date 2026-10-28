"""Real point-in-time forecasts, scored only after each h-bar label has matured."""

import pandas as pd
import streamlit as st

from gmia.config import load_config
from gmia.evaluation.forward import (
    ASSETS, HORIZONS, MIN_PAIRS, MIN_SPAN_DAYS, FDR_Q, forward_significance,
    ledger_path, read_forecasts, read_scores,
)
from gmia.models.registry import MODEL_LABELS

cfg = load_config()
path = ledger_path(cfg)

st.caption("v0.4: 매 실행 당시 최초 예측만 보존하고, 만기 결과가 나온 뒤 실제 수익률로 채점합니다. "
           "기존 2년 홀드아웃은 전진 검증이 아닙니다.")
st.code("python scripts/score_ledger.py", language="powershell")

if not path.exists():
    st.info("전진 검증 장부가 아직 없습니다. python scripts/run_all.py 를 실행해 최초 예측을 기록하세요.")
    st.stop()

forecast = read_forecasts(path)
scored = read_scores(path)
sig = forward_significance(scored)

with st.container(horizontal=True):
    st.metric("최초 예측 기록", f"{len(forecast):,}", border=True)
    st.metric("만기 채점", f"{len(scored):,}", border=True)
    st.metric("검정 가능", f"{int(sig['enough_data'].sum())} / {len(sig)}", border=True)
    st.metric("지지된 후보", int(sig["supported"].sum()), border=True)

st.warning(
    f"사전 등록: 후보/B1 대응 예측 {MIN_PAIRS}쌍 이상 및 {MIN_SPAN_DAYS}일 이상 필요. "
    f"HAC lag=h, 고정 252개 비교에 BH-FDR q={FDR_Q:.2f}. "
    "표본 부족은 실패나 성공이 아니라 검정 불가 상태입니다."
)

asset = st.selectbox("자산", ASSETS)
h = st.segmented_control("예측 기간(봉)", HORIZONS, default=5) or 5

f = forecast[(forecast["asset"] == asset) & (forecast["horizon"] == h)].copy()
s = scored[(scored["asset"] == asset) & (scored["horizon"] == h)].copy()
x = sig[(sig["asset"] == asset) & (sig["horizon"] == h)].copy()

if f.empty:
    st.info("이 자산의 예측 기록이 없습니다.")
else:
    by_model = f.groupby("model", as_index=False).agg(
        n_issued=("forecast_date", "count"),
        first_date=("forecast_date", "min"),
        last_date=("forecast_date", "max"),
    )
    if not s.empty:
        by_model = by_model.merge(
            s.groupby("model", as_index=False).agg(n_scored=("forecast_date", "count")),
            on="model", how="left")
    else:
        by_model["n_scored"] = 0
    by_model["n_scored"] = by_model["n_scored"].fillna(0).astype(int)
    by_model["모델"] = by_model["model"].map(MODEL_LABELS)
    st.subheader("후보별 전진 예측·채점 현황")
    st.dataframe(by_model[["모델", "n_issued", "n_scored", "first_date", "last_date"]],
                 hide_index=True, alt="후보별 신규 예측 기록 및 채점 건수")

st.subheader("기준모델 대비 전진 검정 (현재 누적 표본)")
x["모델"] = x["model"].map(MODEL_LABELS)
st.dataframe(x[["모델", "n", "span_days", "brier", "brier_base",
                "mean_brier_diff", "p_one_sided", "p_bh_adjusted",
                "enough_data", "supported"]],
             hide_index=True, alt="기준모델 B1 대비 전진 검정",
             column_config={
                 "brier": st.column_config.NumberColumn("후보 Brier", format="%.4f"),
                 "brier_base": st.column_config.NumberColumn("B1 Brier", format="%.4f"),
                 "mean_brier_diff": st.column_config.NumberColumn("차이 (음수가 개선)", format="%+.4f"),
                 "p_bh_adjusted": st.column_config.NumberColumn("BH 조정 p", format="%.4f"),
                 "p_one_sided": st.column_config.NumberColumn("단측 p", format="%.4f"),
             })
if not s.empty:
    st.subheader("최근 채점 기록 (원자료 확인 가능)")
    recent = s.sort_values("forecast_date", ascending=False).head(100).copy()
    recent["모델"] = recent["model"].map(MODEL_LABELS)
    st.dataframe(recent[["forecast_date", "label_end", "모델", "probability",
                        "y", "realized_return", "recorded_utc", "scored_utc"]],
                 hide_index=True, alt="전진 예측과 실제 결과 비교")
else:
    st.info("아직 만기 채점된 예측이 없습니다. 실제 시간이 경과하고 새 데이터를 받은 뒤 채점하세요.")

st.caption(f"로컬 장부 경로: {path}. Git에 올리지 않으며 DB는 최초 예측과 최초 채점을 변경하지 않습니다.")
