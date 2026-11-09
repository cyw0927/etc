# 리서치 Agent 프로토타입 (KIC AI Agent 공모전용)

상태: **프로토타입.** 도구·검증기·Agent 루프·오류 주입 평가는 구현되고 테스트됐다. 실제 Claude 호출로 끝까지 돌린 기록은 API 키 설정 후 남긴다.

## 무엇을 하나

질문 하나와 기준 시각(as-of)을 받는다. Claude가 질문을 나누고 도구를 호출해, 근거가 연결된 짧은 리서치 메모를 쓴다.
- **숫자는 도구만 만든다.** 메모의 숫자는 `{{ev:<근거 ID>}}` 슬롯으로만 들어가고, 화면에 표시할 때 근거 값으로 채워진다.
- **기준 시각은 하네스가 정한다.** 모델이 바꿀 수 없다. 도구는 그 시각까지 공개된 값만 돌려준다.
- **메모는 두 번 검증한다.**
  - 규칙 검증기(코드): 직접 타이핑한 숫자, 없는 근거, 기준 시각 이후 근거, 근거 없는 주장을 거부한다. 거부된 메모는 최대 2회 되돌려 보낸다.
  - 의미 검증(Claude 별도 호출): 각 문장이 인용한 근거와 같은 말을 하는지 판정한다.

## 데이터 (키 없이 받는 공식 원자료)

| 시리즈 | 출처 | 사용 가능 시각 규칙(보수적 가정) |
|---|---|---|
| 미국 10년 실질금리, 10년 국채금리 | 미 재무부 일별 수익률 CSV(2003~) | 관측일 다음 날 06:00 ET |
| 원/달러 | 연준 H.10 과거 자료(2000~) | H.10은 월요일 16:15 ET에 지난주 값을 공개한다. 관측 주 다음 화요일 17:00 ET로 잡는다 |

두 출처 모두 발표 후 값을 수정하지 않는 시리즈만 쓴다. 그래서 현재 스냅샷으로 과거 기준 시각 질문에 답해도 수정치가 섞이지 않는다. 원본 파일은 `data/agent/snapshots/`에 해시와 함께 불변으로 보관한다(`.partial`로 쓰고 완성 후 이름 변경). FRED와 Yahoo는 쓰지 않는다.

## 실행

```powershell
.venv\Scripts\python.exe -m pip install -e ".[agent]"
.venv\Scripts\python.exe scripts\agent_fetch.py
# ANTHROPIC_API_KEY: 사용자 환경변수 또는 프로젝트 폴더의 .env(커밋 제외)에 ANTHROPIC_API_KEY=<키> 한 줄
.venv\Scripts\python.exe scripts\agent_ask.py "미국 10년 실질금리가 최근 상승했다. 원/달러 환율의 향후 20거래일에 어떤 의미인가?" --as-of 2026-11-02
.venv\Scripts\python.exe scripts\agent_eval_injection.py            # 규칙 오류 주입(무료)
.venv\Scripts\python.exe scripts\agent_eval_injection.py --semantic # 방향어 뒤집기(API 사용)
```

결과는 `data/agent/runs/<시각>-<id>/`에 `memo.md`(근거 표 포함)와 `run.json`(도구 호출, 근거 목록, 검증 결과, 토큰 사용량)으로 남는다.

## 코드

- `src/gmia/agent/sources.py`: 수집·스냅샷·파싱·사용 가능 시각 규칙
- `src/gmia/agent/tools.py`: `list_series`, `get_latest`, `get_change`, `conditional_outcomes`와 근거 레지스트리
- `src/gmia/agent/memo.py`: 메모 스키마, 규칙 검증기, 렌더러
- `src/gmia/agent/agent.py`: Claude 도구 호출 루프(`claude-opus-5-5`, adaptive thinking, 서버 측 fallback), 의미 검증
- `src/gmia/agent/inject.py`: 오류 주입 변형
- `tests/test_agent.py`: 파서, 시점 규칙, 기준 시각 이후 값을 바꿔도 결과가 같은지, 규칙 위반별 검출, 가짜 클라이언트로 돌린 루프

## 한계

- 시리즈 3개, 도구 4개뿐이다. 기획서의 근거 Agent(공식 문서 검색)와 예측 장부 연결은 아직 없다.
- 사용 가능 시각은 실제 공개 시각을 관측한 것이 아니라 보수적 규칙이다.
- 조건부 통계는 과거 연관성이다. 인과 효과나 예측력으로 해석하지 않는다.
