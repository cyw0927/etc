import altair as alt
import pandas as pd
import streamlit as st

import dash_data as dd

prices, metas = dd.prices()
if not prices:
    st.error("저장된 시장 데이터가 없습니다. `python scripts/fetch_data.py`를 먼저 실행하세요.", title="데이터 없음")
    st.stop()


def ret(c: pd.Series, n: int) -> float:
    c = c.dropna()
    return c.iloc[-1] / c.iloc[-1 - n] - 1 if len(c) > n else float("nan")


rows = []
for key, px in prices.items():
    c = px["adj_close"].dropna()
    m = metas[key]
    rows.append({"자산": key, "이름": m["name"], "유형": m["price_type"], "통화": m["currency"],
                 "기준일": c.index[-1].date(), "종가": px["close"].dropna().iloc[-1],
                 "1일": ret(c, 1), "5일": ret(c, 5), "20일": ret(c, 20), "60일": ret(c, 60),
                 "추이(120봉)": c.iloc[-120:].tolist()})
table = pd.DataFrame(rows)

with st.container(border=True):
    st.subheader("최근 수익률")
    st.caption("수익률은 각 자산의 현지 통화·자체 거래일 기준(수정종가). BTC는 달력일, FX는 상승 = 달러 강세.")
    st.dataframe(
        table, hide_index=True, alt="자산별 최근 수익률",
        column_config={
            "1일": st.column_config.NumberColumn(format="percent"),
            "5일": st.column_config.NumberColumn(format="percent"),
            "20일": st.column_config.NumberColumn(format="percent"),
            "60일": st.column_config.NumberColumn(format="percent"),
            "종가": st.column_config.NumberColumn(format="%.2f"),
            "추이(120봉)": st.column_config.LineChartColumn(),
        },
    )

with st.container(border=True):
    st.subheader("가격 추이 (시작점 = 100)")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        chosen = st.multiselect("자산", list(prices), default=["SPY", "KOSPI", "GOLD", "BTC"])
        period = st.segmented_control("기간", ["3개월", "1년", "3년", "10년"], default="1년")
    days = {"3개월": 92, "1년": 365, "3년": 3 * 365, "10년": 3652}[period or "1년"]
    frames = []
    for k in chosen:
        c = prices[k]["adj_close"].dropna()
        c = c[c.index >= c.index[-1] - pd.Timedelta(days=days)]
        frames.append(pd.DataFrame({"date": c.index, "자산": k, "지수화": c.values / c.iloc[0] * 100}))
    if frames:
        df = pd.concat(frames)
        chart = alt.Chart(df).mark_line().encode(
            x=alt.X("date:T", title=None), y=alt.Y("지수화:Q", scale=alt.Scale(zero=False)), color="자산:N",
            tooltip=["자산", alt.Tooltip("date:T"), alt.Tooltip("지수화:Q", format=".1f")])
        st.altair_chart(chart, alt="선택 자산의 지수화 가격 추이")

rates, rmeta = dd.fred_series("rates")
with st.container(border=True):
    st.subheader("미국 금리 (FRED)")
    if {"DGS2", "DGS10"} <= set(rates):
        r = pd.concat([rates["DGS2"].rename("2년"), rates["DGS10"].rename("10년")], axis=1).dropna()
        r["10년-2년 (%p)"] = r["10년"] - r["2년"]
        if "DFF" in rates:
            r = r.join(rates["DFF"].rename("연방기금 실효금리"), how="left")
        r = r[r.index >= r.index[-1] - pd.Timedelta(days=5 * 365)]
        last = r.iloc[-1]
        with st.container(horizontal=True):
            st.metric("미 2년물", f"{last['2년']:.2f}%", border=True)
            st.metric("미 10년물", f"{last['10년']:.2f}%", border=True)
            st.metric("10년-2년", f"{last['10년-2년 (%p)']:+.2f}%p", border=True)
        long = r.reset_index().melt("date", var_name="series", value_name="value")
        st.altair_chart(alt.Chart(long).mark_line().encode(
            x=alt.X("date:T", title=None), y=alt.Y("value:Q", title="% / %p"), color="series:N"),
            alt="미국 2년·10년 국채금리와 장단기 금리차, 최근 5년")
        st.caption(f"기준일 {r.index[-1].date()} · 출처: FRED (금리 수준은 %, 금리차는 %p)")
    else:
        st.warning("FRED 금리 데이터가 없습니다.")

macro, mmeta = dd.fred_series("macro")
with st.expander("미국 거시지표 (분석용 · 최신 수정치 · 모델 입력 아님)"):
    st.caption("빈티지(발표 시점) 데이터가 없어 수정치가 섞여 있습니다. 백테스트·예측 모델에는 사용하지 않습니다. "
               "FRED_API_KEY를 설정하면 실시간 빈티지로 모델 입력에 포함됩니다.")
    if macro:
        mrows = []
        for sid, s in macro.items():
            yoy = s.iloc[-1] / s.iloc[-13] - 1 if len(s) > 13 else float("nan")
            mrows.append({"지표": sid, "설명": mmeta[sid]["description"], "최근 기준월": s.index[-1].date(),
                          "최근값": s.iloc[-1], "전년비": yoy})
        st.dataframe(pd.DataFrame(mrows), hide_index=True, alt="미국 거시지표 최신값",
                     column_config={"전년비": st.column_config.NumberColumn(format="percent")})
