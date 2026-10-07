# 정답 없는 Shot 판독 실행

## 두 입력 경로의 구분 · 2026-10-05 13:10 KST

**이 문서는 `decision_review.py`의 역사적 A/queue 재생 경로다.** 품질 파일의 `quality_record_position`을 요구하므로 새 생산 관측용 카운터로 바꿔 사용할 수 없다. 기존 코드·예제는 보존한다.

새로 추가한 [공정14 관측 입력 경로](OBSERVABLE_QUALITY.md)는 `observable_quality.py`와 다른 schema를 사용한다. 원래 A0 동결 모델로 카운터·이력·품질 파일 없이 계산하며, 아래 경로와 자동 전환하지 않는다. [새 예제](../reports/observable_quality/example_output.html). 입력 처리 능력과 현장 수신/미래 성능 검증은 구분한다.


2026-10-05 구현 및 순서/이력 검증 보강. 새 학습 없이 기존 검사 비교의 동결 모델을 실행한다. 입력에서 품질 점수·설비 상태1 점수·각 모델의 개별 설명·학습 범위 경고·미산출 사유를 출력한다. 출력은 연구 재생이며 실제 라인 적용, 정책 우위, 보정된 불량 확률이나 제어 권고를 뜻하지 않는다.

## 바로 실행

프로젝트 `C:\Users\JH\Desktop\workspace\contest`에서 실행한다. 처음 한 번 사용할 새 출력 이름이다. 같은 파일이 있으면 덮어쓰지 않고 종료하므로 다음 실행에는 파일명을 바꾼다.

```powershell
& .\.venv\Scripts\python.exe -I -B -X utf8 decision_review.py `
  --input examples/decision_review/shots.json `
  --output reports/decision_review/my_review.json `
  --html reports/decision_review/my_review.html
