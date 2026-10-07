# 품질 파일 없이 공정 관측값만으로 판독

2026-10-05. 기존 A0 동결 모델을 쓰는 **명시적인 별도 입력 경로**다. 완료된 동일 Shot의 공정값 14개가 있으면 품질 정답 파일·품질 행 카운터·생산 카운터·과거 이력 없이 점수와 개별 설명을 계산한다. 신규 관측 형식의 입력을 처리하는 기능이며 실제 신규 현장 데이터를 수집하거나 미래 성능을 검증한 것은 아니다.

## 바로 실행

프로젝트 `C:\Users\JH\Desktop\workspace\contest`에서 실행한다. 다음 출력 이름은 새 파일이어야 한다. 이미 있으면 덮어쓰지 않고 종료한다.

```powershell
& .\.venv\Scripts\python.exe -I -B -X utf8 observable_quality.py `
  --input examples/observable_quality/shots.json `
  --output reports/observable_quality/my_review.json `
  --html reports/observable_quality/my_review.html
```

[실제 예제 화면](../reports/observable_quality/example_output.html), [JSON 출력](../reports/observable_quality/example_output.json), [입력](../examples/observable_quality/shots.json), [입력 출처](../examples/observable_quality/provenance.json), [기대 요약](../examples/observable_quality/expected_summary.json).

원래 `decision_review.py`와 [과거 재생 예제](../reports/decision_review/example_output.html)는 그대로다. 새 경로는 기존 queue 품질 모델을 교체하거나, 입력이 부족할 때 자동으로 A0로 전환하지 않는다. CLI와 schema가 다르며 잘못된 schema는 거절한다. 새 경로는 품질 A0만 출력하고 설비 상태나 검사 정책을 몰래 결합하지 않는다.

## 원인과 수정 범위

기존 `q42_A`/`q42_B`/`B2`의 `shot_position`은 [재구성 코드](../castguard/rebuild.py)의 품질 파일 처리에서 만들어진다. 순서는 `DieCasting_Quality_Raw_Data.csv` 읽기 → Shot 감소로 run 분리 → 원래 열들로 중복 제거 → run별 cumcount다. 중복 제거 키에는 품질 정답 열도 들어간다. 카운터가 정답 수치를 직접 인코딩한 것은 아니지만 **품질 기록의 존재·원래 순서·중복 처리에 의존**한다. 품질 행을 빼거나 새로 받으면 뒤의 순서가 달라질 수 있다.

기존 queue는 qpart에서 품질 점수를 만든 후 전체 공정 이력에 결합한다. 따라서 점수가 있는 범위도 과거 품질 파일 행의 존재와 연결돼 있었다. 라벨 없는 패킷에 이 과거 카운터를 미리 넣어 재생하는 것만으로 신규 공정 입력 능력을 입증할 수 없었다. 카운터를 생산 순번으로 바꾸거나 0/중앙값으로 채우지 않았다.

| 입력군 | 원래 출처·의존성 | 신규 관측 경로의 결정 |
|---|---|---|
| 공정14 | 공정 원본 CSV에 독립적으로 존재. 같은 Shot의 품질 파일 값과 기존 검증에서 일치. 정답/행 순서로 파생하지 않음 | 그대로 사용. 동일 완료 Shot의 14개 값이어야 함 |
| shot_position | 품질 파일의 보존 행 순서 | 받지 않음. 전달하면 오류 |
| 센서6·Product_Type | 품질 원본에 기록. 정답 값의 변환은 아니지만 공정 원본에는 없음. 독립 수신원/시각 미확인 | 모델 특징에서 제외. 제품 ID만 선택적 외부 맥락으로 받아 경고에 사용 |
| B의 이전 Cycle_Time·5개 최대·20개 결측·물리 Shot 공백 | 이전 공정 기록과 순서에서 계산. 정답 자체는 사용하지 않지만 완전한 과거 기록 필요 | A0에는 없음. 과거 이력을 요구하지 않음 |
| B2 상대 이력 | B 특징과 train에서 배운 제품별 Cycle_Time 중앙값 등. shot_position 의존을 그대로 상속 | 사용하지 않음 |
| 품질 정답·Machine_Status·행 ID/원천 위치 | 목표/감사용이며 새 모델 입력 아님 | 거절. record_id는 출력 연결에만 사용 |

공정14는 Velocity_1, Velocity_2, Velocity_3, High_Velocity, Cylinder_Pressure, Rapid_Rise_Time, Biscuit_Thickness, Clamping_Force, Cycle_Time, Pressure_Rise_Time, Casting_Pressure, Spray_Time, Spray_1_Time, Spray_2_Time이다.

보존된 10/2 공식 실행 cache에는 공정14만 쓰는 A0 artifact가 220개 있다. 추가 모델 학습이나 스윕 없이 기존 baseline 하나를 연결했다. [의존성 감사와 목록](../reports/observable_quality/dependency_audit.json).

## 어떤 동결 모델인가

`artifacts/14b7926791a139eb/q42__all__forward_run__2__A0__logistic__17/model.joblib`.

- 선택 이유: 현재 공정14만으로 입력 계약이 성립하는 A0, 출처가 연결된 원래 10/2 cache, 가장 이른 forward fold2, 기존 정확한 선형 설명 adapter를 쓸 수 있는 logistic, 원래 첫 seed17이다. 이번에 노출 test 점수로 후보를 비교·재선정하지 않았다.
- 학습 경계: 원래 forward fold2의 run0 품질 관측 1,099행. validation은 run1, 이미 노출된 test는 run2다. 학습행은 제품1뿐이다. 전체 생산/미관측 품질 행을 대표한다고 가정하지 않는다.
- 전처리: 저장된 train-only median imputer → StandardScaler → LogisticRegression을 그대로 사용한다. runtime은 현재값 누락/null을 보류하므로 부족한 측정값이나 카운터를 조용히 impute하지 않는다.
- 출처: 원래 provenance의 학습 코드·설정·입력 해시, complete.json의 모델·지표·예측 해시를 대조했다. 실제 payload의 feature 목록과 파이프라인도 확인했다. [고정 프로필](../configs/observable_quality.json).
- 출력: 미보정 클래스1 점수. 설명은 실제 표준화 값×계수 및 절편의 log-odds 분해다. 기준값+기여 합과 sigmoid가 실제 emitted score를 재현한다. 기여는 확률 %p, SHAP 기대값, 물리 원인이나 제어 효과가 아니다.

## 지원 입력 계약

```json
{
  "schema_version": "castguard-observable-quality-v1",
  "records": [{
    "record_id": "new-observation-001",
    "observation_basis": "same_completed_shot",
    "measurements": {
      "Velocity_1": 0.144,
      "Velocity_2": 0.17,
      "Velocity_3": 0.188,
      "High_Velocity": 2.134,
      "Cylinder_Pressure": 214.0,
      "Rapid_Rise_Time": 0.008,
      "Biscuit_Thickness": 16.8,
      "Clamping_Force": 258.0,
      "Cycle_Time": 20.7,
      "Pressure_Rise_Time": 0.044,
      "Casting_Pressure": 1037.0,
      "Spray_Time": 7.8,
      "Spray_1_Time": 0.7,
      "Spray_2_Time": 0.8
    }
  }]
}
```

이는 입력 형식 예시이며 새로운 현장 관측을 주장하지 않는다. 정확한 원본 예제와 변형 출처는 위 입력 파일을 따른다. [JSON Schema](../configs/observable_quality_input.schema.json).

- 카운터·run·Shot 번호·이력·품질 파일 키가 없다. 처음 보는 record_id도 외부 자료를 조회하지 않고 계산한다. 모든 값은 같은 완료 Shot에서 확보한 수치라고 입력 제공자가 보장해야 한다.
- timestamp/도착순서/배치 순번은 모델 입력이 아니며 받을 필요가 없다. batch를 뒤집거나 나눠도 같은 입력값의 점수·설명이 같다. 특징의 순서는 이름으로 고정하며 JSON 키 순서는 영향을 주지 않는다.
- 현재 필수값 누락/null은 해당 행 `not_scored`다. 숫자 문자열·bool·NaN/Infinity·허용되지 않은 열은 `invalid_input`이다. 잘못된 schema/중복 ID/전체 입력 오류는 종료코드2, 유효한 배치 안 개별 오류는 행 상태에 기록하고 종료코드0이다.
- 선택적 `context: {"product_type": 1}`은 외부에서 확인한 제품 ID가 있을 때만 넣는다. 점수 입력이 아니며 값 변경으로 score가 변하지 않는다. 제품2는 미학습 경고, 누락은 제품 적용범위 미확인 경고다. 공정 파일에 없는 제품을 품질 파일이나 순서로 추정하지 않는다.
- train 변수별 최소/최대 밖 값을 경고한다. 범위 안이라는 사실은 공동지지·안전·현장 성능을 입증하지 않는다. 모든 점수는 진단용이며 운영 조치는 보류다. 임계값·검사 정책을 새로 선정하지 않는다.

## 성능을 좋게 보이게 바꾸지 않는다

다음은 **이미 저장된 같은 forward fold2 / logistic / seed17** 비교다. 이번 입력 경로 수정으로 새로 얻은 성능이 아니다. A/B는 더 많은 특징을 쓰지만 그 중 품질 행 카운터의 신규 가용성이 성립하지 않는다. 기존 queue 모델과는 학습/평가 경계가 달라 이 표를 queue 우위 비교로 바꾸지 않는다.

| 기존 validation (1,157행·양성158, 불량률 .1366) | ROC-AUC | AP | Brier |
|---|---:|---:|---:|
| A0 공정14 | .4878 | .1333 | .2000 |
| A 공정+센서+제품+품질 순서 | .5921 | .1976 | .1204 |
| B A+공정 이력 | .5919 | .1977 | .1208 |

A0의 validation AP는 불량률보다 낮다. **관측 입력으로 실행 가능한 것과 유용한 예측 모델인 것은 다르다.** 같은 노출 test는 397행 중 양성이 5개뿐이며, A0 ROC-AUC .6130/AP .01859/Brier .7830, A .3480/.01148/.03753, B .3755/.01210/.03771이다. A0의 한 test 순위 지표가 높다고 승격하지 않고 심한 확률 오차도 함께 남긴다. 임계값 기반 운영을 채택하지 않는다. 전체 수치와 기존 분모는 감사 JSON에 보존했다.

## 무엇이 해결됐고 무엇이 남았나

**해결:** 실제 동결 모델이 외부에서 받은 공정14만으로 점수를 낸다. 원본/전처리/품질 파일이 없는 실행 폴더에서도 카운터를 완전히 생략한 새 형식의 입력을 처리한다. 라벨 파일 없음/빈 파일/내용 변경에도 결과가 같고, 역사적 schema로 자동 전환하지 않는다. 기존 저장 예측 1,554건의 score 최대차 2.3e−16, 설명 margin 최대오차 1.8e−15를 확인했다. 이는 계산/입력 검증이다. [실제 검증](../reports/observable_quality/verification/verification.json).

**남음:** 완료된 동일 Shot의 공정14를 실제 라인에서 언제 수신하는지, 최종검사 전에 모두 확보되는지, 단위/장비/제품 매핑, 품질 미관측 생산군·새 run에서의 성능·확률보정·비용 효과는 미검증이다. 입력 제공자가 서로 다른 Shot의 값을 섞거나 잘못된 단위를 넣은 사실까지 runtime이 독립 인증하지 못한다. 새 경로는 prospective-input-capable이며 prospectively-validated/deployable로 부르지 않는다. A/B/queue의 기존 카운터 경로는 계속 역사적 재생 전용이다.

이번 수정에 신규 학습은 필요하지 않았다. 앞으로 성능을 개선하려면 새로운 평가 경계·입력 수신 시각·전체 생산과 독립 품질 표본을 먼저 고정해야 한다. 이 작업에서는 모델 스윕·재학습·정책 변경·변수쌍 연구를 실행하지 않았다.

## 재현

```powershell
# 새 출력 폴더: 실제 동결 모델의 저장 점수/설명과 데이터 없는 추론 확인
& .\.venv\Scripts\python.exe -I -B -X utf8 verify_observable_quality.py `
  --output reports/observable_quality/my_verification

# 전체 회귀검사
& .\.venv\Scripts\python.exe -I -B -X utf8 run_review_tests.py
```

`prepare_observable_quality.py --output-root <새 폴더>`는 저장 모델·기존 분할·입력 열로 프로필과 예제를 재생성한다. 이 준비 단계와 실제 추론을 구분한다. 추론은 config와 pinned model만 읽고, 재학습하거나 feature selection을 하지 않는다. [통합·보존 기록](../reports/observable_quality/integration.json).
