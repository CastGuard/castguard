## 10/8 연구 및 제출 산출물

현재 제출 폴더에는 [보고서 PDF](submission/CastGuard_report.pdf), [발표 PDF](submission/CastGuard_presentation.pdf), [발표 PPTX](submission/CastGuard_presentation.pptx), [소스 ZIP](submission/CastGuard_source.zip)이 있습니다. 모델 탐색·데이터 교차 비교·시간 창 집계 실험 코드와 계획을 함께 보관합니다.

추가 입력의 일관된 품질 개선은 입증되지 않아 기존 S_FB logistic 판독 모델을 유지합니다. 재사용 test의 AUC 0.7378/AP 0.3845는 독립·현장 검증 성과가 아닙니다. [실험 계획](docs/OCT08_CROSSED_SEARCH_PROTOCOL.md)을 참고하세요.

서명 및 포털 접수 여부는 이번 Git 게시 작업에서 확인하지 않았습니다. 아래는 이전 회차의 기록으로 현재 파일 구성과 다를 수 있습니다.

---

# CastGuard · 소스와 검증 코드

## 제출 후보 완성 · 2026-10-06 23:55 KST

[submission 안내](submission/README.md)에서 보고서14쪽·발표16장·소스ZIP·설문 원본·판독 화면을 확인합니다. 팀명 **RE제조부터시작하는이세계생활**, 팀장 **정가현**, 팀원 **신종훈**을 반영했습니다.

`add`의 피드백 지연/관측률 분석을 공정 event 기준으로 도입했습니다. 같은 구간 재사용 test에서 과거 검사결과 추가 전후 AP0.3713→0.3845, AUC0.7378, 20% 순위검사117/272입니다. 미래 구간 일관성 및 #41 추가가치 채택에는 실패했습니다. 이전 실험은 보존하고 새 결과는 `reports/oct06_research`에 분리했습니다. test는 독립 검증이 아닙니다.

현재 관측·과거 회신으로 위험·설명·지원경고·사람검토를 자동 산출하는 [새 입력 계약](docs/SUBMISSION_READER.md)을 연결했습니다. 실제 생산중지/설정 변경은 없고 기존 검사를 면제하지 않습니다. 전체413개 검사, 최종 ZIP15개 검사와11건 추론, 별도 ZIP 전체 학습210개 결과 일치를 확인했습니다. [최종 검수](reports/oct06_submission/final_checks.json).

실제 서명과 포털 접수는 참가팀 단계입니다. HTML 브라우저 조작은 도구의 로컬 URL 보안 차단으로 미검수입니다. 아래는 과거 회차별 결과입니다.


## 10/5 공정 관측 입력 경로 추가 · 13:10 KST

품질 파일의 행 순서가 필요한 기존 재생과 별도로, **현재 공정값 14개만 받는 A0 동결 모델 경로**를 추가했습니다. 품질 정답·품질/생산 카운터·과거 이력 없이 점수와 개별 설명이 나옵니다. 입력 가용성으로 선택한 기존 baseline이며 재학습·자동 모델 전환·정책 변경은 없습니다.

```powershell
& .\.venv\Scripts\python.exe -I -B -X utf8 observable_quality.py --input examples/observable_quality/shots.json --output reports/observable_quality/my_review.json --html reports/observable_quality/my_review.html
```

[새 관측 입력 예제](reports/observable_quality/example_output.html) · [입력 계약·원인·기존 성능 비교](docs/OBSERVABLE_QUALITY.md) · [검증/보존 기록](reports/observable_quality/integration.json).

실제 공정 예제 점수 .290169, 카운터 없는 합성 신규 입력도 계산됩니다. 기존 validation AP .1333 / 불량률 .1366으로 예측력이 강하지 않습니다. 새 입력 처리 능력과 현장 효과는 구분하며, 실제 수신 시각·미래 성능·보정은 미검증입니다. 전체 398개 검사 통과, 기존 A0 저장 예측 재현. 아래 `decision_review.py`와 이전 예제는 역사적 A/queue 재생으로 보존합니다.


## 10/5 입력 순서·이력 보강 · 12:33 KST

