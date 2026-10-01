# 전처리 및 데이터 인수인계

기준일: 2026-09-29. 이 문서는 데이터 담당자가 모델 담당자에게 전달하는 처리 명세다.
이 저장소는 원본·전처리 결과·처리 명세를 제공하며, 전처리 실행 코드는 포함하지 않는다.
모델 학습·성능 측정은 아직 수행하지 않았으며, 기존 팀 HTML의 AUC는 이번 작업의 검증 결과가 아니다.

## 1. 사용할 파일

모든 경로는 저장소 루트 기준이다. Parquet는 열 이름·자료형·결측을 보존하는 테이블 파일이다.

| 파일 | 행 × 열 | 용도 | 정답 |
|---|---:|---|---|
| `data/processed/joined.parquet` | 4,617 × 80 | #42 품질 데이터에 #41 과거 공정 이력을 연결한 주 학습 데이터 | `y_defect` |
| `data/processed/m41_timeline.parquet` | 5,161 × 29 | #41 전체 설비 타임라인, Gate 학습 및 예열 평가 | `Machine_Status` |
| `data/processed/d40_clean.parquet` | 73,612 × 40 | #40 별도 공정 데이터, 금형온도 변수 비교 | `y_defect` |
| `data/processed/folds.csv` | 181,170 × 8 | 데이터셋·검증 방식별 학습/검증/시험 역할 | 해당 없음 |
| `data/processed/feature_contract.json` | — | 실험별 입력 열 허용목록 | 해당 없음 |
| `data/processed/manifest.json` | — | 원본·결과의 SHA-256, 크기·행열 수, 처리 설정·환경 | 해당 없음 |

원본 CSV 3종은 `data/raw/`에 보존했고 내용을 변경하지 않았다.
`joined.parquet`에는 중복 제거한 #42 데이터의 71개 열과 #41에서 연결한 9개 열이 포함되어 있다.

## 2. 예측 시점과 분석 단위

예측 시점은 **현재 Shot의 생산 완료 후, 최종검사 전**이다. 현재 Shot의 Cycle_Time 등 완성된 공정값을 사용하므로 생산 전 예측으로 해석하면 안 된다. 현장 적용 시 이 시점까지 센서값을 수신할 수 있는지 확인해야 한다.

- #42: 1행은 1 Shot이며, Cavity 2개 제품의 불량 결과를 함께 담는다.
- #41: 정상·예열·기록 결손을 포함한 설비 타임라인이다.
- #40: 별도 공정의 생산 기록이다. #41/#42와 행 단위로 연결하지 않는다.
- #41/#42의 가동구간 번호는 파일 순서에서 Shot 번호가 감소할 때 1씩 증가한다. 실제 날짜·시각을 복원한 값이 아니다.

## 3. #42 품질 데이터 처리

1. 원본 `DieCasting_Quality_Raw_Data.csv`는 2단 헤더로 읽고 두 번째 헤더를 열 이름으로 사용했다. 열 이름의 앞뒤 공백을 제거했다.
2. 원본 행 순서를 유지하고 Shot 감소 지점을 기준으로 `run_id` 0~6을 부여했다. `source_row`는 헤더를 제외한 원본 데이터 행의 0부터 시작하는 위치다.
3. 같은 run_id에서 id를 제외한 **모든 원본 열 값이 동일한 행**만 중복으로 처리했다. 최초 행을 보존해 7,535행에서 2,918행을 제거했다. 구간이 다른 행은 값이 같아도 합치지 않는다.
4. `(run_id, Shot)`가 고유한지 확인했다. 같은 키에 서로 다른 측정값이 있는 경우는 자동 처리하지 않도록 검증했다.
5. 상수 센서 관리한계 8개를 제외했다. 대상은 Air_Pressure, Coolant_Temp, Factory_Temp, Factory_Humidity의 각각 `_Min`, `_Max`다. 관측 센서 6개는 유지했다.
6. 공장 온도·습도 결측은 원본에서 각각 90행, 중복 제거 후 각각 45행이다. 전체 데이터로 보간하거나 평균 대체하지 않고 결측 상태를 유지했다.
7. 26개 불량 열 중 하나라도 0보다 크면 `y_defect=1`로 정의했다. 각 Cavity에 같은 규칙을 적용한 `y_cavity_1`, `y_cavity_2`도 만들었다.
8. 각 불량유형이 어느 Cavity에든 나타나면 해당 `y_type_<유형>=1`이다. `defect_type_count`는 발생한 서로 다른 불량유형 수다.

