# 거시 전진 예측 및 WTI 공급원 검증

## 거시 연구 예측

`preregistration_macro_forward.md`에 따라 고정된 연구용 모델과 SPY 5거래일 라벨만 사용한다. 4개 ALFRED 원본 수정 이력과 모델 해시·수집 및 학습 완료시각을 검증하고, 날짜로만 알려진 수정일에는 이틀 지연을 적용한다. 미국 정규장 마감과 다음 개장 사이에만 발행한다. 모든 값을 해당 발행 시각 전에 로컬로 실제 수집한 경우만 사용하며, 각 관측월·수정일·값과 수집시간은 새 장부의 manifest에 기록된다. ALFRED 수정일은 정확한 일중 발표시각이 아니고 이틀은 연구 가정이다. 과거 학습의 가격 및 거시 빈티지는 현재 재구성된 자료이므로 과거 당시 실제 수집을 증명하지 않는다. 신호의 성능은 아직 검증되지 않았다.

예측 장부는 `data/operations/macro_forward/ledger.sqlite3`이며 기존 장부와 분리돼 있다. 최초 예측과 최초 점수는 수정·삭제를 막는 트리거와 고유키를 사용한다. 저장장치를 관리하는 사람에 대한 암호학적 불변성은 아니다. 만기 점수는 같은 새 장부에만 저장하며, 누락된 거래일이나 수정된 기준가가 있으면 중단한다. 채점은 설명용 Brier 오차만 기록하며 우위나 유의성 검정을 하지 않는다. 부주의한 DB 파일 교체를 막기 위한 별도 백업과 복구 연습이 필요하다.

```powershell
.\.venv\Scripts\python.exe scripts/issue_macro_forward.py --model <모델_JSON> --vintages <ALFRED_수집본> --price-batch <가격_수집본>
.\.venv\Scripts\python.exe scripts/issue_macro_forward.py --model <모델_JSON> --vintages <ALFRED_수집본> --price-batch <가격_수집본> --issue
.\.venv\Scripts\python.exe scripts/score_macro_forward.py --batch <만기_이후_수집본>
.\.venv\Scripts\python.exe scripts/score_macro_forward.py --batch <만기_이후_수집본> --write
```

최초 명령은 기록하지 않으며 36시간 이상 지난 거시 수집본은 발행이 차단된다. 새 ALFRED 수집본은 `collect_alfred_web.py`로 별도 생성한다. 모델은 사전등록한 해시로 고정돼 있다. 다음 개장 전 최신 완료 봉과 시각 검증에 실패하면 해당 회차는 발행하지 않는다. 자동 스케줄이나 배포는 없다.

## WTI 선물 공급원

| 공급원 | 공식 문서로 확인한 내용 | 실제 접근 검증과 제한 |
|---|---|---|
| [CME Continuous Price Series](https://www.cmegroup.com/market-data/cme-group-continuous-price-series.html) | CLCP1은 최근월, CLCPA는 유동성 기준. 표준 파일에 정산가격·계약 식별·다음 전환일이 있다. 최근월 방식은 만기 2영업일 전 전환. 확장 파일은 거래량·미결제약정과 잠정/최종 버전 제공. | 거래소 라이선스 및 접근 계약 필요. 최신 실제 파일이나 정산값을 받지 않아 모델 사용 미검증. |
| [Databento GLBX.MDP3](https://databento.com/docs/datasets/glbx-mdp3) | CME Globex 개별 계약과 타임스탬프 제공. [연속 심볼](https://databento.com/docs/conventions/symbology)은 만기·이전일 거래량·이전일 미결제약정 기준을 구별한다. 가격은 [롤 시 무조정](https://databento.com/docs/examples/symbology/continuous)이다. | 계정·API 접근 및 계약/요금 확인 필요. 실데이터·계약 식별 매핑을 직접 검증하지 못함. 사용자 승인 없이 가입·결제하지 않음. |
| [EIA RCLC1](https://www.eia.gov/dnav/pet/hist/rclc1d.htm) | 공개 원본은 원유 선물 1계약의 일별 시세. | 실제 파일은 2024-04-05 이후 중단, 개별 계약·롤 정보 부족. 최신 사용 불가. |

공급원 문서 확인은 실제 최신 데이터 수집·이용권·롤 검증 완료와 다르다. WTI는 유효한 라이선스와 데이터, 계약별 정산·롤 검증 및 별도 사전등록 전 계속 차단한다.
