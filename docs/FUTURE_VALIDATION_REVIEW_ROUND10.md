# 회차10 · 미래 평가 검증기의 경계와 현재 실행 경로

2026-10-03. 범위는 CSV 입력·계약·누수 방지·고정 자원 재생의 결함 수정이다. 새 학습, 임계값 탐색, 정책 선정, 미노출 성능평가를 수행하지 않았다. 기존 관측 포착률 점추정(FIFO/과거빈도 22.376%, Q 20.871%, GQ 20.238%)은 그대로다. FIFO와 과거빈도는 같은 검사 행·시점의 유효 기준선 하나이며, Q·GQ 차이의4run 조건부 재표본 범위는0을 포함한다. 품질검사 평균 대기도 FIFO310.308기록, Q142.253기록으로 달라 통계적·현장 우위를 확립한 비교가 아니다.

## 실행 경로

```powershell
.\.venv\Scripts\python.exe -B future_evaluation.py init --output incoming/new_collection
.\.venv\Scripts\python.exe -B future_evaluation.py validate --directory incoming/new_collection --output reports/future_validation/new_receipt.json
```

`future_evaluation.py`와 `future_evaluation_v2.py`는 모두 `future_evaluation_core.py`의 **revision 3 / schema 1**을 호출한다. 버전 없는 명령이나 기존 v2 명령으로 과거 결함에 돌아갈 수 없다. 기존 공개 함수와 CSV8개 열 구성은 유지한다. 기존의 유효한 합성 fixture·문자열 ID·결손 hold·idle 슬롯은 통과한다. 실제자료는 아래 추출계획 파일이 추가로 필요하며, 이전 검증에서 통과했다는 이유로 새 요건을 생략하지 않는다.

원본 v1/v2와 당시 검증 코드·문서의 정확한 바이트는 `legacy/`와 `docs/archive/round10_legacy/`에 보존한다. `historical_sources.py`는 명시한 이전 소스만 원래 SHA256과 일치하는 사본으로 찾는다. 수치 CSV·보고서·PPTX·PDF·ZIP 해시는 대체하거나 갱신하지 않는다. 보존 코드는 과거 재현 참고용이며 운영 기본 경로가 아니다. 원래 폴더 밖에서 직접 실행하면 상대경로 기준도 달라지므로 과거 전체 재현은 당시 보존 ZIP을 사용한다.

## 실제로 수정한 경계

| 확인한 문제 | revision 3 동작 | 기능 근거 |
|---|---|---|
| 기본 명령은 v1, v2는 별도 파일 | 두 명령과 import가 동일 core 사용 | 실제 subprocess CLI 10개 사례 |
| locale 날짜와 의미 불명 `-00:00` 수용 | ISO 날짜+알려진 명시 offset만 허용. 같은 순간의 `+09:00`/`Z`는 동등 | 날짜 모호성·naive·unknown offset·정상 offset |
| 점수 확정과 검사 시작이 같은 시각 | `decision_at < inspection_started_at` 필수. 같은 초에 실제 순서가 있었다면 더 정밀한 원천 기록 필요 | 검사 시작 동시각 차단 |
| 참/거짓이 검사시간·대기시간·확률의 1/0처럼 취급 | 계약 숫자에 bool 거부 | 시간 2개, 추출확률, 기존 queue bool |
| 잘못된 JSON 모양·중복 키·NaN | 구조화된 차단 결과. CLI는 새 영수증과 종료코드2 | object/중첩 구조 및 두 명령 실제 실행 |
| 비어 있거나 중복된 학습 라벨 키 | `(policy,label_event_id)` 고유한 비어 있지 않은 문자열 요구 | 빈 키·중복 키 |
| 기존 event_id를 새 original_event_id로 가림 | 두 식별자 모두 과거 row_id 집합과 대조 | 노출 ID 변형 |
| 만료 시각과 새 도착이 같을 때 이전 행이 공간 점유 | 기다리는 행은 `expiry <= now`에서 먼저 제거. 서비스 완료 `== expiry`는 허용 | 경계에서 새 행 검사 가능·정확한 완료 허용 |
| 마지막 슬롯 후 도착을 일반 미처리로만 기록 | 남은 도착에도 입장/overflow 적용, 종료까지 만료 기록. 결정이 종료 이상이면 `unavailable_by_window_end` | overflow/만료/종료·동시 다중 자원 |
| 추출 독립성 체크박스만으로 파일 검증 통과 | 실제자료는 로컬 추출계획 JSON, SHA256, 계약 일치 필수 | 누락·변조·설계 불일치·정상 가짜 fixture |
| 표 검사 API 결과가 출처 검토 준비 상태로 표시됨 | 표 검사와 로컬 파일 일치 검사의 상태·범위 분리 | `source_files_verified` false/true 구분 |

