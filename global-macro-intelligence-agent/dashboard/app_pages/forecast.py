import pandas as pd
import streamlit as st

import dash_data as dd

if not dd.has_run():
    st.error("모델 실행 결과가 없습니다. `python scripts/run_all.py`를 먼저 실행하세요.", title="결과 없음")
    st.stop()

art = dd.run_artifacts()
fcs, meta = art["forecasts"], art["meta"]

st.caption(f"실행 `{meta['run_id']}` · 생성 {meta['created_utc']} UTC · 코드 커밋 `{(meta.get('git_commit') or '')[:8]}`")
n_low = sum(fc["reliability"].startswith("참고 신뢰도 낮음") for fc in fcs)
n_base = sum(fc["selected_model"] == "baseline_base_rate" for fc in fcs)
if n_low:
    st.warning(
        f"{len(fcs)}개 예측 중 {n_low}개가 '참고 신뢰도 낮음'입니다. 그중 {n_base}개는 학습 모델이 검증 구간에서 "
        "기준모델(과거 상승비율)을 넘지 못해 과거 상승비율을 그대로 출력합니다 — 방향 예측력이 확인되지 않았다는 뜻입니다.",
        title="학습 모델이 기준모델보다 낫지 않습니다")
if meta.get("macro_note"):
    st.info(meta["macro_note"], title="거시지표 미사용")

rows = []
for fc in fcs:
    v = fc["verdict"]
    rows.append({
        "자산": fc["target"], "기간": f"{fc['horizon']} {fc['horizon_unit']}", "예측 기준일": fc["forecast_date"],
        "P(상승)": fc["p_up"], "사용 모델": dd.MODEL_LABELS.get(fc["selected_model"], fc["selected_model"]),
        "학습기간": f"{fc['train_start']} ~ {fc['train_end']}", "홀드아웃 Brier": v["holdout_brier"],
        "기준모델 Brier": v["holdout_brier_base_rate"], "홀드아웃 AUC": v["holdout_auc"],
        "기준모델 대비": "개선" if v["holdout_beats_base_rate"] else "미달/동일",
        "p(BH)": v.get("selected_p_bh"),
        "입력 완전성": fc["feature_completeness"], "신뢰도": fc["reliability"],
    })
st.dataframe(
    pd.DataFrame(rows), hide_index=True, alt="자산별 5일·20일 상승확률과 검증 성능",
    column_config={
        "P(상승)": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
        "홀드아웃 Brier": st.column_config.NumberColumn(format="%.4f"),
        "기준모델 Brier": st.column_config.NumberColumn(format="%.4f"),
        "홀드아웃 AUC": st.column_config.NumberColumn(format="%.3f"),
        "p(BH)": st.column_config.NumberColumn(format="%.3f", help="홀드아웃에서 B1보다 낫다는 검정의 다중비교 보정 p값"),
        "입력 완전성": st.column_config.NumberColumn(format="percent"),
        "신뢰도": st.column_config.TextColumn(width="large"),
    },
)
st.caption("P(상승): 예측 기준일 종가 대비 h봉 뒤 종가가 더 높을 확률. 홀드아웃 = 최근 2년, 모델 선택에 쓰지 않은 구간. "
           "Brier는 낮을수록 좋고, 항상 0.25 근처인 기준모델과 비교해야 의미가 있습니다.")

with st.container(border=True):
    st.subheader("자산별 상세")
    target = st.selectbox("자산", sorted({fc["target"] for fc in fcs}))
    for fc in [f for f in fcs if f["target"] == target]:
        st.markdown(f"**{fc['horizon']} {fc['horizon_unit']}** · {fc['name']} ({fc['ticker']}) — {fc['price_type']}")
        probs = pd.DataFrame([{"모델": dd.MODEL_LABELS.get(k, k), "P(상승)": p, "선택": k == fc["selected_model"]}
                              for k, p in fc["p_up_all_models"].items()])
        st.dataframe(probs, hide_index=True, alt=f"{target} {fc['horizon']}봉 모델별 확률",
                     column_config={"P(상승)": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
        st.caption(f"데이터 기준일 {fc['data_last_date']} · 입력변수 {fc['n_features']}개 · "
                   f"예측 시점 결측: {', '.join(fc['missing_features']) or '없음'}")