```

저장한 HTML은 브라우저에서 바로 열 수 있다. 서버·네트워크·정답·원본/전처리 데이터는 필요 없다. 로컬의 `configs/decision_review.json`과 해당하는 `reports/oct03_queue/models/*.joblib` 두 개는 필요하다. 공개 소스만 받은 환경에는 저장 모델이 없으므로 실제 추론을 할 수 없다. 자동 다운로드·학습·모델 대체는 하지 않는다.

기본 체크포인트는 `queue-fold2-seed17`이다. 가장 이른 고정 fold와 고정 첫 seed를 기능 예시에 사용하며 점수가 좋은 모델을 고른 것이 아니다. `--checkpoint queue-fold4-seed17`처럼 바꿀 수 있다. fold는 2/3/4/6, seed는 17/29/43/71/101의 20개 조합이다. 각 조합은 당시 선택된 품질·설비 모델만 사용한다. 다른 fold의 결과를 같은 모델의 설명이나 새로운 독립 평가로 읽지 않는다.

```powershell
& .\.venv\Scripts\python.exe -I -B -X utf8 decision_review.py `
  --checkpoint queue-fold4-seed17 `
  --input examples/decision_review/shots.json `
  --output reports/decision_review/fold4_review.json
```

JSON 문법·전체 schema·모델·배치 관측 일관성 문제가 있으면 종료코드 2로 실패하며 점수를 쓰지 않는다. 서로 다른 ID라도 같은 `(run_key, sequence)`이면 중복 관측으로 거절한다. 현재/과거 Cycle_Time의 모순이나 역사적 품질 순서의 역전/재사용도 배치 전체를 거절한다. 그 밖의 개별 입력 오류는 해당 행의 `invalid_input`으로 남기고 나머지 행을 계속 처리한다. 그 경우 종료코드는 0이며 출력의 `records[].status`를 반드시 확인한다. 입력 행을 몰래 삭제하지 않는다.

## 예제와 기대 동작

[입력 7건](../examples/decision_review/shots.json), [선택·변형의 출처](../examples/decision_review/provenance.json), [기대 요약](../examples/decision_review/expected_summary.json), [실제 JSON](../reports/decision_review/example_output.json), [실제 HTML](../reports/decision_review/example_output.html).

| 입력 | 기본 체크포인트의 결과 | 해석 |
|---|---|---|
| observed-product1 | 품질 점수 0.3098313162, 설비 상태1 점수 약 0.0000005513 | 과거 학습행의 기능 예시. 제품·개별 변수 범위 안이며 미래 성능 근거가 아님 |
| unseen-product2 | 품질 점수 0.9991123431과 `unseen_product`·범위 경고 | 높은 점수여도 학습에서 보지 못한 제품. 운영 판단은 보류하며 이 행을 성능 분모에서 제거하지 않음 |
| missing-sensor | 품질 미산출, 설비 점수 산출 | Factory_Temp가 실제 입력에 없음 |
| missing-process | 두 모델 모두 미산출 | 현재 Cycle_Time이 없음 |
| invalid-type | `invalid_input`, 두 모델 실행 안 함 | 압력이 숫자 문자열/문자가 아니라 실제 JSON 수여야 함 |
| unsupported-position-basis | 품질 미산출, 설비 점수 산출 | 물리 Shot 번호를 과거 품질 입력 순서로 치환하지 않음 |
| unknown-history | 품질 산출, 설비 미산출 | 이전 공정 관측 이력의 부재를 run 시작과 혼동하지 않음 |

품질 사례는 제품1·2 각각에서 입력이 완전한 첫 행을 원래 순서로 택했다. 정답이나 예측 성공 여부를 보고 고르지 않았다. 나머지 5건은 제품1 사례의 명시적 결손/오류 변형이며, 서로 다른 **가상 시나리오 run 이름**을 쓴다. 실제 추가 run으로 수집한 데이터가 아니다. 하나의 실제 관측을 다른 값으로 중복 기재한 배치로 혼동하지 않도록 분리했다. 실제 예제의 원자료 키와 해시는 provenance에 있다. 기존 7건의 점수/상태는 순서 검증 보강 후에도 같다. `_1/_2` cavity 대응이나 물리 단위를 새로 확정한 것이 아니다.

## 입력 계약

전체 형식은 [JSON Schema](../configs/decision_review_input.schema.json)와 실행기 검증을 함께 따른다. `schema_version`은 `castguard-shot-v1`, `records`는 비어 있지 않은 배열이다. 허용되지 않은 키는 무시하지 않고 거절한다.

| 위치 | 의미·형식 |
|---|---|
| record_id | 앞뒤 공백이 없는 고유 문자열. 배치 내 중복은 거절. 출력 연결에만 쓰며 모델 입력이 아님 |
| observation.run_key | 앞뒤 공백 없는 문자열. 동일 설비·기록 세션의 공정 흐름을 식별해야 함. 역사적 예제의 run 번호는 실제 설비 ID 인증이 아님 |
| observation.sequence | 해당 run의 전체 공정 관측 순서, 0부터 시작. 물리 Shot 번호가 아님 |
| observation.quality_record_position | 기존 품질 입력 기록의 중복 제거 후 run 내 순서, 0부터 시작. 모델의 shot_position으로 전달 |
| observation.position_basis | 품질 모델에는 `legacy_quality_input_order`만 허용. 수신시각·운영 카운터 계약 미확인 상태를 숨기지 않음 |
| measurements | 공정14개, 센서6개, Product_Type. JSON 숫자/명시적 null; Product_Type은 양의 정수 |
| history | 같은 run의 정확히 직전 min(sequence,5)개 공정 관측. 각 항목은 run_key, sequence, Cycle_Time. 현재·미래·역순·다른 run·부분 이력은 거절 |

현재 공정14개: Velocity_1/2/3, High_Velocity, Cylinder_Pressure, Rapid_Rise_Time, Biscuit_Thickness, Clamping_Force, Cycle_Time, Pressure_Rise_Time, Casting_Pressure, Spray_Time, Spray_1_Time, Spray_2_Time.

센서6개: Melting_Furnace_Temp, Air_Pressure, Coolant_Temp, Coolant_Pressure, Factory_Temp, Factory_Humidity.

**중요한 미해결 입력:** 과거 `shot_position`은 `castguard/rebuild.py`의 품질 입력 행별 cumcount다. 실제 Shot 번호나 전체 공정 순번과 같지 않다. 신규 현장 입력에서 이 정의를 재현할 근거가 없으면 `position_basis`를 임의로 인정하지 말고 품질 판독을 보류한다. 이 기능은 완전한 현장 배포 문제가 해결됐다는 주장이 아니다.

`history`가 누락/null이면 설비 판독을 보류한다. `sequence=0, history=[]`는 확인된 run 시작이므로 이전 이력값 둘을 null로 만들고 **기존에 학습된 median imputer**를 적용한다. 과거 Cycle_Time의 명시적 null도 해당 전처리를 그대로 따른다. 현재 필수 입력의 누락/null은 모델별 미산출로 처리한다. 임의의 0·문자열 수치 변환·새 중앙값 학습은 하지 않는다.

`Machine_Status`, 불량26열, `y_*`, `oracle_*`, `source_row`, `run_id`, 직접 입력한 `shot_position`·`prev_cycle_time` 등은 허용 입력에 없다. 라벨이나 파생 이력을 입력에 끼워 넣으면 거절한다. 원자료 파일 존재나 정답 유무로 추론 대상을 고르지 않는다.

## 순서·이력의 지원 범위

이 도구는 **각 행이 자신의 과거 이력을 명시하는 상태 없는 판독기**다. CLI/API 호출 사이에 입력을 보관하거나 run을 자동으로 추정하지 않는다. 이미 앞선 행을 같은 배치/이전 호출에 보냈더라도 현재 행의 `history`를 생략하면 설비 판독을 보류한다. `record_index`는 화면/JSON의 배치 위치일 뿐 모델 특징이 아니다.

| 상황 | 지원 계약과 실제 처리 |
|---|---|
| 전체·일부·역순 배치, 개별 호출 | 동일한 관측 메타데이터·현재값·직전 이력을 그대로 보내면 행별 점수/설명/경고가 동일하다. 출력 위치인 record_index만 달라질 수 있다 |
| 배치에서 관측/품질 행 생략 | 원래 sequence와 quality_record_position을 유지한다. 배치 내 순번이나 라벨 있는 행의 순번으로 다시 매기지 않는다. 이력을 product/품질 관측/라벨 유무로 거르지 않는다 |
| 같은 관측을 여러 ID로 입력 | `(run_key, sequence)`가 같으면 내용이 같아도 배치 전체를 거절한다. “첫 행/마지막 행 우선” 규칙이나 자동 병합은 없다. 같은 관측의 대안 실험은 별도 호출로 수행한다 |
| 현재값과 다른 행의 과거값 충돌 | 같은 관측의 Cycle_Time이 다르면 전체 거절한다. 서로 겹치는 이력끼리의 충돌과 명시적 null 대 수치의 충돌도 포함한다. 개별 입력 검증을 통과한 행의 이력 진술을 대조한다 |
| 품질 순서 중복·역전·비정상 증가 | 동일 run에서 지원하는 historical basis의 품질 순서는 process sequence에 따라 엄격히 증가하며 증가량이 process 증가량을 넘을 수 없다. 해당 교차 행 모순은 전체 거절한다 |
| 앞선 관측이 통째로 없음 | history=[]를 중간 run에 쓰거나 일부 전임자를 빼면 입력 오류다. 모르는 이력을 null/생략으로 표시하면 설비 점수만 보류한다. 누락 이벤트를 임의 null Cycle_Time 관측으로 만들지 않는다 |
| 관측은 있으나 Cycle_Time 결측 | 그 관측을 정확한 run/sequence와 명시적 null 값으로 전달할 수 있다. 기존 median imputer를 그대로 적용하며 설명과 history_missing_cycle_values에 결측을 표시한다 |
| 제품이 바뀜 | 제품 변경만으로 run/sequence를 리셋하거나 다른 제품의 과거 공정 관측을 빼지 않는다. 같은 설비 run의 공정 이력 전체가 기준이다. 품질 제품2는 진단용 점수+미학습 경고다 |
| 여러 설비/run 혼합 | 각각 고유 run_key로 분리한 완전한 패킷은 같은 배치에 넣을 수 있다. 다른 run의 history는 거절한다. 실제 설비·세션 분리의 진실성은 입력 제공자가 보장해야 하며 판독기가 인증하지 않는다 |
| 동일 타임스탬프·지연 도착·시간대 | 이 schema는 timestamp/event_time/tie_breaker를 받지 않고 거절한다. 동률 시각이나 도착 순서로 특징 순서를 추정하지 않는다. 원천의 고정 관측 순서를 확보하지 못하면 지원하지 않는다 |
| 호출 간 중복·충돌·재전송 | 영속 원장/스트리밍 수집기가 없어 자동 탐지하지 못한다. 완전한 독립 패킷의 재생만 지원하며 exactly-once 수집이나 실시간 운영 계약을 주장하지 않는다. 출력에 cross_call_consistency_checked=false를 표시한다 |

정수 카운터와 제품 번호는 0/1의 각 하한부터 `2**53−1`까지 받는다. 더 큰 정수를 모델용 실수로 조용히 반올림하지 않는다. JSON Schema가 표현하지 못하는 교차 행/이력 규칙은 runtime에서도 검사한다.

**운영형 계약과 역사적 특징을 구분한다.** 설비 점수는 전체 공정 관측의 현재값·직전 관측을 명시한 패킷에서 계산할 수 있지만 실제 입력 도착시각·상태 코드 의미·현장 성능은 검증되지 않았다. 품질의 `quality_record_position`은 고정된 과거 품질 입력 파일에서 중복 제거 후 만든 cumcount로, 앞으로 수신할 모든 생산 Shot에 적용되는 카운터가 아니다. 이 도구는 값 자체를 정답 파일이나 현재 배치에서 계산하지 않으며 출력에 `quality_position_use=retrospective_only`를 표시한다. 현장 정의가 없으면 basis를 물리 Shot/도착순서로 바꾸거나 legacy라고 추정하지 말고 품질 판독을 보류한다.

역사적 예제 생성은 원래 `source_row`가 유일한 공정 순서일 때만 정렬하고, source_row 또는 관측 키의 동률/중복을 거절한다. 추론 단계는 과거 CSV를 다시 읽거나 라벨 유무로 run·순서·대상을 재생성하지 않는다. 이미 만들어진 고정 메타데이터를 바꾸면 모델 입력이 바뀐 것이며, 일반적인 입력 재현 보장은 그 변경에 적용되지 않는다.

## 전처리와 설명의 의미

품질: 공정14+센서6+제품+기존 품질 입력 순서. 설비: 공정14+직전 Cycle_Time+직전 최대5개 Cycle_Time의 최대값이다. 후자의 두 값은 전달받은 과거 관측에서 계산하고 현재 값을 섞지 않는다.

저장된 imputer와 로지스틱의 scaler를 그대로 적용한다. 모델·입력 순서·단계 구성·클래스·해시가 맞지 않으면 실행을 거절한다. 새로운 모델 파일이나 임의 joblib 업로드를 읽는 인터페이스가 아니다.

| 모델 | 개별 설명 | 기준값·단위 |
|---|---|---|
| LogisticRegression | 변환 후 입력 × 학습 계수 | 표준화 좌표 0에서의 절편. TreeSHAP 평균 기준값과 다름 |
| LightGBM | 모델 내장 pred_contrib의 TreeSHAP | 모델이 반환한 기대 raw margin |

둘 다 **숫자 클래스1의 log-odds**다. 기여 0.2를 불량 확률 20%p로 해석하지 않는다. 기준값+전체 기여 합은 실제 raw margin을 재구성하고 sigmoid 결과는 실제 모델 점수와 맞아야 한다. 허용오차 1e−6을 넘거나 결과가 비유한 값이면 해당 판독을 미산출한다. 원자료 값, 모델에 전달된 변환값, impute 여부, 전체 기여를 JSON에 남긴다. 상관된 변수의 기여를 물리적 원인·조작효과로 읽지 않는다.

모든 모델은 미보정이다. `score`는 `predict_proba`의 클래스1 출력을 재생한 값이며 검증된 현장 불량 확률이 아니다. 설비 클래스1의 실제 정상/예열 코드 대응도 아직 확정되지 않았다. 기존 calibration 단계가 있어도 확률보정 모델이 있다는 뜻은 아니다.

기본 fold2의 설비 경보는 당시 validation 에피소드 부족으로 비활성화돼 있다. 점수는 산출하되 경보 값은 false가 아니라 **null/disabled**로 표시한다. 다른 checkpoint의 활성 경계도 고정된 연구 비교이며 실제 FPR 보장이나 생산중지 지시가 아니다.

## 적용범위와 의도적 한계

품질 학습의 제품은 모든 큐 checkpoint에서 제품1뿐이다. 제품2 등은 `unseen_product` 경고와 함께 진단 점수를 남긴다. 개별 변수의 train 최소/최대 밖 값도 표시한다. 범위 안에 있어도 다변량 공동지지·물리적 안전·현장 일반화가 검증된 것은 아니다. 이 단계에서는 거리 기반 공동지지나 변수쌍 분석을 구현하지 않았다.

입력이 유효해도 운영 조치는 `abstain`/사람 검토로 둔다. 자동 설비 제어·검사정책 선택·유형 예측·운전창 추천은 없다. 경고를 붙이거나 제품2를 제외한 것을 측정된 성능 개선으로 보고하지 않는다. 현재 명령은 한 건/배치의 **판독 기능**이며 기존 FIFO/Q/GQ 정책 비교 화면은 다음 단계다.

실제 입력 도착시각·품질 입력 순서의 현장 정의·상태 코드·공학 단위·AAS와 실제 CSV의 버전 매핑은 여전히 미확인이다. AAS 원문은 [선별 근거](audit_evidence/2026-10-05/aas_history_extract.json)를 참조한다. 값의 단위 변환이나 임의 cavity 재해석은 수행하지 않는다.

## 검증과 재생

```powershell
# 모델이 없어도 실행되는 schema/설명 adapter 회귀검사: 합성 test fixture만 학습
& .\.venv\Scripts\python.exe -B -X utf8 -m pytest tests/test_decision_review.py -q -p no:cacheprovider

# 전체 동결 모델 + 저장 예측 120건 대조. 새 출력 폴더를 사용
& .\.venv\Scripts\python.exe -I -B -X utf8 verify_decision_review.py `
  --output reports/decision_review/my_verification

# 기존 전체 회귀검사와 새 기능검사를 함께 실행
& .\.venv\Scripts\python.exe -I -B -X utf8 run_review_tests.py

# 동결 모델 2개 checkpoint에서 순서/이력 합성 반례 60건 검증
& .\.venv\Scripts\python.exe -I -B -X utf8 verify_decision_order.py `
  --output reports/decision_review/my_order_verification
```

실제 [동결 모델 검수](../reports/decision_review/verification.json): 20 checkpoint·40개 모델, 저장 예측 120건 최대차 2.8e−17, raw margin 설명 최대오차 2.7e−14, 점수 재구성 최대오차 8.9e−16. 정답 없는 별도 실행 폴더에서 7행 모두 유지, 정답 파일 없음/빈 파일/0/1 및 순서 변경에도 동일 출력이었다. 이는 재현·기능 검증이며 새로운 독립 성능 평가가 아니다.

[순서/이력 반례](../reports/decision_review/order_reliability/adversaries/verification.json)는 고정된 합성 패킷을 실제 동결 모델로 실행했다. 같은 타임스탬프 필드·누락 이력·다른 run·라벨 유입은 미산출하고, 중복 관측·현재/과거 충돌·카운터 모순은 전체 호출을 거절한다. 전체/역순/일부/개별/분할 호출의 유효한 패킷은 정확히 같은 의미의 출력을 냈다. 추가로 실제 저장 예측 재생의 40개 모델 그룹에서 전체/역순/일부 배치와 개별 호출이 일치했다. 합성 시퀀스는 실제 생산 관측이나 성능 분모가 아니다. [이번 통합 기록](../reports/decision_review/order_reliability/integration.json).

`prepare_decision_review.py --output-root <새 폴더>`는 기존 동결 모델과 입력 열만 읽어 프로필·예제를 재생성한다. 프로필 범위는 각 모델 payload의 fit_row_ids로 지정된 inner fit에서만 계산하며 calibration/evaluation의 라벨이나 성능으로 범위를 선택하지 않는다. 프로필 생성 때도 정답 열을 읽지 않는다. 추론 단계에는 그 테이블들이 필요 없다.