불량 13종은 Short_Shot, Bubble, Exfoliation, Blow_Hole, Stain, Dent, Deformation, Contamination, Impurity, Crack, Scratch, Buring_Mark, Inclusions다. 원본 철자를 그대로 유지했다.
주요 4종은 Short_Shot, Bubble, Exfoliation, Blow_Hole이며, 나머지 유형 중 하나라도 발생하면 `y_type_Etc=1`이다. **여러 유형이 동시에 발생한 Shot이 72개이므로 단일 정답 분류로 강제하지 않는다.**

최종 4,617 Shot 중 불량은 1,073개(23.2402%)다. 불량 칸의 값이 2~3인 경우는 원본에서 74개, 중복 제거 후 40개다. 이 값은 단순한 0/1이 아니므로 `>0` 규칙을 사용했다.
`row_id`는 `q42_r<구간>_s<Shot>`이며, `shot_position`은 중복 제거 후 구간 안의 관측 순번(0부터)이다.

## 4. #41 타임라인과 이력 변수

원본 `DieCasting_Raw_Data.csv`의 5,161행을 모두 보존했다. #42와 같은 방식으로 구간을 부여하고 `row_id=m41_r<구간>_s<Shot>`을 만들었다.
Machine_Status는 0=정상, 1=예열이다. 구간 안에서 상태 1이 연속되는 덩어리를 예열 에피소드로 보며, 상태 결측 또는 정상 행은 연속성을 끊는다. `episode_id`는 예열 행에만 부여한다.

| 관측 상태 | 행 수 | 기본 Gate 학습 |
|---|---:|---|
| 정상·공정값 완전 | 4,617 | 가능 |
| 정상·공정값 일부/전체 결측 | 313 | 제외 |
| 예열·공정값 완전 | 104 | 가능 |
| 예열·공정값 결측 | 14 | 제외 |
| 설비상태 결측·공정값 완전 | 30 | 제외 |
| 설비상태 결측·공정값 결측 | 83 | 제외 |

`process_missing`은 공정 14개 중 하나라도 결측인지 나타낸다. `gate_eligible`은 설비상태가 존재하고 공정 14개가 모두 있는 행이다. 기본 학습 가능한 행은 4,721개다. 나머지 440개는 삭제하지 않았다.

예열은 전체 118 Shot·21개 에피소드다. 구간 2의 `r2_e4`(Shot 325~336)는 12행 전체 입력이 없고, `r2_e5`에도 2행 결손이 있다. **모델이 관측 가능한 예열은 104 Shot·20개 에피소드**다. 전체 21개와 관측 가능한 20개의 평가 분모를 구분해야 한다. 입력 결손은 정상으로 간주하지 말고 별도 보류 경로로 다룬다.

이력 계산은 각 구간에서 독립적으로 수행했다. 아래 집계에서 “이전 행”은 결손 행을 삭제하지 않은 #41 타임라인 기준이다.

| 파생 열 | 계산 정의 |
|---|---|
| `prev_cycle_time` | 직전 행의 Cycle_Time |
| `max_cycle_previous_5` | 현재 행을 제외한 직전 최대 5행의 Cycle_Time 최댓값. 최소 1개 유효값이 있어야 계산 |
| `missing_process_previous_20` | 현재 행을 제외한 직전 최대 20행 중 process_missing=True인 행 수. 이력이 없으면 결측 |
| `missing_shots_before_current` | max(현재 Shot−직전 Shot−1, 0). 구간 첫 행은 결측. 현재 Shot 식별자는 사용하지만 현재 측정값·정답은 사용하지 않음 |
| `oracle_shots_since_warm` | 현재 Shot−직전까지 관측된 마지막 예열 Shot. 이전 예열이 없으면 결측 |
| `oracle_prior_episodes` | 현재 행 전까지 시작된 예열 에피소드 수 |

