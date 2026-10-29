# 보안·개인정보·공개 저장소 정책

저장소는 public이다. 코드·한국어 문서·작은 합성 테스트 fixture만 커밋한다. `data/`, `artifacts/`, `.env`, DB·백업·실데이터·기사 전문·계정키를 올리지 않는다. 실행결과는 집계 검증 요약만 문서에 기록한다. 데이터 해시도 소스 계약에 따라 공개 여부를 검토하고 원자료를 CI artifact에 첨부하지 않는다.

로컬 환경변수/비밀 저장소에서 공급자 키를 읽고, URL에 키가 들어가는 API는 요청/예외 로그에서 query credential을 가린다. 현재 ALFRED requests 예외 문자열에 키 포함 URL이 들어갈 위험이 있어 운영 승격 전 redaction을 추가한다. CI는 합성 테스트만, secrets 없이, contents read 최소 권한이다. 의존성 lock/취약점·action pinning은 별도 유지보수 대상으로 관리한다.

위협과 통제:

- 파일 손상/부분 수집: snapshot hash·pointer 교체·실패 시 중단. hash를 함께 수정하는 공격까지 검출하는 전자서명은 아니다.
- 장부 변경: UPDATE/DELETE trigger·최초 INSERT 보존. DB 소유자는 DDL/REPLACE/파일 교체 가능하므로 외부 WORM처럼 표현하지 않는다. 운영 DB 계정은 INSERT 전용 worker·SELECT 전용 UI·분리된 관리자.
- 뉴스/공시 prompt injection: 외부 텍스트를 지시로 실행하지 않음, 도구/SQL/키 권한과 분리, JSON schema·허용 evidence reference 검증.
- SSRF: 향후 URL fetcher는 HTTPS 허용 도메인·redirect 재검증, loopback/사설IP/metadata endpoint 차단·응답크기/시간 제한.
- 공개 UI: 인증·접근권한·TLS, rate/기간/행 제한, 임의파일 경로·SQL·모델 업로드 금지. 키·내부 파일경로·저작권 원문 미노출.
- 사고: 키 노출이면 즉시 폐기/교체, 로그/입력 snapshot 격리, 영향 run/발행시각 식별, 기존 예측 수정 없이 incident·정정 설명 추가. git history 비밀 삭제는 별도 사용자 승인/절차.

개인 투자/계좌/주문정보는 현재 수집하지 않는다. 미래 포트폴리오 기능은 연구 데이터와 별도로 암호화·보관기간·삭제정책을 설계한다. 백업 역시 비공개 접근제어·암호화 대상이다. 이번 작업은 외부 서비스 가입/배포/자동실행·메시지 발송을 수행하지 않았다.
