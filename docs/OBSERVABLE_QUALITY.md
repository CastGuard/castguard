# 공정 관측값만 사용하는 A0 입력 경로

`observable_quality.py`는 완료된 동일 Shot의 공정값14개만으로 계산하는 명시적 경로입니다. 품질 파일·품질/생산 카운터·과거 이력을 요구하지 않습니다. 기존 동결 A0 baseline을 사용하며 역사적 A/queue 경로로 자동 전환하지 않습니다.

이는 신규 관측 형식을 받을 수 있는 기능입니다. 실제 라인 수신 시각·미래 성능·확률보정·운영효과가 검증됐다는 뜻은 아닙니다. 기존 baseline의 성능 한계를 그대로 유지하며 임계값/검사 정책을 새로 선정하지 않습니다.

## 공개 소스와 실제 추론

공개 저장소에는 실행 프로필·저장 모델·실제 관측 예제가 없습니다. 합성 fixture를 사용하는 source-only 시험은 실행할 수 있습니다. 실제 추론은 권한이 있는 로컬 묶음에 configs/observable_quality.json과 profile이 지정하는 해시 고정 A0 model.joblib이 있어야 합니다. 부족하면 명확히 실패하고 모델을 내려받거나 자동 학습하지 않습니다.

```powershell
python -I -B -X utf8 observable_quality.py --input your_process_observations.json --output new_review.json --html new_review.html
```

입력은 [JSON Schema](../configs/observable_quality_input.schema.json)를 따릅니다. 출력 파일은 새 이름이어야 합니다. prepare_observable_quality.py는 원래 artifact/provenance/고정 분할이 있는 로컬 묶음에서 프로필과 예제를 만들며, verify_observable_quality.py는 저장 점수·라벨 없는 실행을 검증합니다. 준비 단계와 실제 추론을 혼동하지 않습니다.

## 입력 계약

schema_version은 castguard-observable-quality-v1입니다. 각 records 항목은 고유 record_id, observation_basis=same_completed_shot, measurements를 갖습니다. measurements에는 다음 값만 허용합니다.

Velocity_1, Velocity_2, Velocity_3, High_Velocity, Cylinder_Pressure, Rapid_Rise_Time, Biscuit_Thickness, Clamping_Force, Cycle_Time, Pressure_Rise_Time, Casting_Pressure, Spray_Time, Spray_1_Time, Spray_2_Time.

현재값 14개가 같은 완료 Shot에서 확보됐다고 입력 제공자가 보장해야 합니다. 카운터·timestamp·배치 순서가 특징에 들어가지 않습니다. 처음 보는 record_id도 원천 행을 조회하지 않고 계산합니다. 동일 측정값을 배치에서 재정렬/분할해도 점수와 설명은 같습니다.

필수 현재값 누락/null은 not_scored입니다. 숫자 문자열·bool·NaN/Infinity·라벨·counter·history·알 수 없는 열은 invalid_input입니다. 부족한 값을 임의 카운터/0/새 중앙값으로 채우지 않습니다. 전체 schema/중복ID 오류는 종료코드2, 유효한 배치 안 개별 오류는 행 상태에 기록하고 종료코드0입니다.

선택적 context.product_type은 외부에서 확인한 제품 ID일 때만 제공합니다. 모델 특징이 아니므로 score는 변하지 않습니다. 제품이 미학습이면 경고하고, 제품 정보가 없으면 적용범위 미확인을 표시합니다. 공정 파일에 없는 제품을 품질 파일이나 순서로 추정하지 않습니다.

## 과거 counter 의존성을 피한 이유

A/B/B2의 shot_position은 품질 파일에서 run별 중복 제거 후 만든 cumcount입니다. 정답 수치 자체를 직접 입력한 것은 아니지만 품질 행의 존재·순서·중복 처리에 의존합니다. 생산 순번으로 대체하거나 임의 impute하면 원래 모델 입력과 달라집니다. queue의 품질 점수 유무도 과거 품질 행의 존재와 연결돼 있었습니다.

기존 A0는 독립된 공정 CSV에도 존재하는 현재값14개만 사용합니다. 원래 provenance가 연결된 cache, 가장 이른 forward fold2, 기존 정확한 선형 설명 adapter를 쓸 수 있는 logistic, 첫 seed17을 선택했습니다. 노출 test에서 점수가 높은 후보를 새로 고르거나 모델을 재학습하지 않았습니다. 센서·제품·품질 위치·과거 이력은 A0의 feature가 아닙니다.

## 전처리·설명과 적용 한계

저장된 train-only median imputer → StandardScaler → LogisticRegression을 그대로 사용합니다. runtime은 현재 결측을 보류하고, 모델·feature·class·hash가 맞지 않으면 실패합니다. 임의 joblib 업로드 인터페이스가 아닙니다.

설명은 실제 표준화 값×계수와 절편의 log-odds 분해입니다. 기준값+기여 합과 sigmoid가 실제 score를 재구성해야 합니다. 기여는 SHAP 기대값·확률 %p·인과 효과가 아닙니다. 모든 점수는 진단용·미보정이며 자동 운영 조치는 보류합니다.

학습 집단은 원래 품질이 관측된 과거 구간입니다. 전체 생산·새 제품·새 run에서의 타당성을 보장하지 않습니다. 실제 수신시각, 동일 Shot 매핑, 단위, 미래 예측력과 비용 효과는 별도 검증이 필요합니다. 변수별 train 범위 경고도 공동지지나 안전을 보증하지 않습니다.

실제 모델/프로필 묶음에는 원래 같은 split의 A0/A/B 지표를 함께 보존해 불리한 결과도 확인하도록 합니다. 입력 계약이 성립하는 baseline이라는 이유를 성능 승격이나 현장 적용 성공으로 바꾸지 않습니다. [역사적 경로](DECISION_REVIEW.md)는 별도로 보존합니다.
