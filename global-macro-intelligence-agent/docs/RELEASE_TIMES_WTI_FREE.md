# 공식 발표 시각 대조와 무료 WTI 선물 자료

## 거시 지표와 전진 예측

기존 사전등록 및 장부와 별개로 `preregistration_release_checked.md`를 등록했다. 공식 발표문 또는 공식 일정의 2026년 9월 지표 발표 기준시각(미국 동부시간)은 CPI 10월 14일 08:30, 실업률 10월 2일 08:30, 산업생산 10월 16일 09:15, M2 10월 27일 13:00이다. CPI와 실업률은 발표문의 엠바고 종료, 산업생산은 발표문 시각, M2는 공식 일정 시각이다. [CPI](https://www.bls.gov/news.release/archives/cpi_10142026.htm), [고용](https://www.bls.gov/news.release/archives/empsit_10022026.htm), [산업생산](https://www.federalreserve.gov/releases/g17/20261016/g17.pdf), [연준 일정](https://www.federalreserve.gov/newsevents/2026-october.htm). BLS 직접 자동 다운로드는 HTTP 403이었고 공식 웹문서에서 내용을 확인했다.

`collect_fred_pages.py`는 FRED 공식 페이지의 최신 관측월·값·`Updated` 분, 원본 해시 및 이 컴퓨터의 요청·수신 시각을 새 폴더에 남긴다. 4개 지표에 대해 각각 ALFRED 빈티지의 값·관측월·수정일과 대조하고, 공식 발표 기준시각·FRED 업데이트 표시·실제 수신시각의 순서 및 입력 무결성을 확인한다. FRED 업데이트는 시리즈의 최신 갱신 표시이며 각 값의 최초 공개시각 증거는 아니다. 공식 엠바고 또는 일정 역시 ALFRED의 정확한 일중 배포 시각을 보증하지 않는다. 발표·수정·수집의 완전한 PIT 증명 대신, 기존 이틀 지연 연구 가정과 실제 수신 기록을 함께 사용한다.

`issue_release_checked.py`는 네 지표가 일치하지 않거나 공식 기준시각 확인 범위를 벗어나면 발행을 중단한다. 현재 사전등록은 2026년 9월 관측치만 포함한다. 미래 데이터 변경에 대해 시각을 임의로 추정하지 않는다. 별도 `data/operations/macro_release_forward/ledger.sqlite3`에 최초 예측과 첫 만기 점수를 남긴다. 예측 우위 및 수익성은 검증되지 않았고 통계 확증을 하지 않는다. 예측은 기존 장부를 수정하지 않는다.

```powershell
.\.venv\Scripts\python.exe scripts/collect_fred_pages.py
.\.venv\Scripts\python.exe scripts/issue_release_checked.py --model <모델_JSON> --vintages <ALFRED_수집본> --fred-pages <FRED_수집본> --price-batch <시장_수집본>
```

기본은 기록 없는 검사이며, 발행은 마지막 명령에 `--issue`를 붙인다. 만기 이후 새 시장 수집본으로 `scripts/score_release_checked.py --batch <시장_수집본>`을 실행해 검사하고, `--write`를 붙이면 최초 점수만 새 장부에 기록한다. 자동 실행·배포 없음.

## 무료 WTI 선물 자료와 롤

[CME 무료 일일 공보](https://www.cmegroup.com/market-data/daily-bulletin.html)는 계약별 정산값·거래량·미결제약정을 공개한다. 공식 웹에서 확인한 2026-10-27 최종 공보의 NYMEX 원유(CL)는 2026년 12월물 정산 99.90달러, 2027년 1월물 98.06달러였다. 공보는 전 거래일 잠정 및 최종판을 별도 제공하며, CME는 웹 자료를 참고용으로 표시한다. 이 두 계약의 가격차는 실제 롤 수익률이 아니다. 확인 당시 자동 정산 요청은 시간 초과였고, 일보는 웹에서 확인한 것으로 자동 수집·연속 데이터 구축을 검증한 것은 아니다. [CME 공보](https://www.cmegroup.com/daily_bulletin/current/Section61_Energy_Futures_Products.pdf)는 변하는 주소라 날짜를 반드시 본문에서 확인해야 한다. 저작권·이용 조건을 확인하기 전 재배포하지 않는다.

[CME 연속가격](https://www.cmegroup.com/market-data/cme-group-continuous-price-series.html)은 최근월 기준 만기 2영업일 전 전환, 실제 계약과 다음 전환일을 제공하지만 자료 라이선스가 필요하다. 무료 일보에는 동일한 연속계약 롤 이력이 제공된다고 확인되지 않았다. [Databento](https://databento.com/docs/conventions/symbology)는 전일 거래량·미결제약정·만기 기준을 구분하지만 실제 접근 및 사용료 조건을 확인해야 한다. 따라서 WTI 전진 예측은 차단 상태로 남긴다. EIA 공개 선물 시계열은 2024-04-05 이후 중단됐다.
