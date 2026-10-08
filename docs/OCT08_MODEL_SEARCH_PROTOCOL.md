# 10/8 모델·튜닝·앙상블 탐색 사전 계획

사용자 요청: JH 기반으로 하드웨어를 활용해 더 좋은 모델을 탐색한다. 이전 탐색 종료 판단을 이번 요청이 갱신한다. 제출 파일·제출용 내용은 수정하지 않는다. 원본·기존 분할·기존 모델/결과를 보존한다.

## 가설과 후보

공정값의 비선형 관계를 학습하는 부스팅/신경망과 서로 다른 모델의 평균이 기존 S_FB logistic보다 검증 AP 및 검사 포착을 개선할 수 있다. 신형/복잡한 모델이라는 이유만으로 우월성을 주장하지 않는다.

- 입력: S, SH, S_FB, SH_FB. #40 전이는 직전 실험의 동등성 불확실성을 유지하며 이번 모델 탐색의 축에서는 제외한다. 피드백 지연은 기존 20 공정 이벤트, 품질 행 카운터/현재 정답/행 ID/shot_position 미사용.
- XGBoost, CatBoost, LightGBM 각 8설정 × 4입력; GPU MLP, 공식 TabM 각 4설정 × 4입력. 난수 20261008로 설정 목록을 학습 전에 configs/oct08_model_search.json에 기록한다. 모델당 seed17로 기존 within_run primary 및 forward_run 2/3/4/6 전체를 평가한다. 총 128후보, 640 fit. CPU 트리 병렬 6작업×3스레드, GPU 신경망 1작업(미니배치 내부 병렬), 메모리 여유를 보존한다.
- Product_Type: CatBoost 범주형, 다른 모델은 train에서만 학습한 one-hot. 결측대치/신경망 분위변환도 fit 대상 train에서만 학습. TabM은 공식 패키지 구현을 사용하고 각 head 손실을 평균하여 학습, 추론은 sigmoid 확률 평균.
- 트리 최대 1,200회; 신경망 최대 160 epoch. 반복 수는 outer train 내부의 run별 마지막 20% holdout AP로 early stopping (트리 60회/NN 20epoch)하여 결정한다. 내부 경계 직전 20 공정 이벤트를 fitting에서 제외한다. 이후 outer train 전체로 정해진 반복 수만큼 재학습한다. outer validation은 모델/설정 선택에만 사용한다.
- 기준은 각 고정 fold의 S_FB/logistic(C=.3) seed17. 기존 최종 within 모델과 재학습 일치 확인. 원래 모델별 forward 결과와 이 고정 baseline은 구분한다.

## 선택과 평가

각 후보가 5fold 모두 성공한 경우에만 순위 참여. 선택 목적함수: 0.5×within validation AP차 + 0.5×4개 forward validation 평균 AP차(동일 fold 기준모델 대비). 동률은 within AP 후 ID 순. 이를 기준으로 각 모델군 상위 1개 설정을 고정하고 seed29/43을 추가한다. 후보별 3seed 확률 평균을 계산한다.

앙상블: 5개 모델군의 고정 최종 후보와 baseline 중 개별/모든 두 모델 조합의 가중치 .25/.5/.75, 전체 5개 새 모델 동일 가중치, 5개+baseline 동일 가중치. 별도 stacking/meta learner 없음. 위와 동일한 검증 목적함수로 한 후보를 선택한다. 테스트 점수를 보고 가중치나 후보를 바꾸지 않는다.

실질 개선 사전 기준은 기존 기준을 유지한다: within validation AP +.02 이상, 20% 검사 포착 +.05 이상, forward validation 최소2fold에서 AP와 포착 모두 비감소. 만족하는 후보 중 목적함수 최고를 개선 후보로 정한다. 만족 후보가 없으면 최고 탐색 후보를 별도로 표시하고 기존 모델 채택 상태는 유지한다. 각 후보의 AP/AUC/Brier/고정80%분위 경보의 TP/FP/FN/TN/FPR 및 순위20% 포착을 보존한다. 기준모델의 임계값도 validation에서만 정한다.

개발/validation 결과, finalist/앙상블 구성 및 임계값을 파일로 봉인한 뒤에만 선택된 모델군·최종 조합과 기준의 test를 평가한다. 테스트는 이미 노출된 재사용 자료다. 미래 fold도 겹치는 개발 자료이므로 독립 검증이라고 표현하지 않는다. 테스트 성능 악화도 그대로 공개한다. 6run paired block bootstrap 1,000회로 within 차이의 불확실성을 보고하며 3seed 변동과 구분한다.

## 중단·자원·재현

탐색 시작 제한 22:20 KST, finalist 작업 시작 제한 22:50, 전체 계산 제한 23:10. 후보별 기존 완료 기록을 재사용할 수 있으나 미완료 fold/후보는 성공으로 세지 않는다. 메모리 부족/의존성 오류는 실패로 기록하며 자원 설정만 수정할 수 있다. 신경망 패키지 설치는 별도 reports/oct08_search_env 환경에 하고 기존 .venv를 바꾸지 않는다. GPU는 MLP/TabM에 전용, 작은 트리 데이터는 CPU로 병렬 처리한다. 실패한 가족은 최종 조합에서 제외하고 이유 기록. 결과 경로 reports/oct08_model_search/.

기존 test/제출물/기존 판독기 자동 교체 없음. 검증된 새 모델과 재사용 가능한 예측 진입점을 별도로 보관한다. 종료 후 일지와 연구 계획만 갱신하며 제출 파일과 제출 문구는 사용자 요청 시 작성한다.

참고: [공식 TabM](https://github.com/yandex-research/tabm), [논문](https://arxiv.org/abs/2410.24210), [CatBoost 튜닝](https://catboost.ai/docs/en/concepts/parameter-tuning), [XGBoost 문서](https://xgboost.readthedocs.io/en/stable/).
