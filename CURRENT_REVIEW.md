# CastGuard · 공개 소스의 검증 범위

## 제출 후보 완성 · 2026-10-06 23:55 KST

[submission 안내](submission/README.md)에서 보고서14쪽·발표16장·소스ZIP·설문 원본·판독 화면을 확인합니다. 팀명 **RE제조부터시작하는이세계생활**, 팀장 **정가현**, 팀원 **신종훈**을 반영했습니다.

`add`의 피드백 지연/관측률 분석을 공정 event 기준으로 도입했습니다. 같은 구간 재사용 test에서 과거 검사결과 추가 전후 AP0.3713→0.3845, AUC0.7378, 20% 순위검사117/272입니다. 미래 구간 일관성 및 #41 추가가치 채택에는 실패했습니다. 이전 실험은 보존하고 새 결과는 `reports/oct06_research`에 분리했습니다. test는 독립 검증이 아닙니다.

현재 관측·과거 회신으로 위험·설명·지원경고·사람검토를 자동 산출하는 [새 입력 계약](docs/SUBMISSION_READER.md)을 연결했습니다. 실제 생산중지/설정 변경은 없고 기존 검사를 면제하지 않습니다. 전체413개 검사, 최종 ZIP15개 검사와11건 추론, 별도 ZIP 전체 학습210개 결과 일치를 확인했습니다. [최종 검수](reports/oct06_submission/final_checks.json).

실제 서명과 포털 접수는 참가팀 단계입니다. HTML 브라우저 조작은 도구의 로컬 URL 보안 차단으로 미검수입니다. 아래는 과거 회차별 결과입니다.


## 10/5 품질 파일 의존성 교정 · 2026-10-05 13:10 KST

기존 A/B/B2는 품질 파일에서 중복 제거 후 만든 `shot_position`을 사용했다. queue의 품질 점수 유무도 qpart 행 존재에 의존했다. 카운터를 미리 넣은 라벨 없는 재생은 신규 관측 입력 기능과 같지 않다. [원인 감사](reports/observable_quality/dependency_audit.json).

새 `observable_quality.py`는 원래 10/2 A0 / forward fold2 / logistic / seed17만 명시적으로 사용한다. 실제 feature 목록은 독립된 공정 원본의 현재14개 값이고 counter/history/품질 파일이 없다. 원래 학습 코드·입력·설정·artifact 해시와 저장 전처리를 확인했다. 선택 기준은 입력 계약·기존 정확한 설명 adapter·가장 이른 forward fold/첫 seed이며 노출-test 성능으로 재선정하지 않았다.

모델·프로필만 있는 실행 폴더에서 카운터를 완전히 생략한 실제 형식/합성 신규 입력을 계산했다. 현재값 누락/null은 미산출하고 counter/라벨 주입·역사적 schema는 거절한다. 실제 저장 예측 1,554건(기존 validation1,157+노출test397) 최대차2.3e−16, 설명 margin 최대오차1.8e−15. 새 평가 지표를 계산하거나 미래 성능을 입증한 것이 아니다. [실제 검증](reports/observable_quality/verification/verification.json).

기존 동일 fold의 validation A0/A/B AP는 .1333/.1976/.1977, 불량률 .1366이다. A0 test Brier .7830 등 불리한 결과를 함께 보존하며 성능 승격·자동 운영을 하지 않는다. [사용 계약·기존 비교](docs/OBSERVABLE_QUALITY.md), [새 화면](reports/observable_quality/example_output.html).

전체 [398개 통과·실패/제외0](reports/reproduction/tests_20261005T040457Z_0e630c04/receipt.json), 별도 경로의29개 회귀 포함. [변경·보존 기록](reports/observable_quality/integration.json). 기존 역사적 코드/예제/결과·원본·동결 모델·사용자 가이드북을 보존했다. 아래 기록은 각 이전 회차의 범위다.


## 10/5 입력 순서·이력 신뢰성 검증 · 12:33 KST

기존 판독의 세 결함을 실제 동결 모델에서 확인했다: 다른 ID의 동일 관측 중복, 현재 Cycle_Time과 다음 행의 과거 값 충돌, 다른 관측에 같은 품질 순서 재사용이 점수 산출까지 통과했다. 수정 후 배치 전체를 추론 전에 거절한다. 이력끼리 충돌, 순서 역전/과도한 증가, 최대 정확 정수 초과도 검사한다.

전체 [369개 검사·실패/제외 0](reports/reproduction/tests_20261005T032615Z_87718518/receipt.json), [실제 동결 모델 합성 반례 60건](reports/decision_review/order_reliability/adversaries/verification.json), [실제 20 checkpoint·120개 저장 예측 재생](reports/decision_review/verification.json)을 통과했다. 40개 모델 그룹에서 전체/역순/일부와 개별 호출의 점수·설명·경고가 정확히 같았다. 예측 최대차 2.8e−17, 설명 최대오차 2.7e−14는 그대로다. 합성 반례는 기능 검사이며 실제 생산 관측이나 성능 근거가 아니다.

