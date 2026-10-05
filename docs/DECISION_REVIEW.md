# 역사적 A/queue 판독 계약

`decision_review.py`는 기존 동결 모델을 재생하는 경로입니다. 저장소에는 실행 프로필·모델·실제 관측 예제가 포함되지 않습니다. 소스만으로 실제 추론할 수 없으며 자동 다운로드/학습/fallback을 수행하지 않습니다. 모델 없는 회귀검사는 합성 fixture로 실행됩니다.

카운터 없는 새 관측 입력에는 별도의 [A0 공정14 경로](OBSERVABLE_QUALITY.md)를 사용합니다. 두 schema를 자동으로 바꾸지 않습니다.

## 필요한 로컬 자산과 명령

권한이 있는 로컬 연구 묶음에서 configs/decision_review.json 및 해시가 일치하는 reports/oct03_queue/models/ 저장 모델 두 개가 필요합니다. 프로필에는 학습 범위·제품·기존 threshold·artifact 해시가 포함돼 있으므로 공개 소스에서 제외합니다.

```powershell
python -I -B -X utf8 decision_review.py --input your_historical_packets.json --output new_review.json --html new_review.html
```

입력은 [JSON Schema](../configs/decision_review_input.schema.json)를 따릅니다. 출력은 새 파일명이어야 합니다. prepare_decision_review.py는 원래 데이터/모델/선정 영수증이 있는 로컬 묶음에서 프로필을 만들고, verify_decision_review.py와 verify_decision_order.py는 실제 재생을 검증합니다. 준비 단계와 추론 단계는 다릅니다. 추론에는 정답 테이블이 필요하지 않습니다.

## 순서와 이력

- record_id는 배치 안 고유 문자열입니다. 관측 identity는 (run_key, sequence)이며 같은 관측을 여러 ID로 중복 기재하면 전체 호출을 거절합니다.
- sequence는 같은 설비/세션 run의 고정 공정 관측 순서입니다. 도착순서·배치 위치·물리 Shot 번호·timestamp를 대신 쓰지 않습니다.
- quality_record_position은 원래 품질 파일에서 중복 제거한 후의 run 내 행 순서입니다. position_basis=legacy_quality_input_order만 품질 재생에 사용합니다. 생산 카운터나 라벨이 있는 현재 배치의 순번으로 바꾸지 않습니다.
- history는 동일 run의 정확히 직전 min(sequence,5)개 공정 관측입니다. 제품·정답 유무로 거르지 않으며, 현재/미래/역순/다른 run/일부 이력은 거절합니다.
- history 생략/null은 이력을 모름을 뜻해 설비 판독을 보류합니다. sequence=0의 history=[]만 확인된 run 시작입니다. 실제로 존재한 관측의 명시적 null Cycle_Time은 기존 학습 imputer로 처리하고 설명에 표시합니다.
- 현재값과 다른 패킷의 과거값, 겹치는 과거값이 충돌하거나 품질 카운터가 중복·역전·과도하게 증가하면 추론 전에 배치 전체를 거절합니다.

완전한 동일 패킷이면 전체·일부·역순·개별 호출의 점수·설명·경고가 같습니다. 출력 record_index만 달라질 수 있습니다. 호출 간 중복 원장·자동 이력 조립·timestamp 동률 해결은 없습니다. 원천의 run 분리와 관측 진실성은 입력 제공자가 보장해야 합니다.

## 점수·설명·실패 처리

품질 모델은 공정14+센서6+제품+역사적 위치, 설비 모델은 공정14+직전 Cycle_Time+직전5개 최대값을 사용합니다. 저장 전처리와 feature 순서를 검증하며 라벨·oracle·직접 넣은 파생 이력·알 수 없는 열은 거절합니다.

LogisticRegression은 실제 변환값×계수와 절편, LightGBM은 native TreeSHAP의 log-odds 기여를 사용합니다. 기준값+기여 합과 sigmoid가 실제 emitted score를 허용오차 이내로 재구성해야 합니다. 인과·확률 %p·제어 효과가 아닙니다.

현재 필수값 누락은 영향을 받는 모델을 보류합니다. 잘못된 숫자·허용되지 않은 열은 행을 invalid_input으로 유지합니다. 미학습 제품 점수는 진단용 경고를 붙이며 검증된 불량 확률로 표시하지 않습니다. 비활성 경보는 false가 아닌 null/disabled입니다. 자동 설비 조치는 없습니다.

전체 schema/모델/배치 충돌은 종료코드2, 유효한 배치 안 개별 오류는 행 상태에 기록하고 종료코드0입니다. 소비자는 records[].status와 모델별 reasons를 확인해야 합니다.

이 경로는 품질 파일 행 존재/순서에 의존하는 counter를 요구하므로 역사적 재생 전용입니다. 정답 없는 입력을 재생할 수 있다는 사실만으로 신규 생산 입력이나 현장 성능을 입증하지 않습니다.
