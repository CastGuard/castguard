# 10/6 모델 개선·피드백·조건 분석 사전 계획

설정: configs/oct06_research.json. 실행 전 기록. 사용자의 10/6 모델 개선 재개 지시를 따른다. 모든 기존 적격 품질행은 이전 연구에 노출됐다. 이번 연구는 탐색/재사용 평가이며 신규 독립 성능 검증이 아니다.

## 가설과 후보

H1: 순서 카운터를 제거하고 규제한 모델을 비교하면 공정 완료 관측 입력으로 더 나은 품질 순위를 얻을 수 있다. P=공정14, H=P+#41 과거이력4, S=P+센서6+제품, SH=S+이력4. shot_position은 제외한다. 센서·제품의 현장 수신시각은 미검증이다.

H2: 과거 검사결과가 정해진 지연으로 회신된다면 현재 공정 입력에 없는 품질 드리프트를 설명할 수 있다. FB=피드백 단독, S_FB=S+FB, SH_FB=SH+FB. 비교는 S_FB-S, SH_FB-S_FB, H-P, SH-S를 분리한다. 피드백은 #42의 과거 정답이며 #41 다종융합 이득으로 부르지 않는다.

후보5개: logistic, 규제RF, 규제LightGBM, Ordered/has_time CatBoost, 작은 HistGradientBoosting. 설정에 고정된 후보만 실행한다. 새 라이브러리나 foundation model 탐색보다 현재 데이터 크기·시간순 계약을 우선한다. HistGradientBoosting의 무작위 내부 조기중단은 끈다. 공식 문서: https://scikit-learn.org/1.7/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html ; https://catboost.ai/docs/en/references/training-parameters/common . add 참조 commit 90402e0.

## 분할·선정

기존 within_run primary와 forward_run 2/3/4/6의 train/validation/test 그대로. 7입력×5모델×3seed×5fold=최대525 fit. 학습 전처리는 train만 fit한다. 각 fold/입력별 validation AP의3seed 평균 최대로 모델을 선택하고 동률은 모델명순. 다른 미래 fold의 성과를 앞선 fold 선정에 쓰지 않는다. 각 seed 임계값은 해당 validation 점수의80% 분위(nextafter)로 동결한다. 선택 결과 JSON·후보 validation 표를 봉인한 뒤 test 지표를 생성한다. 전체 후보 test 성능으로 재선정하지 않는다.

표본 부족/단일클래스 지표는 결측과 분모를 기록한다. 최종 도구용 연구 모델은 within_run validation에서만 입력·모델을 선택하되, 연구 판독용이며 미래 실운영 채택과 구분한다. 원래 A0/queue 모델은 교체하지 않는다.

개선 판정은 validation paired AP≥+.02 및20% 검사 포착≥+5%p, 최소2개의 적격 forward validation fold에서 각각 음이 아닌 차이. AP 기준은 불량률 및 원래 목표와도 비교한다. 입력 추가에 따른 효과는 같은 모델·seed의 쌍 비교도 병기한다. test 실패는 그대로 보고하며 threshold·후보 재조정은 하지 않는다.

## 피드백의 엄격한 경계

품질행을 #41 source_row_m41와1:1 연결하고, 같은 run의 공정관측 순번으로 결과 도착을 모사한다. 현재 event t에는 event≤t-20의 관측 정답만 사용한다. 미래·현재 정답, 다른 run 정답은 금지. 품질미관측 event는 정상으로 채우지 않는다. 공정이 누락된 품질행은 제외 역할을 유지한다. 20/100 event 창의 과거 평균·EWMA·누적 관측 수를 사용한다. 실제 초/분 지연으로 변환하지 않는다.

기본 prequential 평가는 앞선 evaluation Shot의 정답도20event 후 제공된다고 가정한다. 독립적인 라벨 없는 batch 예측과 다르다. validation/test 각각 자신의 구간 정답 회신을 끈 prior-partition-only 감도도 함께 보고한다. delay5/50/100, coverage50/20%는 동결 모델에 대한 스트레스 검사이며 성능에 맞춰 기본값을 바꾸지 않는다. 회신 누락 mask는 row_id 고정해시로 재현한다.

## 지표·불확실성·조건

AP/AUC/Brier, 불량률, validation 임계값 FPR/TP/FP/FN/TN, 각10/20/30% top-k 포착을 같은 행 분모로 계산한다. top-k는 사후 batch 순위 지표이며 기존 causal queue와 직접 비교하지 않는다. 비용은 검사단가 비율[1,2,5,10,20]에 대한 조건부 손실 시나리오로만 해석한다.

run별·제품별·불량유형별 표본/오류, 훈련 제품 지지, 고정 변수쌍 High_Velocity×Casting_Pressure의 train 분위3×3 cell을 기록한다. train30·평가20 이상 cell에서만 모델 반응/오류 표시. 두 변수 교호차는 해당 cell 안의25/75분위 교차4점, 다른 입력은 cell 내 실제행에서 고정해 계산한다. 선형 모델의 log-odds 교호가0인 사실과 비선형 점수 변환을 구분한다. 물리적 인과·설정 최적화로 확대하지 않는다. 결과가0/미지원이어도 변수쌍을 바꾸지 않는다.

paired bootstrap은 run block 재표본1000회. 적은 run 수 때문에 탐색적 불확실성만 제시하며 seed SD는 CI가 아니다. 원래 Gate 기준·정책 결과는 별도 모집단으로 유지한다.

## 자동 판독

입력 계약/누락/미학습 제품/관측범위·공동지지 이탈은 자동 검출한다. validation 동결 임계값에 따른 위험 표시와 추가검사 검토 요청을 자동 생성한다. 지지 부족은 보류하고 정상 보증/자동 생산중지/폐기/조건 변경은 하지 않는다. 사람 승인 없이 제조 설비에 조치를 보내지 않는다. 측정된 성능과 미검증 운영 조건을 결과에 함께 낸다.
