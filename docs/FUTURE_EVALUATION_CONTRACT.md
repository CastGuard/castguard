# 미래 평가 계약 · schema 1 / validator revision 3

이 계약은 회차7에서 확인한 문제를 새 자료 수집 전에 고정하기 위한 것이다. 모델·임계값 선택, 생산시스템 연결, 성능 계산을 하지 않는다. 기존4613개 적격 품질행을 새 holdout으로 바꾸지 않는다. 기존 원본·전처리·학습코드는 유지한다.

현재 기본 구현은 `future_evaluation_core.py`이다. 버전 없는 `future_evaluation.py`와 기존 `future_evaluation_v2.py` 명령 모두 revision 3을 실행한다. 이전 소스는 `legacy/`에 정확히 보존했다. [회차10 변경·검증 범위](FUTURE_VALIDATION_REVIEW_ROUND10.md)를 함께 읽는다.

## 실행

```powershell
python -B future_evaluation.py init --output incoming/new_collection
python -B future_evaluation.py validate --directory incoming/new_collection --output reports/future_validation/new_receipt.json
```

`init`는 계약 JSON과 빈 CSV8개만 만든다. 기본 계약은 `unconfigured`, 운영수치/시각/서명확인은 미입력이며 검증에 통과하지 않는다. 기존 경로를 덮어쓰지 않는다. `validate`도 출력 영수증이 있으면 중단한다. 입력은 읽기 전용이다. 필요한 열·형식은 [팀원 요청서](DATA_REQUEST_ROUND8.md)에 설명했다.

반환코드0은 구조 검사 통과,2는 미완료/위반이다. `validator_revision`은3이며 `external_provenance_verified`는 항상 false다. JSON 중복 키·NaN·잘못된 object 구조를 거부한다. 시각은 명확한 ISO 날짜와 알려진 offset(`Z`, `+09:00` 등)만 받으며 locale 날짜·시간대 없는 값·`-00:00`은 거부한다. 숫자 계약에 bool을 넣을 수 없다. 합성자료의 상태는 항상 `synthetic_functional_checks_only`, 실제자료의 표 검사(`validate_tables`)만 통과하면 `tables_checked_bundle_evidence_required`다. 파일 묶음 검사(`validate_bundle`)가 출처·정책·추출계획 파일까지 일치시키면 `ready_for_human_provenance_review`다. `source_files_verified`는 로컬 선언 파일의 일치 여부이지 외부 진위 검증이 아니다. **어떤 경우에도 `performance_evidence_created`와 `field_readiness_certified`는 false다.** 파일만으로 실제 시계·원천 진실성·실제 모델 입력·자료 미노출을 인증할 수 없다. 실제자료는 별도의 원천·시계·정책 독립성 검토가 필요하다.

## 지원하는 좁은 운영 규칙

- 한 파일 묶음은 한 개의 공통 대기열과 공유 검사 자원 집합이다. 여러 자원은 resource_id로 구분하며 같은 자원의 검사 슬롯은 겹칠 수 없다. 검사시간은 계약에 고정한 일정 길이이다.
- 모든 정책에 같은 전체 생산행, 같은 예측 결정시각, 같은 입력 수신목록, 같은 검사 슬롯과 종료시각을 제공한다. 미검사/미관측 품질행을 빼는 것은 오류다. 정책별로 다른 가용mask나 예산 파일을 줄 수 없다.
- `required_features`는 수집 전 합의한 입력 목록이다. 기본2개 열은 설명용 임시 목록으로 실제 모델 계약이 아니다. required feature의 값 또는 수신시각이 결정시점에 없으면 모든 정책에서 hold(class0, score빈칸)이며 hold는 FIFO가 우선이다. 품질결과·관측 여부·oracle·검사정보는 입력 허용목록에 넣을 수 없다. 다른 이름으로 숨긴 대리정보까지 자동 탐지한다는 보장은 없다.
- 완전한 입력이면 FIFO는 class2/score0, 점수정책은 class1 또는2와 유한 점수를 기록한다. FIFO는 도착순, 점수정책은 class→점수 내림차순→도착순→event_id 순서다. class1은 사전 고정된 별도 우선순위가 있을 때만 사용하고 그 의미를 정책 원문과 해시로 동결한다. 검증기가 새 경보 임계값을 고르지 않는다.
- 대기열 크기는 검사 중인 건을 제외한 기다리는 건 수이다. 가득 차면 새 행을 거절(drop_new)한다. 같은 시각에는 예측 도착을 event_id 순서로 반영한 뒤 resource_id/slot_id 순서로 검사를 시작한다. 경계 규칙 자체도 계약의 일부이며 실제 운영과 다르면 계약을 수정·재검토해야 한다.
- 만료는 생산완료시각+max_wait_seconds이며, 대기 중인 행은 `expiry <= 현재시각`이면 같은 시각의 새 도착보다 먼저 제거한다. **이미 시작한 서비스의 완료가 정확히 만료시각과 같은 것은 허용한다.** **검사 완료시각**이 만료 및 평가 종료시각 이내여야 한다. 검사 시작만 빠른 것은 허용되지 않는다. 완료 가능한 대기행이 있으면 임의로 슬롯을 비울 수 없다. 평가 종료 후 검사 슬롯을 더하지 않는다. run 경계에서 자동 배출하지 않고 같은 큐가 이어진다.
- 제공된 모든 정책의 slot/event 배정을 독립적으로 재생해 확인한다. 대기열 입장·overflow·만료·검사완료·미처리를 영수증에 남긴다. 마지막 슬롯 뒤의 도착에도 입장·overflow·만료를 적용한다. 평가 종료시각까지 만료된 잔량은 expired로, 그 뒤까지 유효한 잔량은 unserved_at_window_end로 기록한다. 결정시각이 평가 종료 이상인 행은 unavailable_by_window_end다. 라벨 값은 재생에서 사용하지 않는다. 포착률이나 비용을 계산하지 않는다.

