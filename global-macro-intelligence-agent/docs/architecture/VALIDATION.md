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
