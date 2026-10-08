# 10/8 네 가지 데이터 조합 비교 계획

등록 시점: 실행 전. 사용자는 JH 기반으로 add 팀 작업의 유용한 부분을 통합하고 네 조합 실험을 수행하도록 명시적으로 요청했다. 기존 모델·원본·분할·결과는 보존한다. 결과는 이미 노출된 데이터의 탐색 재사용 평가이며 독립 검증이 아니다.

## 가설과 고정 비교

- 가설: #40에서 학습한 공통 개념의 위험 순위가 #42의 품질 예측에 추가 정보를 제공할 수 있다. #41 과거 이력과 함께 넣었을 때의 추가가치도 평가한다.
- 주 비교: S(#42), SH(#42+#41), S_T(#42+#40), SH_T(#42+#41+#40). 별도 민감도 비교: 각 입력에 기존 20 공정 event 지연의 #42 검사 피드백을 추가한 네 조합. 피드백을 다종 융합효과로 세지 않는다.
- 고정 모델: 10/6 규제 RandomForest(주 표), LogisticRegression(견고성 확인). 두 모델 모두 동일한 기존 설정, seed 17/29/43. 결과가 좋은 모델만 골라 보고하지 않는다. 기존 S_FB 판독 모델은 교체하지 않는다.
- 기존 within_run primary 및 forward_run 2/3/4/6을 그대로 사용한다. 대상 240 fit + #40 source RF 3 fit. 모델 탐색·파라미터 튜닝 없음.

## 전이 입력 계약

#40과 #42는 행 단위 조인하지 않는다. HTML 피드백의 공통 개념 분위 정렬 아이디어를 JH 파이프라인에 재구현한다. 고정 5개 대응은 injection_pressure→Casting_Pressure, facility_CycleTime→Cycle_Time, mechanical_strength→Clamping_Force, biscuit_thickness→Biscuit_Thickness, cooling_water_temp→Coolant_Temp이다. 특히 mechanical_strength와 Clamping_Force의 의미·단위 동등성은 미확인 가정이다. 이름 유사성 및 분위 정렬만으로 물리적 동등성·인과 전이를 주장하지 않는다. 결과에 따라 매핑을 교체하지 않는다.

각 데이터의 train에서만 중앙값과 경험누적분포를 학습한다. ECDF는 (작은 값 수 + 0.5×동률 수)/train 수로 계산하며 범위 밖은 0/1이다. #40은 기존 chronological/primary의 normal_pressure이며 라벨이 있는 train만 source 학습에 쓴다. 별도 source validation/test에 대한 성능은 진단으로만 보고하며 source 설정을 선택하는 데 쓰지 않는다.

source 모델은 10/6 RF 설정으로 seed별 1개를 학습한다. #42의 각 fold train 분포로 변환한 5개 입력에 이 모델을 적용하여 확률 점수 1개(T)를 추가한다. 이 수치는 #42에 보정된 불량 확률이 아니라 전이 후보 feature다. #42의 validation/test 정답·분포는 변환 및 source 학습에 쓰지 않는다. 두 공정의 실제 시간 동시성은 확인할 수 없으며 사전에 source 모델을 확보했다는 전이 시나리오 가정이다.

## 평가·성공·중단 조건

- 모든 후보 validation 지표·임계값을 먼저 파일로 봉인한 뒤 같은 후보들의 재사용 test를 산출한다. 임계값은 각 validation 80% 분위 바로 위. AP/AUC, 정상 FPR, TP/FP/FN/TN, 사후 20% 검사 포착과 실제 분모를 모두 보존한다.
- 같은 모델/seed/행에서 S_T−S, SH_T−SH, SH−S, SH_T−S_T를 비교한다. FB 층도 별도 비교한다. seed SD와 within_run 6run 블록 재표본 1,000회 범위를 구분한다.
- 기존 개선 기준 유지: within_run validation AP +0.02 이상 및 포착 +5%p 이상, 적격 forward validation 최소 2개에서 AP/포착 차이가 모두 음이 아님. 만족하지 않으면 미채택. test를 보고 재선정하지 않는다. 불확실성이 0을 포함하면 확정 개선으로 표현하지 않는다.
- 21:30 KST까지 실험을 종료한다. 오류·누수·분모 불일치면 해당 결과는 제외하고 실패 기록을 남긴다. 재튜닝으로 성공 수치를 찾지 않는다. 22:30까지 제출 후보·렌더·ZIP 검수를 마치고 참가팀의 실제 접수 시간을 확보한다. 공식 마감은 보존 공고 기준 23:59 KST다.

## 팀 작업 통합

add 90402e0의 Gate/유형별 결과와 생성 코드를 출처·설정·분모를 포함해 보존한다. 가져온 결과는 같은 팀의 보조 연구로 활용하되 JH의 다른 모집단 지표와 혼합하지 않는다. 적응형 Gate는 지연된 정상 상태 회신을 요구하며 실측 생산중지나 현장 효과가 아니다. #40 온도 제거는 수집 제언의 근거로만 사용한다.

설정: configs/oct08_fusion.json. 실행 및 결과: castguard/oct08_fusion.py, reports/oct08_fusion/. 새 점수가 없는 문서 개선은 모델 성능 개선으로 세지 않는다.
