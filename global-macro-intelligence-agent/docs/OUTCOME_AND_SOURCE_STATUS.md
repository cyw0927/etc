# v0.5 만기 채점 및 봉·발표 시각 조사

## 현재 구현과 보존

`score_pit_baseline.py`는 `data/operations/issuance/ledger.sqlite3`를 읽기 전용으로 열고, 조건에 맞는 최초 점수만 독립적인 `data/operations/issuance/scores.sqlite3`에 트랜잭션으로 추가한다. 원래 v0.4 장부와 예측 장부를 바꾸지 않는다. 기본 실행은 채점 가능성만 출력한다. `--write`를 붙여도 만기가 지난 완전한 자료가 없으면 파일을 새로 만들지 않는다. 기존 점수와 입력이 다르면 충돌로 중단한다. `docs/preregistration_v0.5_scoring.md`가 기존 최초 예측의 채점 규칙이다.

```powershell
.\.venv\Scripts\python.exe scripts/score_pit_baseline.py --batch data/operations/collections/<수집본_ID>
.\.venv\Scripts\python.exe scripts/score_pit_baseline.py --batch data/operations/collections/<수집본_ID> --write
```

매 실행 전 안전한 신규 수집본이 필요하다. 만기 정규장 마감+15분 이후 수집이 시작되어야 하며, 공급자 스냅샷 해시, 기준일~만기일의 모든 거래일과 가격, 기준가격 개정 여부를 확인한다. 수정종가가 기준일 이후 재조정되면 보류한다. 15분은 운영 완충값이며 공급자의 최종값 보증이 아니다. 점수 저장 전에 새 장부도 사용자 백업 정책에 맞게 백업하고 정기 복구를 확인해야 한다. 미도래 예측은 점수 생성하지 않는다. 현 시점 실제 만기 채점은 아직 검증할 수 없다.

## BTC

`probe_coinbase_btc.py`는 Coinbase Exchange BTC-USD의 공식 공개 일봉 API를 읽기만 하며, UTC 자정 정렬, 15분 완충, 가격 범위·중복·결측을 검사한다. 최근 7개를 실제 검사했다. Coinbase는 무거래 구간을 제공하지 않고 과거 봉도 불완전할 수 있다고 명시한다. [Coinbase 공식 문서](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles). 이 결과는 Yahoo BTC-USD 봉의 정합성이나 동일 가격을 증명하지 않는다. 전체 학습 기간 수집, 저장·재현, 사용권 확인, 새 공급자 대상 별도 사전등록과 실제 채점 연결이 필요하므로 BTC 예측은 계속 차단한다.

## FX와 WTI

[OANDA 공식 문서](https://developer.oanda.com/rest-live-v20/pricing-ep/)는 뉴욕 시간 17시 기준 일봉과 UTC 응답 및 [완성 표시](https://developer.oanda.com/rest-live-v20/instrument-df/)를 명시하지만, 접근 인증 및 USD/KRW 제공·이용권 확인이 필요하다. 이를 Yahoo의 기존 FX 봉으로 간주하거나 주말·휴일을 임의로 채우지 않는다.

[CME WTI 문서](https://www.cmegroup.com/education/courses/introduction-to-energy/introduction-to-crude-oil/wti-overview)상 거래 시간과 [정산 절차](https://www.cmegroup.com/trading/energy/files/NYMEX_Energy_Futures_Daily_Settlement_Procedure.pdf)는 Yahoo 연속선물 봉과 동일하다는 증거가 아니다. [CME 연속가격](https://www.cmegroup.com/market-data/cme-group-continuous-price-series.html)은 계약 식별·롤 규칙이 정의되지만 라이선스가 필요하다. WTI와 FX는 기존 봉 계약 확인 또는 허가된 대체 공급자 및 새로운 사전등록 전에는 차단한다. 유료 가입은 하지 않았다.

## 거시 발표

`probe_bls_release.py`는 BLS CPI 발표문의 기준월과 발표 엠바고 해제 시각을 뉴욕 시간대·DST를 적용해 구분한다. BLS는 [CPI 일정](https://www.bls.gov/schedule/news_release/cpi.htm)을 제공한다. 엠바고는 실제 수집·수정 빈티지를 증명하지 않으므로 이 결과를 FRED 최신 관측값에 붙여 과거 입력을 복원하거나 예측에 사용하지 않는다. 실제 BLS 직접 요청은 HTTP 403이어서 자동 수집은 미검증이며 테스트는 인공 발표문으로 수행했다. [연준 H.15](https://www.federalreserve.gov/releases/h15/)는 별도 게시 일정과 수정이 있고, [ALFRED](https://fred.stlouisfed.org/docs/api/fred/alfred.html)의 날짜별 빈티지만으로 일중 발표·수집 시각을 입증할 수 없다. 원문/수정 내역의 수집, 시점별 스냅샷, 특징 생성기 연결은 미완료다.
