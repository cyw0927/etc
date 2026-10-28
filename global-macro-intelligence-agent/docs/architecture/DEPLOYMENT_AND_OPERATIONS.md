# 배포·실행·영구 저장·복구 설계

상태: 로컬 수동 실행과 CI만 실행했다. 다음 스케줄/Compose/클라우드는 **설계이며 설치·배포하지 않았다**.

## 단계와 선택

1. 로컬: 프로젝트 가상환경, 개인 데이터 디렉터리, SQLite+스냅샷, 수동 명령. 실제 장부는 OneDrive 동기화 폴더 밖 운영 경로를 권장한다. 이번 워크스페이스의 장부는 실검증용 로컬 사본이다.
2. 사설 Docker Compose: 같은 이미지의 `web`, 명시 명령을 받는 `worker`, `postgres`, 로컬/오브젝트 데이터 volume. UI는 read-only, DB 포트는 내부망, 외부 노출은 인증된 reverse proxy 하나. 별도 큐·Redis·Kubernetes는 초기 필수 아님.
3. VPS/클라우드: 운영 데이터의 영구 volume/DB·암호화 백업·관측·사용자 인증이 준비된 후 선택. API/UI 분리는 실제 다중사용자 수요 뒤 결정한다.

## 업무별 주기 제안 (활성화 안 됨)

| 작업 | 주기/의존성 | 중복·실패 격리 | 운영 수용조건 |
|---|---|---|---|
| 시장 수집 | 해당 시장 마감+buffer 후; DST/휴일 calendar | source 단위 key+retry, batch 완료 manifest | raw staleness·누락봉·hash 통과 |
| 거시 수집 | 공식 발표 달력+재시도; 일중/빈티지 시각 | 소스별 worker, schema 변경 격리 | release 메타 없으면 학습 금지 |
| 일일 예측 | target별 적격 snapshot 승인 뒤 | target/date/h/model unique, job lease | run/manifest/ledger 완료 뒤 공개 |
| 재학습 | 주간 제안, 사전등록한 cutoff·설정 | inference/재학습 분리, shadow 검증 | 새 모델 manifest 승인 후 승격 |
| 만기 채점 | 새 수집 성공 후 매일 | label당 첫score; stale/late 제외 | 새 outcome snapshot 연결 |
| 뉴스 | 허용 소스별15~60분 제안 | source/event ingest 독립, LLM 예산 한도 | 검증 보류 상태 보존 |
| 백업 | 변경 뒤/일별 제안 | DB online backup·snapshot 별도 복제 | hash·integrity·실제 restore 검사 |

정시 실행을 보장하지 않는 환경에서는 마감시각 대신 readiness와 데이터시각을 기준으로 판단한다. `task_key, attempt, lease_until, heartbeat, status, error_class` 작업 테이블과 재시도 횟수/최대나이를 둔다. 동일 target 작업 lock, 만료 lease 회수, 실패 알림·수동 재시도 명령을 제공한다. 사용자 요청 없이 스케줄을 만들지 않는다.

[GitHub 공식 schedule 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule): 지연/누락 가능, 기본 브랜치에서 실행, public 저장소60일 무활동 시 비활성화. 따라서 현재 feature 브랜치의 CI가 production scheduler가 되는 것은 아니다. Actions의 runner 로컬 디스크나 cache를 예측 장부 원장으로 쓰지 않는다.

[Render 무료 서비스 공식 제약](https://render.com/docs/free): 유휴 중단/재시작/재배포 시 로컬 파일 소실, free web에는 영구 disk 불가, free Postgres30일 만료. SQLite 장부 보관 용도로 부적합하다. [Streamlit 관리 문서](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app)는 앱 운영 안내이며 영구 DB SLA를 확보한 것은 아니다. 무료 UI 서비스의 로컬 파일 영속성을 가정하지 않는다.

## 저장소와 원자성

현재 SQLite는 단일 소유 worker·작은 장부에 적합하다. PostgreSQL 이전은 동시 writer/원격 UI/접근제어 요구가 생길 때 한다. `INSERT ... ON CONFLICT DO NOTHING`, 기존 primary key/첫 기록·첫score, UTC·확률 CHECK·FK를 유지하고 hash/row count를 비교한다. 모델 결과가 바뀌지 않는 offline copy→검증→읽기 전환→단일 writer 전환 순서, 되돌릴 SQLite 백업 보관. 이전 중 양쪽에서 발행하지 않는다.

Parquet는 시계열 본문, DB는 시각/버전/상태/URI 인덱스다. source snapshot의 불변 저장과 run 수준 데이터셋 동결은 다르다. 이번은 소스별 원자 포인터만 구현했다. 다음은 임시 run 폴더→모든 파일 검증→완료 manifest와 `latest` 포인터 교체다. DB INSERT와 파일은 분산 transaction이 아니므로 pending/committed 상태 및 outbox/reconciliation으로 복구한다.

## 수동 백업·복원 실행

```powershell
python scripts/backup_ledger.py --destination data/backups/forward-YYYYMMDD-HHMM.sqlite3
```

SQLite online backup API를 사용하고 `integrity_check`/FK와 행 수를 확인한다. 기존 파일과 원장 자체를 destination으로 주면 거부한다. 이 명령은 원장만 복사하며 스냅샷/모델/아티팩트는 별도 보존해야 한다. 이번 테스트는 백업 파일을 읽어 최초 forecast/score가 같고 trigger가 복원됨을 확인한다. 실제 운영 DB로 덮어쓰는 복구는 수행하지 않았다.

복구 절차: writer 중지→원장 별도 보존→백업을 새 경로에 열어 integrity/FK/예측수·채점수/표본대조→snapshot manifest 해시 확인→읽기 설정을 새 경로로 전환→writer 하나만 재개→누락 job 재처리. RPO24시간/RTO4시간은 초기 목표 제안이며 검증된 SLA가 아니다. 7일 일별/4주 주별 보관안은 사용자 정책 확정 전 자동 삭제하지 않는다.

## 관측·비용

source freshness, schema/해시 실패, 누락봉, job lag/실패율, 예측 발행 지연, ledger duplicate/late/stale, 미채점 수, backup age/복원 성공, 디스크 사용, LLM 토큰/요청/월 예산을 기록한다. 세금/지역/traffic/데이터권리에 따라 요금이 달라 실제 요금 견적을 만들지 않았다. 현재 로컬 연구는 새 유료 인프라를 쓰지 않는다. 향후 호스팅 예산과 뉴스 계약·LLM 상한을 정하면 예산 초과 시 유료 요청을 중단하는 hard cap을 설계한다.
