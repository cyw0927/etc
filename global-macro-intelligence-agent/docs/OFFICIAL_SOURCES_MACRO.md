# 공식 공급원 재검증과 ALFRED 연구용 모델 연결

## FRED 키 없이 수정 이력 받기

ALFRED의 공식 [다운로드 양식](https://alfred.stlouisfed.org/help/downloaddata)은 API 키 없이 지표의 변경이 있는 빈티지 날짜를 제공하고 선택한 날짜의 관측값·수정 적용기간을 ZIP으로 내려준다. `collect_alfred_web.py`는 양식의 날짜 목록 전체 중 2005년 이후와 그 직전 날짜를 선택해 네 지표의 원본 17개 ZIP과 양식, 해시, 요청·수신 시간을 별도 폴더에 저장한다. 실제 목록은 CPIAUCSL 280, UNRATE 263, INDPRO 280, M2SL 794개였다. 이것은 **해당 기간 ALFRED가 현재 제공하는 날짜별 이력**이지 과거에 이 시스템이 실시간으로 수집했다는 뜻이 아니다. 빠진 공표일, 당일 발표 시각, 출처의 사후 정정은 별도 확인이 필요하다.

`alfred_research_features.py`는 모든 원본 파일과 양식 해시, 선택한 날짜 누락, 중복·충돌·겹치는 수정 기간을 확인한다. `train_alfred_research.py`는 사전등록에 따라 SPY 5거래일 라벨과 네 지표의 날짜별 수정값을 결합한다. 매 거래소 마감 시각을 기준으로 ALFRED 수정일 이후 **이틀 지연**을 적용한다. 날짜 단위 이력을 이용한 보수적인 연구 가정으로, 실제 발표 시각이나 과거 수집 시각을 증명하지 않는다. 학습만 진행하며 예측 발행·모델 평가·기존 운영 모델 교체는 하지 않는다. 학습 시 모델 계수와 입력 해시를 비공개 연구 폴더에 저장한다. 수정종가도 발행 당시의 과거 버전이 아니라 이번 가격 스냅샷이다. 향후 전진 예측·평가 전 별도 사전등록과 실제 수집시각·발표 근거가 필요하다.

## ECB 오류와 독립 검증

기존 `.../eurofxref-hist.csv` 응답은 Last-Modified가 2020-06-18이고 2010년 최신 기록, 일요일 및 이상한 숫자를 포함했다. 이 파일이 왜 그 내용을 반환하는지는 확인하지 못했다. 공식 `.../eurofxref-hist.zip`의 Last-Modified는 2026-10-27이고, ZIP의 최신 USD·JPY·KRW는 ECB 공식 SDMX API 및 일별 XML과 정확히 일치했다. `verify_official_fx_wti.py`가 세 경로를 수집·검사하며 원본은 별도 폴더에 남긴다. ZIP의 1999년부터 최신까지 세 통화가 모두 있는 날짜는 7,123개였다. 이 교차 비교는 최신 날짜에 한한다. ECB 기준환율은 유로 기준 공표값이며 뉴욕 FX 일봉이나 Yahoo 일봉과 동일하지 않다. [ECB API 예시](https://data.ecb.europa.eu/help/api/data-examples).

## WTI 선물

EIA의 `RCLC1`은 Cushing 원유 선물 1계약 시계열이며 원본에 1983-04-04~2024-04-05의 10,183행이 있다. EIA는 2024-04-05 이후 NYMEX 선물 가격을 제공하지 않는다고 명시한다. 따라서 최근 예측의 선물 공급원으로 사용할 수 없다. 이 파일은 개별 만기계약 코드·롤 전환 근거를 제공하지 않아 롤 수익률 검증에도 충분하지 않다. [EIA 공식 목록](https://www.eia.gov/dnav/pet/hist/rclc1d.htm), [CME 연속선물 설명](https://www.cmegroup.com/market-data/cme-group-continuous-price-series.html). 현재 FX·WTI 예측 발행 차단은 유지한다.

## 실행

```powershell
.\.venv\Scripts\python.exe scripts/collect_alfred_web.py
.\.venv\Scripts\python.exe scripts/verify_official_fx_wti.py
.\.venv\Scripts\python.exe scripts/train_alfred_research.py --vintages data/operations/source_research/<ALFRED_수집본> --price-batch data/operations/collections/<가격_수집본>
```

마지막 명령은 기본적으로 검증만 한다. `--train`을 붙일 때만 Git의 사전등록·커밋 상태와 모든 입력을 확인하고 독립 연구 폴더에 모델을 생성한다. 실제 가격·예측·장부는 Git에 올리지 않는다.
