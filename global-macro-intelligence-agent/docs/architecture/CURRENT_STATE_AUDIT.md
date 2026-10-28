# 현행 상태 및 위험 감사

2026-10-28 한국 기준. 원격 PR #2 head `b63f831261a11427f750937b3cb7c2b021abfd38`, base main `e34a9fb413dc1bbe08fc232dea0f8ae06f67453b`. PR #1 head `17f24b92abc3385ceada28d26f8bfcd20fb488b3`는 열린 상태이며 보존한다. PR #2도 열림·미병합·mergeable, 등록된 review/review thread 없음. PR 설명은 v0.3까지이며 수정하지 않았다. 원격 최신 상태는 감사 당시 snapshot이고 이후 바뀔 수 있다.

[기존 CI 실행](https://github.com/cyw0927/etc/actions/runs/40429466803): Ubuntu/Python 3.12, 설치·compileall·합성 pytest 36개 통과. job `121943341400` 원문 로그 확인. 실제 Yahoo/FRED·ALFRED·Windows 통합 성공을 뜻하지 않는다.

## 확인 범위와 현행 진단

PR #2 전체 diff(53파일), 코드 트리, README/CLAUDE, config, 원본 프롬프트 3개, 사전등록 v0.3/v0.4, data/features/models/evaluation/pipeline/report/news, scripts, dashboard 6화면과 공유 loader, tests 4개 원본 파일 및 CI를 읽었다. 핵심 구현은 최신 코드가 기준이다. PR #1은 메타데이터만 확인했고 파일/설명을 변경하지 않았다. 모든 모델·데이터 정책이 옳다고 보증하는 외부 감사는 아니다.

| 기능 | 현행 판정 | 근거·실용 한계 |
|---|---|---|
| 시장/FRED 수집·정제 | 구현 | `data/{market,fred,clean,collect}.py`; 17 시리즈. 공개시각·정식 거래소 달력 부족 |
| ALFRED | 부분구현 | API/빈티지 변환·합성 테스트. 키 없어서 실제 응답 미검증 |
| 날짜 정합성 | 부분구현/중요 위험 | strict 날짜 join, 실제 발표시각·수정이력 증명 없음 |
| 15 후보·5/20봉 | 구현 | registry·predict·backtest. 후보가 없으면 누락. 장기 horizon/분포는 없음 |
| 워크포워드/보정 | 구현 | label end purge, train 내 imputer/scaler. 고정 모델; nested tuning 없음 |
| HAC/BH | 구현/제약 | v0.4 고정252. v0.3은 가용 후보 수를 분모로 사용하므로 누락 시 등록252와 불일치 |
| 예측/첫 score | 부분 운영 가능 | 로컬 unique+transaction, 만기·수집시각 검사. 공개/모델버전·누락봉 위험 잔여 |
| 출처 불변성·백업 | 이번 구현 | snapshot pointer·hash·run manifest·triggers·수동 backup. WORM/원응답 보관은 아님 |
| 국가별 거시/재무/사건/시나리오 | 미구현 | 뉴스 계약과 '추후 구현' 화면만. 새 설계 문서에 범위·계약 제시 |
| 대시보드 | 연구 MVP | 현재 시장/상관/예측/백테스트/국제정세/전진검증. 운영 API/인증 없음 |
| 스케줄/배포/영구운영 | 미구현·사용자 선택 | CI만 있음. 운영 DB·백업·실패 알림·호스팅 별도 |

## 발견사항 (파일/라인은 감사 기준 b63f831, 변경 뒤 번호와 구분)

| ID·심각도 | 위치·재현 방법 | 영향·이번 처리 |
|---|---|---|
| A01 중요 | `data/store.py:13-15`: Parquet 쓴 뒤 JSON 쓰기에서 예외 주입 | 새 값+옛 metadata 결합/덮어쓰기. **수정**: 스냅샷 완성 후 pointer 교체, 실패·동시쓰기 테스트 |
| A02 중요 | `evaluation/forward.py:62-96`: sqlite 연결 후 forecasts/scores UPDATE/DELETE 실행 | append-only는 호출 관례였음. **수정**: 일반 수정·삭제 trigger 차단, 백업 복원 검사. 소유자 DDL/REPLACE/파일교체 방지는 미해결 |
| A03 중요 | `features/build.py:42`: 앞 100봉 volume>0, 뒤 100봉 0으로 붙이고 own_features 앞부분 열 비교 | 전체기간의 volume 가용성으로 과거 피처 schema 결정. **미해결**: 원모델 사후 변경 피하고 고정 schema+train 내부 판단을 후속 프로토콜로 등록 |
| A04 중요 | `features/build.py:67-76`, `data/fred.py:3-4`: 아시아 t 종가에 DFF t-1이 이미 발표됐다는 근거 없음 | 엄격한 날짜 join도 지표별 발표 지연보다 빠를 수 있음; 금리 정정 불가 단정도 부적절. 문구 교정/위험 명시; 모델입력 변경은 후속 버전 |
| A05 중요 | `evaluation/forward.py:196-199`(기준): BTC 원봉 하나 제거 후 같은 forecast h 만기 비교 | h는 행 수여서 BTC 누락일이 있으면 달력일 h와 달라짐. 거래소 calendar도 휴일·조기폐장/공급자 누락 구분 없음. **미해결**, 결측/달력 gate 우선 구현 |
| A06 보통 | `configs/default.yaml:62`, `forward.py:54-60`, `clean.py:36-37`: BTC 날짜 D→다음날00:14 UTC | UTC 봉 경계00:00+15분이면00:15, 현재23:59+15분은1분 빠름. 기존 테스트도00:14를 기대함. 공급자 봉 명세 확인 뒤 시간모델 버전 수정 필요 |
| A07 중요 | `data/market.py:54-66`, `forward.py:211`: 새 Yahoo 수정종가로 과거 앵커와 만기를 함께 채점 | 수정 이전 값 재현 불가/첫score 근거 미보존. 이번부터 수집본은 보존하지만 score 행에 snapshot FK는 아직 없음. 등록대로 두 값은 채점 당시 같은 기준 사용; anchor_price로 분모 임의 변경 금지 |
| A08 중요 | `evaluation/significance.py:72-76`: 일부 자산/후보 없이 실행하고 n_tests 확인 | v0.3 과거표의 다중비교 분모가 252보다 줄 수 있음. v0.4는 missing p=1로252 유지. 역사 성적을 조용히 다시 쓰지 않고 후속 보고에서 구분 |
| A09 중요 | `pipeline.py:128,148-150`(기준): 장부 INSERT 후 report/copy에서 예외, 동시에 두 run 실행 | 장부와 run 파일 원자성 없음, latest 삭제·복사 중 UI 깨짐, 초 단위 run_id 충돌. **부분 처리**: 입력/code manifest 추가. 전체 완료 pointer/job lock·재시도 상태는 후속 |
| A10 중요 | `forward.py:202-217`(기준): 미래 fetched_at를 now보다 크게 입력 | 수집시각 하한만 검사해 미래 metadata 허용. **수정**: fetched>now 보류, 회귀 테스트 |
| A11 보통 | `features/build.py:101`: 다른 시장 휴일에 ffill된 종가로0수익 생성 | 비동시 거래·가짜 정적 관측으로 상관 편향; 가격수준 허위상관은 피했으나 정확 동시수익은 아님. 거래 가능한 공통 UTC구간/주간 수익 민감도 연구 필요 |
| A12 중요 | `forward.py:251~` 및 docs/v0.4 | 코드 SHA가 다른 모델군·발행 지연·순차 반복검정을 통계에서 별도 분할하지 않음. 형식 충족과 순수 실시간 확증은 다름. 버전/지연 감사와 새 protocol 필요 |
| A13 보통 | `pipeline.py:99`(기준): 빈 raw에서 run_all --no-fetch | concat 'No objects' 오류, 사용자 원인 파악 어려움. **수정**: 데이터/유효 타깃 부재 명시 |
| A14 중요 | `collect.py`, `pipeline.load_inputs` | 한 소스 갱신 실패해도 이전 cache 사용. stale 임계/품질 blocking 없음. run에는 현재 provenance 기록; 운영 승격 전 SLA gate 필요 |

## 자산의 의미

SPY/QQQ는 ETF 수정종가, KOSPI/Nikkei는 배당 없는 지수다. GLD는 금 현물 자체가 아니다. USDKRW/USDJPY는 자국통화 per USD이며 상승은 원화/엔화 약세다. DGS2/DGS10/DFF는 금리(%), 차분은 %p로 채권 가격 수익과 다르다. WTI 연속 근월물은 롤 갭/음수가격이 있으며 장기 투자 가능 total return이 아니다. BTC는 24/7·UTC와 빠진 날짜를 점검해야 한다. 이들을 같은 통화·총수익 자산으로 보고 수익률을 비교하지 않는다.

## 실험 해석

기존 '지지0' 결과를 유지한다. 데이터/파이프라인 무결성을 개선했다고 신호가 생기는 것은 아니다. 실데이터 수집과 현재 예측 발행은 이번에 실행했지만 만기 이후의 실제 첫 score는 시간이 경과해야 검증된다. 구체적 실행·실패·미검증은 [VALIDATION](VALIDATION.md)을 따른다.
