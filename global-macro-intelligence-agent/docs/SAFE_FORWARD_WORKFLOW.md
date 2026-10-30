# GMIA 안전 재현·수동 수집·만기 채점

운영 위치는 `C:\dev\etc\global-macro-intelligence-agent`. 자동 스케줄·외부 배포 없음. 원본 `data/raw`, `data/imported`, 기존 예측/채점 행은 삭제·덮어쓰지 않는다. 환경: Python 3.12와 `requirements-operations.txt`의 고정 거래소 달력 (버전은 각 batch에 기록). 새 환경에서는 `.venv\Scripts\python.exe -m pip install -r requirements-operations.txt`를 먼저 실행한다.

## 1. 2026-10-28 과거 예측 재현

> **2026-10-30 변경:** 예전에는 현재 코드로 재실행하면서, 원본 커밋 이후 코드가 바뀌었으면 중단했다. 그래서 이후 커밋이 쌓이면 실행할 수 없었다. 이제는 원본 커밋(`7fe1edb`)을 임시 git worktree로 꺼내 **원본 코드로** 재실행하고, 끝나면 worktree를 지운다. 2026-10-30 실행(`data/operations/replays/20261030T061243Z-d1e01d6f`) 결과는 270개 후보 확률 최대 차이 0.0, 장부 기록 0이다.

```powershell
.\.venv\Scripts\python.exe scripts\replay_snapshot.py
```

원본 20261028T054452Z의 13개 입력 포인터/파일 SHA256, 모델 관련 Git 차이, 주요 패키지 버전을 확인하고 원자료 복사본으로 격리 실행한다. 18 자산·기간과 270 후보 확률을 비교한다. 장부에 새 행을 기록하지 않으며 `data/operations/replays/<실행ID>/replay_result.json`과 격리된 실행 파일을 남긴다. 이는 통계적 예측력의 새로운 증거가 아니다.

## 2. 실제 새 데이터 수집

```powershell
.\.venv\Scripts\python.exe scripts\safe_forward.py collect
```

매번 `data/operations/collections/<수집ID>/raw`에 별도 수집한다. Yahoo10개+FRED7개가 모두 성공하고 snapshot hash/수집시각이 일치할 때만 batch ready=true. 실패가 있으면 부분 수집은 보존하되 채점에 쓰지 않는다. FRED/ALFRED 키는 이 수집 명령에서 불러오지 않으며 수정 거시값은 모델 입력으로 사용하지 않는다. 완료 시 출력된 batch 경로를 기록한다.

## 3. 만기 채점 (수동)

```powershell
.\.venv\Scripts\python.exe scripts\safe_forward.py score --batch "data\operations\collections\<수집ID>"
```

만기 후 최신 자료를 새로 수집한 뒤 실행한다. 먼저 원장 SQLite online backup을 `data/operations/scores/<실행ID>/before-scoring.sqlite3`에 만들고 무결성을 검사한다. 고정 batch manifest/hash, UTC 수집시간, 시장별 거래일, 유효 가격, 다음 봉 종료 전 발행 및 만기 완료를 확인한다. BTC는 UTC 연속일 결측과 수집 시점에 완료됐어야 하는 최신 봉의 누락을 차단한다. 주식/ETF는 NYSE/NASDAQ/XKRX/JPX 달력으로 누락 또는 추가 봉을 검사한다. 현재 수집원의 FX/WTI 봉/롤 달력은 검증되지 않아 **USDKRW/USDJPY/WTI 자동 채점은 보류**한다. 규칙은 [docs/preregistration_v0.4.2.md](preregistration_v0.4.2.md)를 따른다. 배치 무결성·최신성 문제는 해당 자산을 **이번 실행에서** 보류하고, 결과 구간의 달력 불일치(BTC 봉 누락 포함)나 달력 기준 늦은 발행은 **그 예측만** 보류(`held`)한다. 같은 자산의 다른 예측은 정상 채점한다.