[명시적 지원 계약](docs/DECISION_REVIEW.md#순서이력의-지원-범위)은 상태 없는 완전한 과거 이력 패킷이다. run 간 이력 혼합은 거절하고 제품 변경만으로 순서를 리셋/필터링하지 않는다. 같은 시각의 사건을 timestamp로 정렬·보정하거나 이전 호출로 누락 이력을 채우지 않는다. 입력 제공자가 보장한 run·순서의 진실성과 호출 간 중복은 독립 인증하지 않는다. 품질 위치는 retrospective_only이며 미학습 제품 점수는 진단용임을 JSON/HTML에 표시한다.

기존 예제의 대안 5건은 서로 다른 가상 시나리오 run으로 구분했다. 실제 추가 데이터가 아니며 7건의 기존 점수/상태는 같다. [이번 변경·보존 영수증](reports/decision_review/order_reliability/integration.json), [변경 전 파일](reports/decision_review/order_reliability/before). 모델/정책 선정·변수쌍 연구는 시작하지 않았다. 아래는 앞선 회차의 검증 기록이다.


## 10/5 로컬 판독 구현 검증

2026-10-05 12:06 KST, 브랜치 JH. [정답 없는 판독](docs/DECISION_REVIEW.md)을 추가했다. `decision_review.py`는 지정 JSON과 해시가 고정된 모델 2개만 사용해 품질·설비 점수, 개별 log-odds 설명, 적용범위와 미산출 이유를 JSON/HTML로 남긴다. 예제 7행은 라벨을 포함하지 않으며 오류 행도 출력에 유지한다. 실제 입력·기대 요약·출처는 `examples/decision_review/`에 있다.

- 기능 회귀 52개를 포함한 **전체 330개 통과, 제외/skip 0개**: [실제 프로젝트 환경 영수증](reports/reproduction/tests_20261005T024822Z_3aacf0e4/receipt.json), [JUnit 결과](reports/reproduction/tests_20261005T024822Z_3aacf0e4/tests.xml).
- 실제 동결 모델 20개 체크포인트·40개 모델, 저장 calibration 예측 120건: 예측 최대차 2.7756e−17, 설명 raw margin 최대오차 2.6202e−14, 점수 재구성 최대오차 8.8818e−16. [실제 재생](reports/decision_review/verification.json).
- 정답·원본·전처리 테이블 없는 별도 폴더에서도 실행했다. 정답 파일 없음/빈 파일/0/1·순서 변경의 네 조건에 출력 불변. 누수 필드·잘못된 schema/숫자·불완전한 이력·모델 불일치는 거절/보류한다. 미학습 제품은 점수와 경고를 함께 남기고 운영 판단을 보류한다.
- 프로젝트 환경의 `python-pptx` 부재로 첫 전체 검사에서 기존 문서 시험 2개가 실패했다. 원래 잠금 파일의 python-pptx 1.0.2, lxml 6.1.3, typing_extensions 4.16.0, xlsxwriter 3.2.9를 해당 wheel 해시로 설치한 뒤 `pip check`와 전체 검사를 통과했다. 검사 제외나 잠금 파일 변경은 없다.
- [통합·보존 기록](reports/decision_review/integration.json)에 변경 파일과 원본/과거 결과 해시 대조를 남긴다. 새 HTML을 브라우저에서 렌더해 확인했다. 사용자 가이드북·기존 보고서·발표·양식·ZIP은 수정하지 않았다.

새 경쟁 모델 학습·후보 선정·임계값 변경·독립 미래 성능 평가는 없다. adapter 단위검사에서만 작은 합성 모델 fixture를 학습한다. 미보정 점수, 상태1 의미, legacy quality-record position과 현장 입력의 대응, 제품2 및 공동지지 한계는 유지된다. 이번 검증은 과거 170개 모델/전체 대기열 감사의 재실행이 아니다. 원격 게시·업로드·제출은 하지 않았다. 아래 항목은 각 날짜의 기존 검증 범위다.


이 브랜치는 [README](README.md)의 소스 공개 범위입니다. 로컬 전체 검토 ZIP과 구성물이 다르며, PDF/PPTX·저장 모델·행별 결과·외부 원문 사본은 포함하지 않습니다. 기존 저장소의 데이터 9개는 변경하지 않았습니다.

## 이 체크아웃에서 실행

README의 Python 3.12 잠금 의존성 환경을 준비한 뒤 실행합니다.

```powershell
& ./.venv/Scripts/python.exe -I -B -X utf8 run_review_tests.py --source-only
```

공개 원격 `59aebf7` 게시 시점에 검증된 범위는 223개 시험입니다. 최근 세 차례에 추가한 평가 계약·누락 정답·대기열 회귀 62개도 포함합니다. 실행기는 독립적인 임시 폴더와 영수증을 `reports/reproduction/` 아래 만들며 기존 파일을 덮어쓰지 않습니다. 생성 결과는 Git에서 제외됩니다.

7개 제외 시험과 이유는 실행기 `ARTIFACT_TESTS`에 명시합니다. 그중 6개는 공개하지 않은 근거 파일이 필요하고, 1개는 원본 CSV 바이트 검증입니다. 기존 Git LF와 원본 CRLF 차이 때문에 원본 바이트 영수증은 Git blob 복사본에 그대로 적용할 수 없습니다. 원본 데이터·manifest·검사 기준은 유지합니다. 합성 fixture는 성능 근거가 아닙니다.

## 전체 산출물이 있어야 실행

다음 명령은 해당 로컬 검토 묶음에서만 사용합니다. 전체 230개 시험과 저장 모델 170개 재생의 기존 성공 기록을 소스 체크아웃의 성공으로 대신하지 않습니다.

```powershell
python -I -B -X utf8 run_review_tests.py
python -I -B -X utf8 review.py check --full-replay --require-package
python -I -B -X utf8 audit_queue_opportunity.py --output verification_runs/queue_opportunities
python -I -B -X utf8 audit_missing_quality.py --output verification_runs/missing_quality_lineage
python -I -B -X utf8 audit_today_experiments.py --output verification_runs/today_experiment_audit.json
```

`audit_queue_opportunity.py`의 전체 484그룹 감사는 별도 명령입니다. 기본 `review.py check`가 전체 감사까지 자동 실행하는 것은 아닙니다. 대기열 독립 참조는 운영 heap·예산 helper를 사용하지 않습니다. 반면 `audit_today_experiments.py`는 원본·분할 감사와 함께 수정된 운영 지표·선정 함수를 재사용해 과거 결과를 대조합니다.

## 해석과 보존

[실험 검토](reports/today_closeout/EXPERIMENT_REVIEW.md)의 저장 점수·선정·행동은 수정 전후 같았습니다. 3,395 Shot 중 관측 품질 정답은 2,879개, 양성은 505개입니다. 나머지 516개와 특히 GQ만 추가 검사한 상태1의 26개를 임의로 양성 또는 비대상으로 판정하지 않습니다. 같은 677개 검사 기회의 실제 사용량은 Q/FIFO 675개, GQ 677개입니다.

원본에 없는 실제 시각·단위·대상 정의·독립 미래 성능은 미측정입니다. 노출 test에서 재선정하거나, 코드 검증 횟수를 모델 성과로 계산하지 않습니다. 전체 검토 파일은 로컬에 보존했고 소스 게시를 위해 삭제·재학습하지 않았습니다.

## 로컬 전체 작업 폴더의 10/4 보고서

로컬 전체 작업 폴더에서는 `review/CastGuard_report.pdf`와 `review/CastGuard_report.md`가10/4 오류·영향요인·KPI 반영본입니다. `docs/STRATEGY.md`의 주장/분모/가정 표와 `docs/TEAM_HANDOFF_2026-10-03.md`의10/5 검토 항목을 함께 봅니다. 이 로컬 전용 경로들은 공개 소스 체크아웃에는 포함되지 않습니다.

보고서만 다시 만들 때에는 전체 근거와 문서 환경이 있는 로컬 폴더에서 `python -I -B -X utf8 build_review.py --report-only --output verification_runs/report_preview`처럼 **새 하위 폴더**를 지정합니다. 현재 편집 원고와 수치 근거를 사용하며 기존 발표 파일은 그대로 둡니다. 기본 전체 빌드도 현재 원고를 우선합니다.

`deliverables/CastGuard_latest_review.zip`은 이전16쪽 보고서를 담은 검증본이며 이번10/4 로컬20쪽 보고서를 포함하지 않습니다. 실제 ZIP 내부 PDF와 현재 PDF의 해시·쪽수가 다름을 확인했습니다. 원격JH는59aebf7 소스 게시 시점 그대로입니다. 다음 제출 후보를 만들 때 보고서·발표·패키지 버전을 맞추고 검수하며, 현재 파일 갱신이 최종 제출/추가 푸시를 뜻하지 않습니다.


## 10/4 로컬 주장 회귀 검사

`python -I -B -X utf8 review_claims.py`는 전체 근거가 있는 로컬 폴더에서 실행합니다. 원본 품질·상태 키를 저장 행동과 대조하고, fold를 seed 안에서 합친 뒤 정책별 에피소드 분자/분모와 관측 정답만의 비용 예시를 다시 계산합니다. 원본 `_1/_2` 열 이름은 cavity의 물리 대응을 증명하지 않으므로 미확인·가정 설명을 요구합니다.

현재 보고서 빌드는 렌더 전에 이 검사를 수행합니다. `verify_review_documents.py`와 현재본의 `review.py check` 문서 연결 검사도 저장된 통과 기록을 신뢰하지 않고 다시 계산합니다. 과거 round8만 있는 bootstrap 출력은 이 검사를 완료한 현재본으로 표시하지 않습니다.

검사 대상은 이름이 지정된 상태 에피소드 KPI 행·queue 설명·접미사 문단·r/s/p 비용 문단입니다. 허용 구조 안에서 숫자와 필수 가정을 검사하며 자유 서술 전체를 이해하는 검증기는 아닙니다. 해당 표/문단 구조를 바꿀 때는 검사와 반례도 함께 검토합니다. 검사 실패를 피하려고 경고 설명을 삭제하거나 원천 정의를 추정하지 않습니다. 새로운 원문이 suffix 의미를 확정하면 근거와 검사를 함께 갱신합니다.

이번 로컬 확인은 새 회귀36개와 인접 기존12개, 합계48개 통과 및 실제 행동80그룹의 기존 `measure` 대조입니다. 실제 원고에 과거 오류7종을 주입하면 모두 실패합니다. 전체230/공개소스223의 이전 검증을 이번에 다시 수행한 것은 아닙니다. 재생성한20쪽 PDF는 현재본과 모든 페이지 텍스트·렌더 픽셀이 같아 기존 원고/PDF/HTML을 그대로 보존했습니다. 발표17장·16쪽 보고서가 든 보존 ZIP·사용자 편집 HTML·원격은 불변입니다. [검증 영수증](reports/today_closeout/checks/oct04_claim_guards.json).


## 10/4 최종 통합 검증

최종 결합 코드와 현재20쪽 보고서를 별도 복사본에서 함께 검사했습니다. 새 검사를 빼거나 artifact 제외 목록을 넓히지 않았습니다. [통합 영수증](reports/today_closeout/checks/oct04_integration.json)에 명령·시험 XML·오류 주입 기록·코드 해시를 남겼습니다.

| 실제 실행 명령 | 최종 확인 범위 |
|---|---|
| `python -I -B -X utf8 review.py check` | 전체278시험, 원본/행동의 주요 지표 대조, 현재 주장 검사, 기존 변이8/8 검출. 작업 폴더에 package manifest가 없다는 사실을 표시 |
| `python -I -B -X utf8 run_review_tests.py` | 전체278통과, 제외 없음 |
| `python -I -B -X utf8 run_review_tests.py --source-only` | 현재 보고서가 있는 로컬 복사본과 보고서/저장행동 없는 소스 복사본 각각271통과·기존7개 명시적 제외 |
| `python -I -B -X utf8 verify_review_documents.py` | 현재20쪽·174수치 연결·17장 발표의23수치 연결·주장 검사 통과 |
| `python -I -B -X utf8 build_review.py --report-only --output verification_runs/새폴더` | 현재 원고를 재생성,20쪽 모든 페이지의 텍스트/렌더 픽셀 동일 |

`--source-only`는 근거 산출물 검증 완료를 뜻하지 않습니다. 같은 코드라도 `review_claims.py`에는 현재 원고·원본 품질/상태·저장 행동이 필요하며, 없으면 경로와 복구 방법을 알리고 실패합니다. 제외7개는 기존과 동일한 외부 HWPX/저장 근거6개 및 Git LF와 원본 CRLF의 바이트 해시1개입니다. `make test`와 `make test-full`의 실행기/범위는 변경하지 않았습니다.

줄바꿈·정책명 강조·KPI 이름 강조의 오탐3종을 고쳤습니다. 실제 원고의 정상 서식5종은 통과하고 같은 서식의 잘못된 분자는 모두 거절합니다. 정식 check·문서검증·build 명령에 잘못된 분모와 누락 원천을 넣은6실행도 모두 실패했으며, 빌드 출력은 생성하지 않았습니다. 일반적인 자유문장 전체의 의미 검증을 보장하는 것은 아닙니다.

전체 저장모델 재생(`--full-replay`), 새 모델 실험, `--require-package`를 사용한 새 ZIP 검증은 이번 범위가 아닙니다. 현재 작업 폴더와 보존 ZIP의 버전이 다르므로 보존 ZIP의 manifest로 현재 코드를 검증하지 않습니다. 현재20쪽·보존ZIP16쪽·원격59aebf7 구분과 기존 파일을 유지했습니다.