가변 검사시간, 우선순위별 서비스시간, 실제 중단/재개, run 경계 강제배출, 다중 연결 queue, 독립 감사와 정책 검사 간 자원공유는 지원하지 않는다. 이 조건이 필요하면 검증 결과를 억지로 통과시키지 말고 현장 규칙을 먼저 명시해 별도 검토한다.

## 정답과 관측 선택

독립 감사는 전수 또는 고정확률 hash-Bernoulli 표본이다. SHA256(seed:event_id) 값을0~1로 바꿔 p보다 작으면 선택한다. seed·p·설계·정책 정의는 미래 평가 시작 전에 잠근다. event_id도 결과를 보기 전에 고정돼야 한다. 모든 생산행에 감사 선택기록을 남기고 검증기가 표본을 재계산한다. 확률을 결과에 맞춰 바꾸거나 정책이 선택한 라벨을 독립 감사라벨로 섞으면 차단한다.

감사 선택은 생산기록 도착 후·정책 점수 확정 전이다. 점수는 독립 검사 시작보다 **엄격히 앞선 시각**에 고정되고(동시각은 차단), 검사 시작≤완료≤라벨 수신≤후속 관측 마감 순서를 지켜야 한다. 선택된 감사표본의 라벨이 모두 도착하기 전에는 평가 완료로 처리하지 않는다. 감사는 이 계약에서 정책 검사와 별도 자원을 쓴다. 같은 자원을 쓰면 그 예산을 따로 설계해야 하므로 현재 검증기는 차단한다.

학습 라벨 사용기록의 `(policy,label_event_id)`는 중복 없는 비어 있지 않은 문자열이어야 한다. 한 정책에서 같은 라벨을 반복 사용했다면 동결 전 사용 이력을 검토하고 계약상 대표 사용시각을 명시해 한 행으로 기록한다. 학습 라벨 사용기록은 라벨 수신≤사용≤정책 동결이어야 한다. 평가 event_id/원본event_id의 라벨을 학습에 사용하면 차단한다. 고정 평가 중 온라인 정답 갱신은 지원하지 않는다. 실제데이터의 원본 파일 해시 및 event_id/원본 event_id가 기존 프로젝트와 일치하면 새 holdout으로 거부한다. 파일/ID를 바꾸는 것만으로 미노출이 증명되지는 않으므로 최종 노출 이력 확인은 사람의 책임으로 남긴다.

## 실제자료의 독립 추출계획 파일

`sampling.definition_path`(묶음 내부 상대경로), `sampling.definition_sha256`(SHA256), `sampling.event_id_rule`(결과 관측 전 ID 고정 규칙)을 채운다. 계획 JSON은 `design`, `probability`, `seed`, `frozen_at`, `audit_resource_mode`, `event_id_rule`의 **정확히 여섯 키**를 갖고 contract의 sampling 값·JSON 자료형과 일치해야 한다. 예를 들어 확률1을 한쪽은 정수1, 다른 쪽은 실수1.0으로 쓰면 일치 검사에서 거부하므로 같은 원본 값으로 작성한다. 계약과 함께 사전 동결하고 원문을 별도 보존한다. 임의 예시 계획을 실제 증빙으로 사용하지 않는다.

검증기는 로컬 파일 해시·설계 일치와 고정 추출 재계산을 확인한다. 실제 작성·동결 시점, ID 불변성, 감사 담당자의 독립성, 별도 자원의 실제 존재는 원천 기록과 사람 검토가 필요하다. `source_files`와 정책 정의 및 모든 contract/CSV 경로는 읽기 전에 묶음 내부인지 검사한다. 경로 탈출이나 원천 파일 해시 불일치는 차단한다.

## 기능 테스트와 과학적 근거의 분리

기능 fixture는 `tests/test_future_evaluation*.py`에 있다. SYNTHETIC 또는 TEST/FIXTURE 표시를 사용하며, real 분기를 시험하는 파일도 가짜라는 설명을 명시했다. real 플래그로 시험했다고 실제자료 근거가 되지 않는다. 미래 입력·정답, 검사 완료, 동일 관측시점, 독립 표본, 입력결손 hold, 제한 queue·만료·자원중복을 시험한다. 라벨 값만 바꿔도 queue 결과가 변하지 않는지 확인한다. 합성 점수·라벨로 성능을 계산하거나 보고서의 실제 비교표에 합치지 않는다.

회차7 실측 비교와 이번 기능검증은 별개이다. 이 인터페이스 통과는 새로운 모델 성과가 아니고, 새 자료가 확보됐다는 뜻도 아니다.