`oracle_*`는 설비상태 **정답**을 이용한 참고용 열이다. 운영 중 정답의 실시간 가용성이 미확인이라 기본 입력 목록에서 제외했다. 향후 Gate 예측을 이력으로 쓸 경우 학습 행에도 교차검증 밖 예측을 사용해야 한다.

## 5. #41–#42 연결

#42를 기준으로 `(run_id, Shot)`에 대해 #41을 1:1 연결했다. 4,617개 모두 매칭됐으며 대응하는 Machine_Status는 모두 0이다. 공정변수 14개 × 4,617 Shot = **64,638개 값이 전부 일치**했다. 조인에 따른 행 증가·손실은 없다.

공정 14개를 중복 입력하지 않고 #41에서 이력 변수·감사용 상태·원본 위치만 추가했다. joined의 `source_row`는 #42 원본 위치, `source_row_m41`은 #41 원본 위치다.
관측된 두 파일의 대응은 확인했지만, 물리적으로 같은 설비라는 주장과 수집 주기는 별도 AAS·원본 가이드북으로 확인해야 한다. #40은 직접 연결하지 않았다.

## 6. #40 공정 데이터 처리

1. `Investment_Casting.csv`의 timestamp(날짜)와 date(시각)를 결합해 `event_time`을 만들었다. 형식은 연-월-일 시:분:초이며 시간대가 없어 UTC 변환은 하지 않았다.
2. event_time, 원본 행 위치 순으로 안정 정렬했다. `source_row`는 정렬 전 0부터 시작하는 위치이고 `row_id=p40_<source_row>`다.
3. 상수 열 line_unit, production, top_temp4, bottom_temp4와 결측이 많은 molten_capacity를 정제 테이블에서 제외했다.
4. mold_temperature, sleeve_temperature와 상·하 금형온도 6개의 원래 값을 `_raw` 열로 보존했다. 이 변수들의 0 이하 값은 결측으로 표시했다. 실제 해당 값은 mold_temperature의 0인 420개다. 이는 미기록 값이라는 전처리 가정이며 단위 검증 결과가 아니다.
5. 같은 변수들의 1,500 초과 값은 `_suspect_high=True`로 표시하고 원래 수치를 유지했다. 단위 확인 전 일괄 삭제하지 않았다. 표시된 칸은 총 16,045개이며 그중 bottom_temp3가 16,036개다. 칸 수와 행 수를 혼동하지 않는다.
6. PassOrFail을 nullable 정수 `y_defect`로 보존했다. 0=합격, 1=불합격이다. 라벨 없는 1행은 `label_available=False`로 남기고 학습·평가에서 제외했다.
7. `normal_pressure`는 injection_pressure>615인지 표시한다. 압력이 결측이면 이 표시도 결측이다. 615는 팀 문서의 분석 기준이며 #42에 전이할 물리 한계가 아니다.

전체 73,612행 중 라벨 있는 행은 73,611개, 불합격은 3,277개다. 관측 시각은 2021-08-04 07:04:11~2021-10-11 21:49:45이며 동일 시각의 추가 기록이 302개 있다.

## 7. 모델 담당자의 입력 선택

**숫자형 열 전체를 입력으로 선택하면 정답 누수가 발생한다.** `feature_contract.json`의 실험별 목록으로 열을 선택한다.

