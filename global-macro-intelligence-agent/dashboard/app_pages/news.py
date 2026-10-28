import streamlit as st

from gmia.news import SOURCE_POLICY

st.info(
    "국제정세 뉴스 수집·분류 모듈은 아직 구현되지 않았습니다(Phase 3). 이 화면에 표시할 실제 기사 데이터가 없으며, "
    "예시 기사나 가짜 분류 결과를 보여주지 않습니다.",
    title="추후 구현 — 데이터 없음",
)

with st.container(border=True):
    st.subheader("설계된 출처 정책")
    st.markdown("**우선 해외 언론:** " + ", ".join(SOURCE_POLICY["preferred_outlets"]))
    st.markdown("**우선 1차 자료:** " + ", ".join(SOURCE_POLICY["preferred_primary"]))
    st.markdown("**기본 제외:** " + ", ".join(SOURCE_POLICY["excluded_by_default"]))
    st.markdown("**허용되는 한국 자료:** " + ", ".join(SOURCE_POLICY["allowed_korean"]))
    st.markdown("**접근 규칙:** " + ", ".join(SOURCE_POLICY["access_rules"]))

with st.container(border=True):
    st.subheader("예측모델과의 관계")
    st.markdown(
        "- 뉴스 점수는 **예측모델의 학습변수로 쓰지 않습니다.** 과거 시점에 실제로 공개됐던 기사(발표 시각 포함)를 "
        "확보해 백테스트할 수 있을 때까지 유지합니다.\n"
        "- 구현 후에도 뉴스 에이전트는 통계모델 확률 옆에 정성적 설명만 덧붙이며, 확률을 바꾸지 못합니다.\n"
        "- 영향은 국가·산업·자산별로 긍정/부정/모호를 따로 판정하고, 사실·당사국 주장·언론 해석·AI 추론을 구분합니다."
    )
