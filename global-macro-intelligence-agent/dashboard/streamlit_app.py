"""GMIA dashboard. Run: streamlit run dashboard/streamlit_app.py"""

import streamlit as st

from gmia import DISCLAIMER

st.set_page_config(page_title="GMIA", page_icon=":material/public:", layout="wide")

page = st.navigation(
    [
        st.Page("app_pages/market.py", title="시장 현황", icon=":material/monitoring:"),
        st.Page("app_pages/correlation.py", title="자산 상관관계", icon=":material/grid_on:"),
        st.Page("app_pages/forecast.py", title="예측모델", icon=":material/insights:"),
        st.Page("app_pages/backtest.py", title="백테스트", icon=":material/history:"),
        st.Page("app_pages/news.py", title="국제정세", icon=":material/newspaper:"),
    ],
    position="top",
)

st.title(page.title)
st.caption(DISCLAIMER)
page.run()