검증 대상은 이번 명령의 batch에 한한다. 예측 270행과 기존 score는 수정하지 않는다. 실제 score는 검사를 통과한 (기준일, 자산, h) 목록만 `score_pending(eligible=...)`에 넘겨 v0.4/0.4.1 규칙과 첫 채점 INSERT를 적용한다. 검사 이후 장부에 추가된 예측은 그 실행에서 채점하지 않는다. v0.4.2 규칙은 v0.4/0.4.1 위에 더해지는 보수적 조건이다. 보고서·고정 입력 포인터·backup은 별도 실행 폴더에 남긴다. 보고서 작성과 DB 쓰기는 완전한 분산 원자 트랜잭션이 아니며, 장애 시 먼저 preflight와 backup을 확인한다. `score.lock`은 이 명령 사이의 동시 실행을 막지만 기존 `score_ledger.py` 직접 실행이나 다른 프로그램은 막지 못한다. 이 명령을 쓰는 동안 다른 장부 writer를 실행하지 않는다.

거래소 달력 패키지는 정식 데이터 제공자/SLA가 아니며 시차·예외휴장·공급자 별 봉 정의와 수정종가 소급 변경에 대해 완전한 보증을 하지 않는다. 휴장 데이터·실제 종가 정의와 BTC 누락을 검토하고, 권한없는 재배포를 하지 않는다. 예측 통계는 252개 비교, 500쌍·540일 조건을 유지한다. 현재 미만기 자료만으로 성능을 판정하지 않는다.

## 4. 실패 및 복원

- 원자료: `data/operations/collections/` 내 실패 batch를 그대로 보존하고 원인 확인 후 새 수집 실행.
- 복원 검증: 백업을 별도 경로에서 열어 `PRAGMA integrity_check`·`foreign_key_check`와 forecast/score 행 수를 확인한다. 원본 장부에 덮어쓰지 않는다.
- 기존 `data/raw`와 imported 원본을 손대지 말 것. 재현과 수집은 snapshot provenance를 사용하며 과거 발표시점 PIT가 완전히 검증됐다는 뜻이 아니다.
- score 실패 시 preflight/backup 기록을 조사하고 바로 재실행하지 않는다. lock이 남았다면 다른 writer가 종료했는지 확인 후 수동 조치.

## 2026-10-28 실제 확인 결과

- 재현: `data/operations/replays/20261028T070730Z-f8741a42/replay_result.json`. 원본 입력13개 hash 확인, 18개 자산·기간/270 후보 확률 차이 최대0, 실제 장부 기록0.
- 새 수집 batch: `data/operations/collections/20261028T071026Z-f63bc57c`. 17개 수집·hash 확인, 실패0.
- 최신 score 점검(v0.4.2 이전 규칙, 자산 전체 보류 방식): `data/operations/scores/20261028T071325Z-f971270a/score_result.json`. 주식/금150행 미만기, BTC30행은 10월27일 완료봉 누락, FX/WTI90행은 공급자 달력 미검증으로 보류. 새 채점0. 원장/백업/원본 장부는 모두 예측270행·채점0행으로 일치했다.
- 전체 회귀 테스트: 54 passed. 합성 데이터 통합 시험에서 적격 SPY score 생성, WTI 보류, 채점 전 백업 및 재실행 시 최초 score 보존을 확인했다. 실제 만기 후 score 생성은 아직 확인하지 못했다.

이 도구는 새 예측을 발행하지 않는다. 미래 예측 발행까지 안전하게 자동화하려면 거시 발표 시각, 타 자산 시각 정합, BTC/FX/WTI 봉 달력, 실행·원장 전체 원자성 등 기존 감사의 위험을 먼저 해결해야 한다. 현재 `run_all.py`를 별도 검증 없이 안전한 신규 발행 경로로 간주하지 않는다. 특히 기본 설정은 기존 `data/raw`를 읽으므로, 오래된 봉을 기준으로 실시간 예측을 발행할 수 있다.
