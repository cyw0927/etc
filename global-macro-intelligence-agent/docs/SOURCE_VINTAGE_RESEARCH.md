# 공급원 수집 및 거시 시점 연구 결과 (2026-10-28)

## 완료 및 경계

- Coinbase Exchange BTC-USD 공개 일봉을 2010-01-01부터 2026-10-28 00:00 UTC 직전까지 요청했다. 응답의 첫 날짜는 2015-07-20이고 마지막은 2026-10-27이며 4,118개, 그 사이 날짜 누락은 0개다. 25개 응답의 원본 해시와 정규화 결과를 다시 읽어 검증했다. Coinbase의 전체 역사나 Yahoo와 동일하다는 보증은 아니며, Coinbase는 구간 데이터가 빠질 수 있다고 설명한다. 역사적 PIT 버전이 아니고, 대체 예측 발행도 하지 않았다. [공식 설명](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles).
- ALFRED CPIAUCSL, UNRATE, INDPRO, M2SL에 대해 2020-03-01, 2021-03-01, 2026-10-27 빈티지를 12개 별도 수집했다. 2020과 2021의 공통 관측월에서 값이 바뀐 건 각각 49, 12, 5, 283개다. 선택된 세 날짜만 비교한 것이며 전체 수정 이력이 아니다. [ALFRED 설명](https://fred.stlouisfed.org/docs/api/fred/alfred.html). API를 통한 전체 vintage date 목록에는 FRED API 키가 필요하고 현재 실행 환경에 설정되지 않았다. 가입이나 키 발급은 하지 않았다.
- `src/gmia/features/macro_pit.py`는 관측월, 이 수정본의 확인된 발표 시각, 수집 시각, 출처 및 해시를 가진 레코드만 각 예측 시각에서 선택해 모델 입력 열을 만든다. 기존 로지스틱 모델 연결은 합성 자료에서 시험했으며 실제 ALFRED 자료 4개는 발표 시각 미확인으로 전부 차단됐다. `exact_verified` 및 해시의 진위는 호출 측에서 원문을 대조해야 하며 이 모듈은 주장만으로 원문의 진위를 증명하지 않는다. 기본 파이프라인·기존 15개 모델·실제 예측에는 연결하지 않았다. 전체 수정 이력 수집과 원문 발표·수정 시각 및 과거 수집 이력 확보, 검증된 파이프라인 연결과 평가 전 별도 사전등록이 필요하다.
- ECB 원본 CSV는 두 번 동일하게 수집됐으나 2010년 일요일 날짜와 비정상적으로 오래된 최신 관측일이 포함돼 거부됐다. 최초 manifest의 성공으로 보이는 값은 후속 검증 파일로 무효 표시했고, 원본과 기록은 보존했다. ECB의 일반적 원화·엔화 교차율은 `EURKRW/EURUSD`, `EURJPY/EURUSD`로 계산되지만 뉴욕 마감 일봉이 아니다. [ECB 기준](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html). CSV 이상 원인은 확인되지 않았다.
- EIA Cushing WTI 현물 XLS는 원본 파일과 내용을 확인했다. 1986-01-02~2026-10-20, 9,527개 값이 있으며 상품명과 날짜 구조를 확인했다. 현물은 기존 CL 연속선물 및 그 롤 수익률과 다르며 발행·수정 시각도 검증되지 않았다. [EIA 정의](https://www.eia.gov/dnav/pet/tbldefs/pet_pri_spt_tbldef2.asp). [CME 연속선물](https://www.cmegroup.com/market-data/cme-group-continuous-price-series.html)은 롤 정의가 있지만 라이선스 확인이 필요하다.

## 재현

가상환경에서 `requirements-operations.txt`를 설치한 후 다음 명령을 수동 실행한다. 수집 명령은 실행마다 새 디렉터리를 만들고 기존 데이터는 변경하지 않는다. 스냅샷과 장부는 공개 Git에 포함하지 않는다.

```powershell
.\.venv\Scripts\python.exe scripts/collect_coinbase_history.py
.\.venv\Scripts\python.exe scripts/verify_coinbase_history.py data/operations/source_research/<BTC_수집본>
.\.venv\Scripts\python.exe scripts/collect_alfred_samples.py
.\.venv\Scripts\python.exe scripts/verify_ecb_eia.py
.\.venv\Scripts\python.exe -m pytest -q
```

거래 자동화나 스케줄 설치는 수행하지 않았다. BTC·FX·WTI 예측 발행과 실제 거시 특성 사용은 계속 차단한다.
