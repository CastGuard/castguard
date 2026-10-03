# 10월 2일 실험 프로토콜

계획 출처: [과거 가이드북](archive/guidebook_before_2026-10-03.html)의 9/30–10/1 및 10/2 판정 게이트. 아래 규칙과 `configs/oct02.json`을 첫 모델 실행 전에 고정했다. 원본·기존 processed·folds·feature_contract는 수정하지 않는다.

**범위:** 이 문서는 10/2 실험의 역사적 규칙이다. 10/3 이후의 탐색적 후속 실험은 [별도 등록 기준](EXPERIMENTS_NEXT.md), 현재 일정은 [ROADMAP](ROADMAP.md)을 따른다. 기존 test를 이미 본 이후의 계획을 이 문서의 최초 사전 규칙으로 소급하지 않는다.

- **분석 단위**: #42 Shot 불량 여부, #41 설비 예열, #40 별도 공정 불합격. #40과 #42는 결합하지 않는다.
- **예측 시점**: 현재 Shot 생산 완료 후, 최종검사 전. 실시간 적용 가능성은 아직 확인하지 않았다.
- **비교**: 로지스틱 회귀, RF, LightGBM, CatBoost의 고정 설정. seed 17/29/43/71/101. 탐색 없이 모든 후보를 같은 folds로 평가한다.
- **입력**: 기존 허용목록만 사용. 중앙값 대체는 train에서 fit, 로지스틱만 train에서 표준화. Product_Type은 이진 수치로 취급한다. 결측 전체 열은 0으로 보존한다.
- **분할**: q42/m41의 within_run 1개, run_holdout 6개, forward_run 4개 전부 사용. p40은 chronological 1개. 구간 5·라벨 결손·Gate 관측 결손은 기존 분할대로 제외한다.
- **선정**: 각 dataset/population/scheme/fold마다 기준 실험(A/Gate/E_full)의 validation AP를 seed 평균하여 모델군을 선택한다. 동률이면 낮은 Brier, 모델명 순서. 같은 모델군을 제거실험에 적용한다. 각 fold에서 따로 선택하여 미래 구간 validation이 이전 fold 선택에 들어가지 않는다. 모든 후보 결과도 보존한다.
- **지표**: PR-AUC 표기는 `average_precision_score`의 AP를 뜻하며 사다리꼴 PR 면적과 다르다. ROC-AUC, AP, 양성률, Brier, 10개 동일 너비 구간 ECE, Recall/FNR/FPR/Precision, 혼동행렬, 학습/추론 시간. 단일 클래스 평가에서는 ROC-AUC/AP를 결측으로 기록한다.
- **임계값**: 품질은 validation F1 최대(동률이면 높은 임계값). Gate는 validation 정상 Shot의 FPR ≤ 2%인 최소 경계, 동점 확률은 함께 처리. validation에 정상 표본이 없으면 경보를 내지 않는 보수적 경계. test에서 2%를 보장하지 않으며 실측 FPR을 따로 보고한다.
- **A0/A/B**: 공정 14 / A0+센서·제품·순서 / A+#41 과거 이력 4. B의 통과는 within_run test의 동일 seed AP 차이 평균 ≥ .02이며 차이의 seed 표준편차 2배를 초과하는 경우다. seed 변동은 표본 불확실성이나 통계적 유의성을 뜻하지 않는다. 별도 run 단위 paired bootstrap도 기록한다.
- **B 재설계 1회**: validation에서 B 기준이 실패하면, test를 이용한 재설계 없이 직전/직전 5행 최대 Cycle_Time의 train 제품별 중앙값 대비 비율 2개와 과거 20행 결손수/20을 추가하는 B2를 한 번 평가한다. 원본 feature_contract는 변경하지 않고 별도 파생 계약을 코드/결과에 남긴다. B2 선택 여부는 validation의 동일 판정식으로만 정한다.
- **C**: Gate 전후의 예열 통과율, 정상 오정지, 에피소드 탐지 및 최초 탐지까지 실제 Shot 간격을 기록한다. 입력 결손은 보류. 관측 가능한 에피소드 분모와 전체 분모를 함께 보고한다. #42에 실제 품질 라벨이 있는 정상 Shot에서만 Gate 통과 후 품질 포착률을 계산한다. 예열 제품의 품질 정답을 만들어내지 않는다.
- **E**: #40 전체 및 압력 >615 모집단에서 각각 train/validation/test를 제한해 full/금형 6개 제거 비교. mold_temperature와 sleeve_temperature는 제거 6개에 속하지 않는다. 압력 규칙 자체의 혼동행렬을 별도 비교한다. test 날짜 블록 paired bootstrap 95% 구간은 탐색적 근거다.
- **F**: 기준 모델의 test 순열 중요도(AP 감소)와 train 25→75 분위 PDP 확률 차이로 압력·열 변수 방향/순위를 비교한다. 같은 물리량·단위라는 근거가 없으므로 서로 다른 proxy 비교이며 인과·공장 간 모델 전이 증거가 아니다.
- **재현**: 원본·입력 해시, 코드·설정·환경 지문, 행 단위 validation/test 예측, 모델 선택 근거, seed별 결과를 저장한다. 실행시간은 하드웨어 의존적이다. test를 반복 확인하여 설정을 수정하지 않는다.

가이드북의 과거 수치는 이번 측정값으로 취급하지 않는다. 조건별 오류·정량 상호작용·KPI, 제출문서·최종 ZIP 재현과 외부 자료 확인은 이 판정 게이트의 완료 범위에 포함되지 않는다. 이후 기한은 현재 실행 계획을 따른다.

방법 참고: [scikit-learn AP 정의](https://scikit-learn.org/1.7/modules/generated/sklearn.metrics.average_precision_score.html), [누수 방지와 Pipeline](https://scikit-learn.org/1.7/common_pitfalls.html).

## 최초 결과 이후 재검토에서 보완한 사항

이 절은 최초 test 결과 공개 이후 추가했으며, 사전 등록 규칙으로 소급하지 않는다. 모델 설정·입력·분할·원래 B 성공 기준은 바꾸지 않았다.

- 기존 제거실험의 모델군은 계속 A/Gate/E_full validation으로 선택한다. 별도 `quality_recommendations.csv`는 A0/A/B × 4종 모델 중 validation AP 평균 → 낮은 Brier → 입력명·모델명 순으로 권고한다. 모든 모델군에 공통 실행되지 않은 B2는 제외한다. test 점수는 이 선택의 입력이 아니다. 독립적인 새 시험의 성능 개선 증거로 사용하지 않는다.
- 최종 이력 판정은 validation이 선택한 B 또는 B2에 적용하고, 원래 B의 결과도 별도로 보존한다. 판정 코드를 수정했으며, 이번 데이터에서 선택된 B와 결론은 동일하다.
- 캐시의 완료 표시만으로 재사용하지 않고 모든 지표·예측·모델 파일 해시를 확인한다. 요약을 시작하기 전에 학습 당시 소스/환경/설정/입력/결과와 현재 상태를 대조한다.
- 검증은 설정에서 전체 실험×fold×seed×role 목록을 재구성한다. validation으로 모델/이력 선택도 재계산하고, 각 모집단에서 평가 행 전체가 있는지 확인한다. 지표와 예측을 함께 삭제해도 누락을 검출한다.
- 별도 `verify` 명령으로 전달된 결과의 완료 여부·코드 및 파일 해시·전체 행과 지표를 읽기 전용 점검한다. 요약 실패는 `failed`로 기록한다.
