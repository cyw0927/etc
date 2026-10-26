import altair as alt
import pandas as pd
import streamlit as st

import dash_data as dd

prices, _ = dd.prices()
if not prices:
    st.error("저장된 시장 데이터가 없습니다.", title="데이터 없음")
    st.stop()


@st.cache_data(ttl="10m")
def grid_returns() -> pd.DataFrame:
    """Daily RETURNS on a common Mon–Fri grid (BTC weekend moves fold into Monday)."""
    px, _ = dd.prices()
    start = min(p.index.min() for p in px.values())
    end = max(p.index.max() for p in px.values())
    grid = pd.bdate_range(start, end)
    out = {}
    for k, p in px.items():
        c = p["adj_close"].reindex(grid).ffill(limit=5).loc[: p.index.max()]
        out[k] = c.pct_change(fill_method=None)
    return pd.DataFrame(out)


rets = grid_returns()
st.caption("가격 수준이 아니라 **일간 수익률**의 상관계수입니다. 공통 평일 달력 기준이며, 거래 시간대가 다른 시장 간 "
           "동일 날짜 상관은 실제보다 낮게 나올 수 있습니다. 상관관계는 인과관계가 아닙니다.")

with st.container(border=True):
    st.subheader("상관관계 히트맵")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        assets = st.multiselect("자산", list(rets.columns), default=list(rets.columns))
        period = st.segmented_control("기간", ["60영업일", "1년", "3년", "10년"], default="1년")
    n = {"60영업일": 60, "1년": 260, "3년": 780, "10년": 2600}[period or "1년"]
    sub = rets[assets].iloc[-n:]
    corr = sub.corr(min_periods=n // 2)
    long = corr.reset_index(names="a").melt("a", var_name="b", value_name="corr")
    heat = alt.Chart(long).mark_rect().encode(
        x=alt.X("a:N", title=None, sort=assets), y=alt.Y("b:N", title=None, sort=assets),
        color=alt.Color("corr:Q", scale=alt.Scale(scheme="redblue", domain=[-1, 1], reverse=True)),
        tooltip=["a", "b", alt.Tooltip("corr:Q", format=".2f")])
    text = alt.Chart(long).mark_text(fontSize=11).encode(
        x=alt.X("a:N", sort=assets), y=alt.Y("b:N", sort=assets), text=alt.Text("corr:Q", format=".2f"))
    st.altair_chart(heat + text, alt="선택 기간 일간 수익률 상관계수 히트맵")
    st.caption(f"기간: {sub.index.min().date()} ~ {sub.index.max().date()}")

with st.container(border=True):
    st.subheader("이동 상관계수")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        a = st.selectbox("자산 A", list(rets.columns), index=list(rets.columns).index("QQQ"))
        b = st.selectbox("자산 B", list(rets.columns), index=list(rets.columns).index("BTC"))
        windows = st.pills("창 길이(영업일)", [30, 90, 180], selection_mode="multi", default=[90])
    frames = []
    for w in windows or [90]:
        rc = rets[a].rolling(w, min_periods=w // 2).corr(rets[b]).dropna()
        frames.append(pd.DataFrame({"date": rc.index, "window": f"{w}일", "corr": rc.values}))
    df = pd.concat(frames)
    st.altair_chart(alt.Chart(df).mark_line().encode(
        x=alt.X("date:T", title=None), y=alt.Y("corr:Q", scale=alt.Scale(domain=[-1, 1])), color="window:N"),
        alt=f"{a}와 {b}의 이동 상관계수")
