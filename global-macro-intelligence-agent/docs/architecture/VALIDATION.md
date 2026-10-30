# 실행·검증 기록

기준일 2026-10-28 한국. Windows/Python3.12.10. 기존 원격 `b63f831`에서 별도 `feature/gmia-trust-architecture`로 작업. 원본 prompts와 사전등록 v0.3/v0.4의 diff는0이다.

## 첫 실데이터 수직 슬라이스

| 실행 | 관측 결과 |
|---|---|
| `python scripts/fetch_data.py` | Yahoo10+FRED7=17 시리즈 성공, 실패0. ALFRED는 키 없어 건너뜀 |
| `python scripts/run_all.py --no-fetch` | run `20261028T053052Z`, 9자산×2기간=18 예측, 후보270 최초 INSERT |
| source pinning | 시장10+금리3=13 입력 pointer, 전부 sha256_verified. 표시전용 macro4는 모델에 포함하지 않음 |
| `python scripts/score_ledger.py` | pending270, not_mature270, scored0, eligible0/252; 실제 시간이 지나기 전 결과 생성 안 함 |
| `python scripts/backup_ledger.py --destination data/backups/forward-20261028-initial.sqlite3` | integrity ok, forecasts270/scores0; 기존 파일 덮어쓰기 없음 |
| `python -m pytest --basetemp=artifacts/pytest-trust-02 --tb=short` | 45 passed,17.31초 (기존36+신규9개 테스트 케이스) |
| `python -m mypy --ignore-missing-imports --follow-imports=silent src/gmia/data/pit.py src/gmia/data/store.py src/gmia/evaluation/backup.py` | 3 소스 파일 오류0. 저장/PIT/백업 경계만 검사, 프로젝트 전체 strict 타입검사 아님 |
| `python -m compileall -q src/gmia scripts tests dashboard` / `git diff --check` | 통과 |

첫 전체 실데이터 실행은 커밋 전 작업트리였다. ledger의 git_commit은 당시 HEAD b63f831이고 수정 내용 전체의 깨끗한 commit 증명으로 읽어서는 안 된다. run 입력 snapshot 포인터는 남았다. 이후 코드에는 dirty 여부와 Python 소스 파일별 SHA256을 추가해 이 구분을 명시한다. 기존 첫 예측을 새 커밋으로 덮어쓰지 않는다.

모델 파라미터·피처 수치·라벨·사전등록 기준은 변경하지 않았다. 실데이터가 기존보다 새로워 과거 성적표 숫자가 달라질 수 있으며, 이를 새 예측력 발견으로 주장하지 않는다. 첫 run의18개 예측은 모두 참고 신뢰도 낮음이다. 원데이터/원장/실행 아티팩트/백업은 Git ignore 대상이며 업로드하지 않는다.

## 실패를 포함한 검증 이력

- 실데이터 없는 최초 `run_all --no-fetch`는 유효 타깃 부재 오류로 종료; `score_ledger`도 원장 부재로 종료했다. 성공으로 세지 않는다. 이후 실제 수집 뒤 실행 성공.
- 기본 pytest 임시폴더는 Windows sandbox 권한으로 만들 수 없어 오류. 프로젝트 내부의 새 `artifacts/pytest-trust-*` 경로로 재실행했다.
- 최초 snapshot 테스트에서 Parquet index frequency 속성 차이2건과 Windows 동시 pointer 교체 PermissionError1건을 확인했다. 저장 계약에서 freq를 제외해 비교하고 Windows 한정 일시 오류에 최대6회 재시도를 추가한 후 전체45 통과.
- 기존 원격 CI는 Ubuntu36 통과. 이번 workflow는 Ubuntu/Windows matrix와 경계 타입검사를 추가한다. 새 PR의 실제 CI 결과는 아래 후속 기록에서 구분한다.

## 미검증·남은 한계