같은 관측의 중복, 현재/과거 Cycle_Time 모순, 품질 순서의 중복·역전·과도한 증가를 **점수 산출 전에 배치 전체 오류로 거절**합니다. 완전한 이력을 유지한 전체·역순·일부 배치와 개별/분할 호출은 같은 결과를 냅니다. 호출 간 중복 추적·타임스탬프 정렬은 지원하지 않으며, 품질 위치 카운터는 과거 자료 재생 전용입니다. [지원 입력 계약](docs/DECISION_REVIEW.md#순서이력의-지원-범위).

실제 프로젝트 전체 **369개 검사 통과·제외 0**, 동결 모델 반례 60건, 실제 40개 모델 그룹의 배치/개별 일치를 확인했습니다. [갱신한 예제 화면](reports/decision_review/example_output.html)과 [이번 검증 기록](reports/decision_review/order_reliability/integration.json). 기존 7건의 점수/상태는 그대로이며, 진단용·미학습 제품 경고를 화면에서 강조했습니다. 아래 330개 기록은 첫 구현 시점의 결과입니다.


## 10/5 로컬 추가 기능: 정답 없는 Shot 판독

2026-10-05 12:06 KST: 기존 동결 모델로 입력 1건/배치의 품질 점수·설비 상태 점수·개별 변수 기여·학습 범위 경고를 출력합니다. 입력 오류·필수값/이력 부재는 이유를 표시하고 해당 판독을 보류합니다. 정답·원본/전처리 테이블은 추론에 필요하지 않습니다. 저장 모델이 있는 로컬 전체 작업 폴더용 기능입니다.

```powershell
& .\.venv\Scripts\python.exe -I -B -X utf8 decision_review.py --input examples/decision_review/shots.json --output reports/decision_review/my_review.json --html reports/decision_review/my_review.html
```

새 출력 파일명을 사용하세요. [사용 안내·입력 계약](docs/DECISION_REVIEW.md), [실제 예제 화면](reports/decision_review/example_output.html), [검증·보존 기록](reports/decision_review/integration.json).

전체 **330개 검사 통과·제외 없음**, 기존 20개 체크포인트의 저장 예측 120건 최대차 2.8e−17을 확인했습니다. 새 모델 성능 향상이나 독립 성능 평가가 아닙니다. 점수는 미보정이며, 제품2와 현장 품질 입력 순서의 적용 가능성은 미검증입니다. 새 기능은 로컬에만 추가했고 아래 공개 원격·10/4 기록은 이전 시점 그대로입니다.


설비 가동이력과 다이캐스팅 품질을 연결하는 분석·검사 대기열의 연구 코드입니다. `JH`는 소스·테스트·설정·기술 문서를 공개하는 브랜치입니다. 기존 저장소에 추적된 데이터 9개는 그대로 유지합니다. 새로운 데이터, 저장 모델, 행별 예측, ZIP, 생성 보고서·발표, 외부 원문 사본, 내부 작업 기록은 이번 변경에 포함하지 않습니다.

품질 모델과 Gate는 기존 연구 목표를 함께 달성하지 못했습니다. 최근 수정은 평가 분모·후보 비교·검사 시점의 신뢰성 개선이며, 저장된 성능 수치의 상승이나 새로운 독립 평가가 아닙니다. [실험 검토](reports/today_closeout/EXPERIMENT_REVIEW.md)와 [실행 범위](CURRENT_REVIEW.md)를 함께 읽으세요.

## 로컬 보고서와 보존 ZIP의 버전

**2026-10-04 KST 현재:** 로컬 `review/CastGuard_report.pdf`는 오늘 수정한 **20쪽 보고서**입니다. `deliverables/CastGuard_latest_review.zip`에는 이전 **16쪽 보고서**가 들어 있으며 오늘 수정본은 포함하지 않습니다. ZIP 파일명에 latest가 있어도 현재 편집본과 같은 버전이라는 뜻은 아닙니다. 기존 ZIP은 재현 이력으로 보존했습니다.

이 안내와 보고서 보완은 로컬 변경입니다. 공개 원격JH는 `59aebf7` 소스 게시 시점 그대로이며 추가 푸시하지 않았습니다. 발표는 기존17장이고 다음 팀 검토에서 필요한 설명을 맞춥니다. 최신 로컬 파일·재현 범위는 [CURRENT_REVIEW](CURRENT_REVIEW.md)를 따릅니다. 아래 설치/시험 안내는 공개 소스 범위입니다.

**10/4 최종 로컬 통합 검사:** 현재 코드의 전체278개 시험과 `review.py check`가 통과했습니다. `run_review_tests.py --source-only`는 현재 보고서가 있는 로컬 복사본과 산출물을 제외한 소스 복사본 모두271개 통과·기존7개 명시적 제외입니다. 아래223/230은 공개 시점의 과거 기록이며, 이번 추가 코드는 아직 원격에 게시하지 않았습니다. [실제 범위와 영수증](CURRENT_REVIEW.md#104-최종-통합-검증).

## 설치와 소스 테스트

확인 환경은 Windows x64 / CPython 3.12.14입니다. 새 폴더에 체크아웃하고 Python 3.12로 실행합니다. 잠금 파일은 36개 의존성의 버전·wheel 해시를 고정하며, 설치에는 공식 PyPI 연결이 필요합니다.

```powershell
python --version
python -I -X utf8 -m venv .venv
& ./.venv/Scripts/python.exe -I -X utf8 -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r requirements-review-win-py312.lock
& ./.venv/Scripts/python.exe -I -X utf8 -m pip check
& ./.venv/Scripts/python.exe -I -B -X utf8 run_review_tests.py --source-only
```

공개 원격 `59aebf7` 게시 시점의 소스 전용 복사본에서 **223개 통과, 7개 명시적 제외**를 확인했습니다. 합성 사례와 기존 추적 데이터로 누수 방어·분할 재구성·대기열·평가 계약을 검사합니다. 제외 목록과 이유는 [실행기](run_review_tests.py)에 고정돼 있고 매 실행 영수증에도 기록됩니다. 실패를 자동으로 건너뛰지 않습니다. `make test`도 같은 범위입니다.

## 전체 검토와 다른 점

- 6개 시험은 제외한 외부 HWPX 또는 저장된 행별 행동·결과 근거가 필요합니다.
- 1개 시험은 원본 CSV의 바이트 해시를 검사합니다. 기존 Git CSV는 LF, 원본 manifest가 기록한 로컬 원본은 CRLF여서 Git blob 그대로의 복사본은 이 검사에 통과하지 않습니다. 값 재구성 검사와 바이트 동일성은 별개이며, 데이터나 manifest를 바꾸거나 해시 검사를 완화하지 않았습니다.
- 전체 230개 시험·170개 저장 모델 재생·484그룹 독립 대기열 감사의 기존 통과 기록은 **로컬 전체 검토 묶음**의 결과입니다. 이 공개 소스 체크아웃의 성공으로 표시하지 않습니다.
- `review.py check --full-replay --require-package`, 지표 재계산·과거 재생·문서 생성 명령은 해당 원본 산출물과 manifest가 모두 있는 검토 묶음에서 실행해야 합니다. `make test-full`은 전체 시험을 실행하며 필요한 파일이 없으면 실패합니다.

기술 문서의 과거 `reports/`, `review/`, `docs/sources/` 링크는 로컬 근거 경로를 가리킬 수 있습니다. 해당 파일은 이 브랜치에 새로 공개하지 않았습니다. 보고서·발표·ZIP은 원래 로컬 위치에 보존됩니다.

| 찾을 내용 | 위치 |
|---|---|
| 모델·전처리·고정 분할 코드 | [castguard](castguard), [설정](configs), [전처리 명세](docs/PREPROCESSING.md) |
| 평가 계약·대기열·독립 참조 | [평가 계약](experiment_integrity.py), [대기열](oct03_queue.py), [독립 구현](audit_queue_opportunity.py) |
| 미래 자료 입력 계약 | [계약](docs/FUTURE_EVALUATION_CONTRACT.md), [빈 양식](templates/future_evaluation) |
| 기술 문서와 폴더 구분 | [문서 안내](docs/README.md), [폴더 안내](FOLDER_GUIDE.md) |

기존에 노출된 test를 다시 사용한 결과를 미래 일반화로 해석하지 않습니다. 원천 상태 코드·품질 대상 정의·실제 검사 시각·독립 미래 자료의 부족은 여전히 연구 한계입니다.