검증 결과의 `queue_trace`는 정책별 재생 기록이다. `expired.at`은 실제 계약상 만료 시각이며 검사 완료 기록도 완료 시각이다. 기록의 배열 순서가 모든 자원의 시간순 로그라는 보장은 없으므로 시간대별 집계는 `at`을 사용한다. 기다리는 행과 검사 중인 행은 구분하며 같은 사건을 두 슬롯에서 검사할 수 없다. 주입한 잘못된 배정은 차단한다.

## 자동 검사와 사람 확인의 경계

| 주장 | 구현으로 검사하는 것 | 여전히 필요한 증거 |
|---|---|---|
| 전체 생산 프레임 | 제출 events 내부 모든 정책·표본 기록의 ID 포괄, 중복·조인 검사 | 실제 MES 생산총수와 누락 대조. 누락된 행을 파일 자체로 발견할 수 없음 |
| 검사 전 이용 가능한 입력 | 허용 열, 측정≤수신≤결정, 누락 hold | 원천 시계 신뢰성, 실제 모델이 사용한 열·전처리·숨은 결과 대리변수 검토 |
| 미래/평가 라벨 비사용 | 제출 label_uses의 시각·ID와 평가 ID 교집합 | 학습 이력의 완전성, 기존 데이터 재명명·재인코딩 여부, 실제 학습 코드 |
| 독립 추출 | 고정 hash 표본 재계산, 전체 추출 기록, 모든 선택 라벨, 계획 파일 해시·계약 일치 | 계획의 실제 사전 동결, 원본 ID 불변성, 독립 담당/자원·현장 운영 기록 |
| 공평한 검사 자원 | 같은 슬롯과 만료·대기한도·동점 규칙으로 재생 | 실제 검사 소요시간·인력·보관공간·서비스 규칙과 계약 일치 |
| 실제 출처 | 폴더 내부 파일과 선언 SHA256의 일치 | 진위·권한·외부 서명 검증. 로컬 해시는 발행자/작성시각 인증이 아님 |
| 성능·ROI·일반화 | **계산하지 않음** | 새 독립 데이터, 사전 동결 지표/가드레일, 비용 기준·불확실성 분석 |

따라서 모든 결과에서 `external_provenance_verified=false`, `performance_evidence_created=false`, `field_readiness_certified=false`다. 실제자료의 `validate_tables()` 통과 상태는 `tables_checked_bundle_evidence_required`, `validate_bundle()`의 파일 일치까지 통과하면 `ready_for_human_provenance_review`다. 합성자료는 `synthetic_functional_checks_only`다. 실제자료 분기를 시험하는 fixture도 가짜 파일로 만든 시험이며 실제자료 확보나 성능 증거가 아니다.

## 검증 기록과 남은 범위

- 수정 전 새 37사례: **30 실패 / 7 통과**. 이는 독립 결함 30개라는 뜻이 아니다. 동일 결함의 두 CLI 반복과 예상 상태/버전 검사가 포함된다.
- 같은 37사례+기존 미래 평가 26사례: **63 통과**. 경로 제한·정확한 과거 해시·다중 자원 5사례 추가 후 새 사례42개.
- 전체 회귀: **151 통과**. `reports/reproduction/tests_20261003T064125Z_1b5371b1/`의 stdout·JUnit·영수증. 수정 전후 로그는 `reports/future_review_round10/`.
- 예전 보고서/슬라이드 검증기는 명시한 보존 소스에만 해시 대체 경로를 허용한다. 잘못된 해시와 보존 파일 변조를 별도 시험으로 거부한다.

여전히 한 개의 공통 대기열, 고정 서비스시간, drop-new, 완료 기준 만료, 감사 별도 자원만 지원한다. 실제 수신시각을 모르면 행 순서를 초 단위로 바꿔 넣지 않는다. 새로운 학습/성능 실험은 자료와 사전 설계가 갖춰진 뒤 별도 등록한다. 그동안 기존 보고서의 표현 정확성, 실행 재현과 심사 질의 대응은 계속 개선한다.
