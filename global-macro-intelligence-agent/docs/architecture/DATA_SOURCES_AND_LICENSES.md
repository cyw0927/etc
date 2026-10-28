# 데이터 취득·권리·공급자 위험

확인일 2026-10-28. **API 접근 가능 ≠ 과거 빈티지 제공 ≠ 공개 재배포 허용**이다. 아래 인증·한도는 공식 문서에서 확인한 범위이며 계정별 권한을 부여받은 것은 아니다. 키 발급·유료 구독·서비스 가입을 수행하지 않았다. 무료 개인 연구와 공개 서비스는 별도 출처 허용 목록을 쓴다. 권리 미확인은 공개 API/UI에서 원자료 재배포를 차단한다.

| 공급자·공식 근거 | 인증·실제 제공 범위 | 주기·결측·PIT 위험 | 개인 연구 / 공개 서비스 판정 |
|---|---|---|---|
| [yfinance](https://ranaroussi.github.io/yfinance/) | 비공식 Yahoo 클라이언트, OHLCV/수정종가; 이번 10개 수집 | 일별; 누락·스테일·과거 조정치 수정·티커 변경; SLA 없음 | 개인 연구 지향. 공개 가격 재배포 권리는 확보되지 않음; 정식 라이선스 공급자 검토 |
| [FRED/ALFRED](https://fred.stlouisfed.org/docs/api/fred/series_observations.html) | API 등록 키; observation/realtime/vintage_dates, 페이지네이션. fredgraph CSV는 현재값 | 일/월/분기; 날짜 빈티지는 일중 release와 다름. 금리도 공개시각·정정 가능성 검증 필요 | 시리즈별 원권리 확인. 현재 금리·표시 macro 7개 수집; ALFRED 키 없음 |
| [ECOS 공식 포털](https://ecos.bok.or.kr/api/) | 한국은행 공식 API 진입점 확인. 페이지 본문을 이번 도구에서 추출 못함 | 한국 금리·환율·통화·국제수지 후보; 테이블/단위/정정·release 보관 여부 추가 확인 | 인증·quota·재배포 약관 세부 미확인. 어댑터 계약 전 공식 가이드 수동 확인; 아직 구현 안 됨 |
| [KOSIS 개발가이드](https://kosis.kr/openapi/devGuide/devGuide_0201List.do) | apiKey; 통계표/항목·분류별 JSON/SDMX | 주기별 기간코드; 표 개편·분류 변경·수정값. 최신 갱신일은 최초 공개일 아님 | 무료 연구 후보; 통계정보 활용약관/원작성기관 조건 확인 후 공개 허용 |
| [BOJ API 안내](https://www.stat-search.boj.or.jp/ssi/docs/info/nme_aphelp_en.html) | 공개 API, getDataCode/getDataLayer/getMetadata, JSON/CSV | 금리·통화·자금순환 등 BOJ 시계열; 공개본의 과거 수정 가능 | [공식 이용조건](https://www.stat-search.boj.or.jp/info/api_notice_en.pdf)은 서비스 공개 시 BOJ 통지와 크레딧 요구. 발송·공개는 별도 승인 후 |
| [e-Stat FAQ](https://www.e-stat.go.jp/api/en/api-dev/faq) | 사용자 등록/app ID 필요; DB형 통계 대상 | 일본 물가·생산·고용 등; 기관별 갱신 시각, API 미제공 파일 존재 | 출처 크레딧·이용약관 하 상업 이용 안내; 빈티지 자동 제공으로 해석 금지 |
| [중국 NBS](https://www.stats.gov.cn/english/Statisticaldata/annualdata/) | 공식 통계 진입점 확인; 페이지 본문 추출 제한 | 성장·물가·산업·소비 후보; 공개 달력·기준 변경·수정 중요 | 안정된 공개 API 계약/권리 확인 못함. 비공식 endpoint 역공학 대신 공식 파일/발표 원문 수동 확보부터 |
| [IMF API](https://data.imf.org/en/Resource-Pages/IMF-API) | SDMX 2.1/3.0; 탐색 Swagger는 포털 로그인 안내 | 국제수지·거시/금융·WEO 등 데이터셋별 주기. 전망과 실적 구분 | 데이터셋·포털 권한/이용조건 확인. 하나의 옛 IFS endpoint를 영구 계약으로 가정하지 않음 |
| [OECD 공식 Swagger](https://sdmx.oecd.org/public/swagger/index.html?urls.primaryName=v1) | SDMX REST 경로 확인; 실행 인증/quota는 미검증 | 국가 비교 통계, 구조(DSD)·단위·시즌 조정·버전 변경 | 어댑터 전 flow/DSD와 데이터별 사용조건 동결, bulk 요청 예산 |
| [BIS 도구](https://data.bis.org/help/tools) | SDMX API로 데이터·메타 JSON/XML/CSV | 정책금리·실효환율·신용·국제은행·글로벌 유동성; 발표 지연/개정 | [사용조건](https://data.bis.org/help/legal): 출처·번역 비공식 표시·오해 유도 금지·상업 제품 추가 요금 관련 조건 확인 |
| [World Bank Indicators](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation) | V2 Indicators API, 국가/지표 메타·값, 키 없이 이용 안내 | 주로 저빈도 구조 지표; 결측·소급 개정, 즉시 거래 피처에 부적절 | 데이터별 라이선스·제3자 제한 확인 후 국가 구조 설명용 |
| [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | submissions/companyfacts JSON, 키 불필요; accession·공시정보 | 공시 이벤트별, XBRL 단위/차원/정정/회계기간 중복; companyfacts만으로 완전 PIT 아님 | [자동접근 상한 10 req/s](https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits). 식별 User-Agent·연락처·캐시, 기본 2 req/s 제안 |
| [DART 재무정보](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003) | 등록 인증키; 회사/보고서별 재무·XBRL | 분기·연간/정정; 연결·별도 구분, 누적 현금흐름→단독 분기 변환 | [020 오류](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)는 일반적으로 20,000 이상 요청이나 개별 한도 다를 수 있음. 계정 한도·약관 확인 |
| 외신·정부·기업 문서 | 허용 RSS/라이선스 API·공식 발표만. 매체별 계약 미확보 | 기사 수정·철회·유료벽·통신사 재인용 | Reuters/AP/FT/Bloomberg/Nikkei/SCMP/Al Jazeera 등을 비교 대상으로 검토하되 무료 수집권 가정 금지. 링크·허용 메타데이터 우선 |

## 공통 소스 계약 (향후 registry)

`source_id, terms_url, terms_checked_at, attribution, personal_research_allowed, public_redistribution_allowed, derivative_use, retention_policy, credential_env, max_rps, daily_budget, timeout, retry_policy, authority_tier, coverage, vintage_support`를 기록한다. 권리 미확인은 false/unknown으로 처리한다. source registry는 법률적 사용 허가를 만들어 내지 않는다.

429/503은 Retry-After 및 지수 백오프+지터, 401/403은 키/권리 오류로 중단한다. 파싱 실패·빈 응답은 신규 snapshot으로 품질 격리하고 마지막 정상본의 나이를 표시한다. 공급자 실패 때 과거 캐시를 최신 자료로 표시하지 않는다. 원출처 둘의 값이 다르면 단위/빈티지/시각부터 비교하고 평균으로 덮지 않는다.

정확한 계정 quota와 시장/뉴스 재배포 계약은 공개서비스 전 필수 결정이다. 이번 구현은 공급자 어댑터를 추가하거나 이러한 권한을 취득하지 않았다.
