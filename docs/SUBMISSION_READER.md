# 제출 연구 판독기 입력 계약

최신 구현은 `castguard/submission_reader.py`, 예제는 `examples/submission_reader/shots.json`이다. 기존 `decision_review.py`의 역사적 품질행 순서 입력과 구분한다.

## 실행

```powershell
python -m castguard.submission_reader --input examples/submission_reader/shots.json --output demo.json --html demo.html
```

이미 있는 출력은 덮어쓰지 않는다. 추론 시 원본/정답 테이블을 조회하지 않고 해시를 검증한 모델·학습 범위만 읽는다. 검증된 패키지의 joblib만 사용한다.

## 현재 관측과 과거 회신

- 상위 필드: `schema_version: castguard-research-reader-v1`, 비어 있지 않은 `records` 배열.
- 각 관측: `record_id`, `run_key`, `event_order`, `shot`, `product_type`, `measurements`. ID는 빈 문자열이 아니며 공정 순서·Shot은 음수가 아닌 정확한 정수다. 한 패킷의 현재 ID 및 (run, event) 중복은 거절한다.
- `event_order`는 품질검사 유무와 독립된 동일 run의 공정 이벤트 순서다. 실제 MES 대응과 run 경계는 현장 확인 대상이다.
- 품질 모델의 현재값은 공정14와 센서6, 제품코드다. 필드명은 코드의 `PROCESS`, `SENSORS` 및 예제를 따른다. 현재 품질 정답이나 상태 정답은 허용하지 않는다. 누락된 현재 입력은 점수를 산출하지 않는다.
- `quality_feedback`의 각 회신은 `run_key`, `event_order`, `available_event`, 이진 `defect`다. 현재 공정 t에서 같은 run의 e≤t−20이며 e+20≤available_event≤t인 이미 도착한 과거 회신만 허용한다. 중복 회신·다른 run·현재/미래 라벨·조기 회신은 거절한다.
- `feedback_ledger_complete: true`는 호출자가 현재까지 도착한 회신을 모두 전달했다는 선언이다. 프로그램이 외부 원장의 진실성이나 누락을 입증하는 것이 아니다. 회신이 없으면 학습 대치값을 사용하고 경고한다.
- 선택적인 `process_history`는 과거 run/event/Shot/공정14를 전달한다. Gate 계산에는 직전 최대20개 공정 이벤트가 모두 필요하다. 미완전 이력에서는 Gate를 계산하지 않는다. 이력에 현재/미래 event, 다른 run, 중복 event, 현재 이상 Shot을 넣으면 거절한다.

현재 품질 입력에는 `shot_position`을 사용하지 않는다. 과거 품질 회신은 원천 품질행 수로 지연시키지 않고 공정 event로 지연시킨다. 단위와 수집 Hz는 원천에서 확정되지 않았으므로 event를 분/초로 치환하지 않는다.

## 자동 판단의 범위

1. 입력 계약 검사 → validation 선택 모델의 품질 점수와 log-odds 개별 기여 계산.
2. 학습 범위·제품·고정 변수쌍의 공동지지·과거 회신 경고 생성.
3. 경고가 있으면 사람 검토, 경고 없는 고위험이면 추가검사 검토 요청, 그 외 기존 검사 유지.
4. 기존 동결 Gate가 상태1을 표시하면 품질·설비 담당자 공동 검토. 물리적 고장 의미와 현장 정상 FPR은 미확인이다.

위험 점수는 보정된 불량 확률이 아니다. 자동 제어/MES 쓰기·생산중지·설정 변경은 없고 정상 표시도 기존 검사를 면제하지 않는다. 1,387개 재사용 test 중 1,168개에 범위/지원 경고가 생겼으며 해당 행을 성능 분모에서 제거하지 않았다.

현재 호출은 상태 없는 연구 패킷이다. 호출 간 중복 추적·원장 대조·서로 다른 패킷의 충돌 조정·실제 수신시각 인증은 지원하지 않는다. 코드의 개별 검사로 원천 공급 계약이 검증됐다고 표현하지 않는다. 화면의 FIFO/Q/GQ 수치는 이전 동결 정책의 별도 비교이며 새 판독기의 운영 KPI가 아니다.

## 확인 범위

전체 회귀 413개 통과, 새 연구/판독 검사15개 포함. 실제 공정 예제24건은 저장 점수와 최대차5.6e−17이다. 동일 자료의 전체 재학습 재현210그룹은 최대차0이며 새로운 독립 평가가 아니다. HTML 내용 생성과 판독 CLI는 확인했으나, 도구 보안 정책이 로컬 file URL을 차단하여 브라우저 화면/펼침 조작 검수는 미완료다.