| 목록 키 | 사용 파일 | 입력 구성 |
|---|---|---|
| `q42_A0` | joined.parquet | 공정 14개 |
| `q42_A` | joined.parquet | 공정 14 + 센서 6 + Product_Type + shot_position |
| `q42_B` | joined.parquet | A + 정답을 쓰지 않은 #41 이력 4개 |
| `m41_gate` | m41_timeline.parquet | 공정 14 + prev_cycle_time + max_cycle_previous_5 |
| `p40_full` | d40_clean.parquet | #40 공정 입력 14개 |

공정 14개: Velocity_1, Velocity_2, Velocity_3, High_Velocity, Cylinder_Pressure, Rapid_Rise_Time, Biscuit_Thickness, Clamping_Force, Cycle_Time, Pressure_Rise_Time, Casting_Pressure, Spray_Time, Spray_1_Time, Spray_2_Time.

센서 6개: Melting_Furnace_Temp, Air_Pressure, Coolant_Temp, Coolant_Pressure, Factory_Temp, Factory_Humidity.

#40 입력 14개: mold_temperature, facility_CycleTime, production_CycleTime, mechanical_strength, injection_pressure, sleeve_temperature, top_temp1, top_temp2, top_temp3, bottom_temp1, bottom_temp2, bottom_temp3, biscuit_thickness, cooling_water_temp.

원본 불량 26열, 모든 `y_*`, Machine_Status, PassOrFail, defect_type_count, ID·구간번호·원본 행 위치, episode_id, oracle 열은 기본 품질모델 입력이 아니다. 타깃과 감사용 열은 확인을 위해 테이블에 남아 있다.
결측 대체·스케일링·변수선택·리샘플링은 아직 fit하지 않았다. 각 train에서만 학습하고 validation으로 모델/임계값을 선택한다. 현재 파일에 남은 결측은 의도된 상태다.

## 8. 평가 분할 사용법

folds.csv는 독립 데이터 행 목록이 아니라 **데이터셋×검증 방식×fold별 역할 배정표**다. 총 23개 조합이 있으므로 전체 181,170행을 학습 표본으로 합치면 안 된다.

1. `dataset`, `scheme`, `fold`를 먼저 선택한다.
2. 해당 파일의 row_id와 배정표의 row_id를 연결한다. dataset은 q42=joined, m41=m41_timeline, p40=d40_clean이다.
3. role이 train/validation/test인 행을 해당 용도로 사용하고 excluded는 점수에서 제외한다.
4. Gate→품질 연결 실험은 양쪽에서 같은 scheme/fold를 사용한다. 같은 Shot의 역할 경계를 맞춰 두었다.

| scheme | 적용 데이터 | 구체적 정의 |
|---|---|---|
| `within_run`, fold=`primary` | q42, m41 | q42의 유효 구간별 앞 floor(N×0.7)을 개발용, 그중 앞 floor(개발행×0.8)을 train으로 사용. 남은 개발행은 validation, 뒤 30%는 test. m41은 q42의 마지막 train/validation Shot 경계와 정렬 |
| `run_holdout`, fold=시험 구간 번호 | q42, m41 | 유효 구간 0·1·2·3·4·6을 각각 test로 사용. 나머지 중 가장 뒤 구간을 validation, 그 외 구간을 train으로 사용 |
| `forward_run`, fold=시험 구간 번호 | q42, m41 | 시험 구간 2·3·4·6에 대해 직전 유효 구간을 validation, 그보다 이전 유효 구간을 train으로 사용. 더 뒤 구간은 제외 |
| `chronological`, fold=`primary` | p40 | 고유 event_time 순으로 앞 floor(T×0.7)을 개발용, 개발용 앞 floor(개발시각수×0.8)을 train, 나머지를 validation/test로 나눔. 같은 시각은 같은 역할 |

구간 최소 행 수는 20으로 정했다. 구간 5는 4 Shot뿐이어서 보존하되 모든 평가에서 제외한다. Gate 입력 결손 및 라벨 결측도 제외한다. #40 라벨 결측 1행은 분할 경계 계산의 시각 목록에는 포함되지만 role은 excluded다.