실제 만기 후 첫score는 아직 미검증이다. 합성 fixture로 정상 만기·수정값 불변·late/stale/future metadata 제외·대응쌍·HAC/BH·백업복원을 검사했지만 실제 시간경과를 대신하지 않는다. ALFRED/ECOS/KOSIS/BOJ/기업 공시/뉴스/클라우드/운영 스케줄·대시보드 브라우저 실사용은 이번 검증 범위 밖이다. 대시보드 코드는 바꾸지 않았고 저장 loader 계약은 유지했다.

잔여 위험: 실제 release timing, 달력/누락봉, 전체기간 volume schema, v0.3 누락가족 분모, 코드버전별 전진분석, score snapshot FK와 전체 run 원자성. CURRENT_STATE_AUDIT의 미해결 항목을 참조한다. SQLite trigger는 관리자까지 막는 WORM이 아니다.

## 재현 (프로젝트 루트)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest --basetemp=artifacts/pytest-new-unique-directory
python scripts/fetch_data.py
python scripts/run_all.py --no-fetch
python scripts/score_ledger.py
python scripts/backup_ledger.py --destination data/backups/forward-new-unique-name.sqlite3
```

테스트 basetemp는 pytest가 관리하므로 사용자 데이터가 없는 새 디렉터리만 지정한다. 실데이터 발행은 실제 현재시각만 사용하고 과거 기록을 조작하지 않는다. score는 새 데이터 수집 후 만기에 실행한다. 백업 복원은 새 경로에서 점검하고 운영 원장에 덮어쓰지 않는다.

## 커밋 후 재실행과 원격 CI 확인

구현 커밋: `7fe1edb102bdcf754711463c68814b05d78db07f`.

- 커밋 후 전체 run `20261028T054452Z` 성공, `git_dirty=false`, Python 소스33개 SHA256 기록.
- 동일 snapshot에서18개 forecast JSON이 최초 실행과 완전히 같음. 장부 attempted270/inserted0/duplicates270, 최초270행 그대로 보존.
- 실제 장부 백업을 별도 경로에서 읽어 forecast270행이 원장과 완전히 같은지 확인(`True`). 합성 만기 score가 포함된 복원 검사는 단위 테스트에서 별도로 통과.
- 최초 실데이터 실행의 역사적 significance252개에서 supported0. 재사용 홀드아웃 결과이며 새 확증 근거가 아님.
- [CI 실행40639827392](https://github.com/cyw0927/etc/actions/runs/40639827392)에서 Ubuntu와 Windows 두 job 모두 성공. 원문 로그에서45개 테스트와 경계3파일 mypy 성공 확인.
- 로컬 최종 테스트45 passed/17.30초. 환경: pandas3.1.0, numpy2.5.4, scikit-learn1.9.1, LightGBM4.7.0, yfinance1.7.0, pyarrow26.0.0, pytest9.2.0, mypy2.4.0.
- [별도 PR #9](https://github.com/cyw0927/etc/pull/9), base=`feature/gmia-prediction-mvp`, head=`feature/gmia-trust-architecture`. 병합하지 않았다. 후속 이슈 #3~#8 생성.

데이터/실행 산출물은 로컬 프로젝트의 data와 artifacts 아래에만 보관된다. 커밋 후 검증을 기록하는 후속 문서 커밋은 위 구현/실험 커밋과 구분한다. 이 문서가 실제 만기 후 채점이나 공개 서비스 준비까지 검증됐다는 뜻은 아니다.

## 작업 중 외부 원격 상태 변화

최초 감사 때 열려 있던 PR #1/#2/#9가 작업 중 외부에서 병합된 상태로 바뀌었다. 에이전트는 병합 도구·명령을 호출하지 않았다. 관측한 merged_at은 UTC 기준 #1 05:49:05, #2 05:49:21, #9 05:49:28 (한국시간14:49)이다.

최종 fetch 당시 main은 `ddc4b30`(#2 병합), 기존 구현 브랜치는 `433791e`(#9 병합)였다. 즉 #9 코드는 기존 기능 브랜치에만 들어갔고 main에는 아직 없다. 후속 검증 문서 `09ea42c`와 함께 **최신 main 대상 새 PR**로 인계한다. 과거 브랜치 병합을 되돌리거나 기존 PR #1/#2 설명을 수정하지 않는다. main 직접 푸시/force push도 수행하지 않았다.

## v0.4.1 독립 검증과 발행 적시성 규칙 (2026-10-28, Claude Code)

**독립 재실행.** `b36843e`를 GitHub에서 새 폴더로 클론했다. 이어서 새 가상환경을 만들고 잠금 파일로 설치했다.

| 확인 항목 | 결과 |
|---|---|
| `pytest` | 45 passed |
| `compileall` | 통과 |
| 경계 3파일 mypy | 통과 |
| `fetch_data.py` | 17개 시리즈, 실패 0 |
| `run_all.py --no-fetch` 1회차 | `git_dirty=false`, 입력 스냅샷 전부 `sha256_verified`, 장부 270행 INSERT |
| `score_ledger.py` | not_mature 270, scored 0, eligible 0/252 |
| 같은 데이터로 2회차 | inserted 0, duplicates 270 |
| `backup_ledger.py` | 백업 270행이 원장과 완전히 같음 |
| 장부 UPDATE·DELETE | 트리거로 차단 |

Codex의 기록과 모두 일치했다. 검증용 클론과 그 장부는 확인 후 삭제했다.

**발견한 빈틈.** 합성 데이터로 시험했다. 기준일보다 24일 늦게(20봉 중 18봉 공개 후, 만기 전) 기록한 예측이 v0.4 규칙에서는 받아들여졌고 채점까지 됐다.
- 모델 입력은 기준일 데이터로 고정돼 직접적인 정보 유출은 아니다.
- 하지만 오래된 데이터로 다시 실행하면 이런 예측이 표본에 섞인다.

**조치.**
- `1092429`: 사전 등록 v0.4.1을 코드 변경 전에 커밋했다. 그 시점에 알려진 장부의 채점 행은 0개다.
- 이어서 `score_pending`에 `stale_issue_excluded` 규칙을 추가했다(기록 시각 ≥ 기준일 다음 봉 완료 → 영구 미채점).
- 테스트 4개를 추가했다: 늦은 발행 제외, 다음 봉 완료 시각 경계(1초 전은 채점, 정각은 제외), 금요일 예측의 주말 기록 허용, 만기 이후 기록은 late로만 집계. 전체 49 passed.

**알려진 관찰.**
- Yahoo `BTC-USD` 원본에 2026-10-27 일봉이 없다(10-26에서 10-28로 넘어감). 공급원이 봉을 빠뜨리면 발행 적시성 창이 그만큼 길어진다.
- 공급원이 나중에 빠진 봉을 채우면, 그 사이에 기록된 예측은 '다음 봉'이 앞당겨져 늦은 발행으로 바뀔 수 있다. 예: Codex 실행의 BTC 기준일 10-26 예측은 10-28 05:30 UTC에 기록됐는데, 10-27 봉이 채워지면 그 봉의 완료 시각은 10-28 00:14 UTC다. 이 경우 제외되는 것이 규칙의 의도와 맞는다(10-27 움직임이 이미 공개된 뒤 기록됨).
- BTC의 '20봉 = 20 달력일' 전제도 봉 누락 시 깨진다. 이번 범위에서는 바꾸지 않았다.

## 2026-10-30 독립 검증 후속 수정 (Claude Code)

`feature/gmia-wti-provider-gate`(`4466aa4`)의 PR 체인 #11~#18과 커밋되지 않은 파일을 독립 검토했다. 커밋된 테스트 91개 통과, 실제 장부 4개 무결성 정상, 실제 발행 예측 12건 모두 발행 창 안에 있었다. 아래 세 가지를 고쳤다.

| 커밋 | 내용 |
|---|---|
| `1af8a1a` | **v0.5 채점 차단 수정.** `score_pit_baseline.py`가 매 실행마다 이미 채점된 예측을 다시 채점했다. 그래서 두 번째 배치부터 '기존 점수와 다름' 오류가 나고, 새로 만기된 점수까지 전부 롤백됐다. 이제 이미 채점된 예측은 건너뛴다. 결과가 다르면 기존 점수를 유지하고 충돌을 실행 기록에 남기며, 다른 새 점수는 그대로 저장한다(사전 등록 `9b7f609`의 "기존 결과 유지·충돌 보고"). 회귀 테스트는 이전 코드에서 실패함을 확인했다. |
| `83aac0b` → `f3ccd7b` | **수집 배치 스크립트 커밋과 v0.4.2.** 커밋된 스크립트 4개가 읽는 `batch_manifest.json`을 만드는 `safe_forward.py`가 커밋되지 않았었다. 추가 채점 규칙을 먼저 사전 등록(`preregistration_v0.4.2.md`)한 뒤 커밋했다. 문제가 있는 예측만 보류하고(자산 전체 보류 아님), 검사를 통과한 목록만 채점한다. `replay_snapshot.py`는 현재 브랜치에서 동작하지 않아 커밋하지 않았다. |
| (이 커밋) | **KRX 수능일 장 시간.** 두 달력 라이브러리가 수능일을 09:00–15:30으로 표시한다. 실제로는 10:00–16:30이다(2023–2025 KRX 공지). `src/gmia/data/sessions.py`에 예외 일정을 두고 v0.5 발행·채점, `safe_forward`, v0.4 장부 봉 완료 시각, 수집 시 미완성 봉 제거에 적용했다. 2026-11-19(2027학년도 수능, 평가원 2026-03-31 발표)는 KRX 공지 전이라 '예상'으로 표시했다. KRX 공지가 다르면 이 파일을 고친다. |

### 같은 날 후속 수정

| 커밋 | 내용 |
|---|---|
| `c5e0f06` → `62953eb` | **거시 입력 기준 시각 일치.** 사전 등록(`preregistration_macro_alignment.md`)을 먼저 커밋했다. 이후 두 거시 가족은 학습과 같은 '기준 세션 마감 + 15분'으로 입력을 고른다. 같은 등록에 FRED 페이지 15분 최신성 조건과 적용 시점(`ac68504`, 2026-10-29 02:14:31 UTC)도 남겼다. |
| `69843ea` | **규칙 보호 테스트.** v0.5 테스트 16개(그중 2개는 알려진 빈틈을 xfail로 기록)와 거시 테스트 8개를 추가했다. 각 테스트는 해당 규칙을 지우면 실패함을 확인했다. |
| `234fde8` | **WTI 수집 작업.** 실행마다 `data/operations/logs/finz_wti/`에 로그(브랜치·커밋, 출력, 종료 코드)를 남긴다. 종료 코드는 0/1/2/3으로 구분하고, 오류에 HTTP 상태 코드를 기록한다. 키 값은 로그에 남지 않는다. 예약 작업 자체는 바꾸지 않았다. |
| (이 커밋) | **`replay_snapshot.py` 커밋.** 원본 커밋을 임시 worktree로 꺼내 재실행한다. 270개 확률 차이는 0.0이었고, 장부는 예측 270행·채점 0행 그대로였다. |

**`macro_release_checked_v1`의 2026-10-28 기록**(p = 0.595570)은 입력 기준 시각 보완 **이전 정의**(발행 시각 기준)로 발행됐다. 학습 정의를 적용하면 M2 8월값이 선택돼 p = 0.595082다. 이 기록은 수정하지 않는다. 이후 이 가족의 기술통계는 보완 이후 발행분과 분리해 보고한다.

남은 사항:
- **WTI 예약 작업의 브랜치 의존.** 작업이 체크아웃된 브랜치의 `run_finz_wti.ps1`을 직접 실행하므로, 그 파일이 없는 브랜치로 바꾸면 로그도 남지 않고 실패한다. 전용 git worktree로 옮기거나 `main`에 병합하는 방안이 있다. 둘 다 예약 작업 설정을 바꿔야 해서 사용자 결정 사항이다.
- **v0.5 발행 충돌 검사.** 확률과 스냅샷 해시만 비교한다(xfail 테스트로 기록).
- **v0.5 발행 기록의 누락 필드.** 사전 등록이 요구한 최신 거래일, 결측·중복 수, 라벨 종료 시각이 발행 기록에 저장되지 않는다.