| 데이터·기본 분할 | train | validation | test | excluded |
|---|---:|---:|---:|---:|
| q42 / within_run | 2,579 | 647 | 1,387 | 4 |
| m41 / within_run | 2,618 | 654 | 1,445 | 444 |
| p40 / chronological | 41,251 | 10,300 | 22,060 | 1 |

within_run은 구간 안의 순서를 지키지만 다른 구간의 미래 데이터가 학습에 포함될 수 있는 **회고적 평가**다. run_holdout도 전역적인 시간 전진 평가가 아니다. 새 미래 가동구간에 대한 주장은 forward_run으로 평가한다.
order는 q42/m41에서 각 원본 파일의 행 위치, p40에서 시각 문자열이다. 서로 다른 파일의 원본 위치 숫자를 직접 비교하지 않는다. fold/order/episode_id는 CSV를 읽을 때 문자열로 지정하면 혼합형 자동 추론을 피할 수 있다.
예열 에피소드는 동일 fold 안에서 역할을 넘나들지 않도록 검증했다. 양성이 없는 평가 조각에서는 AUC를 산출하지 말고 표본·양성 수를 함께 기록한다.

## 9. 가동구간별 참고 집계

| 구간 | 품질 Shot | 불량 Shot | 불량률 | 설비 기록 | 예열 Shot | 에피소드 |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 1,099 | 413 | 37.580% | 1,106 | 6 | 2 |
| 1 | 1,157 | 158 | 13.656% | 1,296 | 26 | 3 |
| 2 | 397 | 5 | 1.259% | 743 | 34 | 7 |
| 3 | 600 | 44 | 7.333% | 623 | 23 | 3 |
| 4 | 725 | 298 | 41.103% | 733 | 8 | 2 |
| 5 | 4 | 2 | 50.000% | 4 | 0 | 0 |
| 6 | 635 | 153 | 24.094% | 656 | 21 | 4 |

구간 2는 불량이 5개뿐이고 구간 5는 전체 4개뿐이다. 비율만 보고 안정적인 성능 또는 구간 간 차이의 원인을 단정하지 않는다.

## 10. 검증·한계·재현 기록

데이터 생성 시 데이터·누수·재현성 테스트 22개가 통과했다. 조인 누락/불일치, 중복 키, 정답 입력, 현재·미래 측정값에 의존하는 이력, 구간 간 이력 혼합, 분할 겹침, 동시각 분할, Gate/품질 경계 불일치를 점검했다. 같은 환경에서 반복 실행한 결과 파일의 해시도 일치했다.

품질 점검은 완전성·유일성·유효성·일관성·정확성·적시성을 구분했다. 유일성은 #42가 61.2741%→100%, #41/#40은 후보 키 기준 100%다. 정답 도메인은 알려진 값에서 모두 유효했지만 센서의 물리적 정확성을 의미하지 않는다. 정확성은 외부 정답이 없고 적시성은 수집/적재 SLA가 없어 미측정이다. 연결 공정값 일치율은 매칭된 부분집합에서 100%다.

Python 3.12.14, pandas 3.0.1, numpy 2.3.5, pyarrow 23.0.0 환경에서 생성했다. 파일 읽기에는 pandas와 Parquet 엔진인 pyarrow 등을 사용할 수 있다. 처리 설정과 원본/결과 해시는 manifest.json에 기록했다. 이 문서는 처리 방법을 설명하며, 동일 파일을 재생성하려면 해당 방법을 구현한 실행 코드와 환경이 별도로 필요하다.

확인이 필요한 사항은 원본 가이드북의 단위·수집주기, AAS 설비 계보, 예측 시점의 실제 입력 가용성이다. 현재 docs/가이드북.html은 팀 계획 문서이고 KAMP 원본 가이드북 PDF가 아니다.
대회 공고문의 최종 소스코드 제출·재현성 평가에 맞춰, 제출 시에는 전처리부터 모델 평가까지 실행할 수 있는 코드와 환경 명세를 함께 준비해야 한다.
