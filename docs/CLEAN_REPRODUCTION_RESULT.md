# 새 의존성 환경 재현 결과 · 2026-10-03

**Windows x64 / CPython 3.12.14의 빈 가상환경 두 개에서 설치와 재현을 확인했다.** 기존 개발 환경과 과거 실험 산출물은 보존했다. 새 성능·독립 test·현장 효과를 얻은 실험은 아니다. 현재 시작점은 [CURRENT_REVIEW.md](../CURRENT_REVIEW.md), 현재 배포 파일은 `deliverables/CastGuard_latest_review.zip`이다.

| 확인 항목 | 실제 결과 | 범위와 한계 |
|---|---|---|
| 기존 ZIP 설치 | 과학 계산 고정29개 설치, `pip check` 통과 | 최초 sandbox 접속은 WinError10013으로 차단. 승인된 공식 PyPI 접근은 성공 |
| 통합 잠금 설치 | 두 번째 빈 환경에36개 버전·wheel SHA256 고정 설치 통과 | 시스템 패키지 상속 없음. 먼저 받은 공식 wheel 캐시 사용. 인터넷 없는 설치는 아님 |
| 회귀·변이·저장 근거 | 168시험 통과, 중요한 변이8/8검출, 저장 모델170개 재생 | 회차11의164시험에 환경/비교 오류4시험 추가. 시험 수는 성능 실적이 아님 |
| 원본에서 재구성 | q42 4,617×80, m41 5,161×29, p40 73,612×40, 분할181,170×8의 값·행·열 일치 | 저장 형식/nullable dtype의 바이트 동일성을 주장하지 않음 |
| 고정 재학습2회 | logistic·LightGBM의 수치 지표76개 최대오차0 | q42/all/within_run/primary/A/seed17. 설정 변경·튜닝 없음. 과거 validation/test 재사용 |
| LightGBM 행별 예측 | 2,034행의 ID·역할·정답·판정 동일, 확률/임계값4,068값 최대오차0 | 허용오차는 실행 전1e-12로 고정. 로지스틱 원래 행별 예측은 ZIP에 없어 비교하지 않음 |
| 문서 재생성 | 보고서16쪽·발표17장 검증, native 넘침0 | 108개 보고서/22개 발표 수치 연결. 이전 검토본과33장 렌더 픽셀 모두 동일 |
| 실제 제출 준비 | 4항목 부재, `review.py ready` 종료2 | 팀정보/서명·설문·포털 규격·최종 블라인드 증거 미확보. 제출 안 함 |

사전 고정 계획은 [재현 프로토콜](CLEAN_REPRODUCTION_PROTOCOL.md), 실행 등록과 비교는 [등록](../review/checks/bounded_retrain_registration.json)·[결과](../review/checks/bounded_retrain_summary.json)에 있다. 두 번째 환경에서 원본 재구성과 두 모델 학습·비교의 전체 소요는 **2.735초**였다. 이 작은 사례의 시간으로1,015회 전체 행렬의 시간을 추정하지 않는다.

## 버전과 설치 증거

Python3.12.14, pip25.0.1을 사용했다. 주요 버전은 numpy2.3.5, pandas3.0.1, pyarrow23.0.0, scipy1.18.1, scikit-learn1.7.2, LightGBM4.6.0, CatBoost1.2.8, pytest8.4.2다. 문서 도구는 python-pptx1.0.2, ReportLab4.4.9, pypdf6.10.0이다.

기존 `requirements-lock.txt`의29개 버전은 그대로다. 문서용 목록의 전이 의존성 **charset-normalizer3.5.2, lxml6.1.3, typing-extensions4.16.0, XlsxWriter3.2.9**를 새 통합 목록에서 고정했다. 전체36개 버전은 [통합 버전 목록](../requirements-review-lock.txt), Windows CPython3.12용 wheel 해시는 [설치 잠금 파일](../requirements-review-win-py312.lock)에 있다. [설치 배포물 기록](../review/checks/dependency_installations.json)은 공식 PyPI에서 받은 `files.pythonhosted.org` URL·버전·SHA256을 포함한다.

실제 설치 명령의 핵심 인자는 다음과 같다. `python`은 새 환경의 실행 파일이며 전체 PowerShell 순서는 시작 안내에 있다. `--report`는 작업 영역에 pip의 실제 설치 기록을 남길 때 사용했다.

```powershell
python -I -X utf8 -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-lock.txt
python -I -X utf8 -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r requirements-review-win-py312.lock
python -I -X utf8 -m pip check
python -I -X utf8 review.py environment --documents
python -I -X utf8 review.py check --full-replay --require-package
python -I -X utf8 review_retrain.py
python -I -X utf8 verify_review_documents.py
python -I -X utf8 build_review.py --output review_rebuilt
```

첫째와 둘째 설치 명령은 **각각 다른 빈 환경**에서 실행했다. 첫 환경의 문서 도구는 과학 버전 제약을 걸고 별도 설치했다. 두 번째 명령이 새 사용자의 통합 설치 경로다. 네트워크 제한 환경에서는 공급원 접근 실패를 먼저 확인해야 하며 설치 실패를 패키지 부재로 단정하면 안 된다.

## 수정한 실행 문제

`build_review.py`는 격리 실행(`-I`)에서 내부 `review_readiness`를 찾지 못했다. 묶음을 만드는 `package_review.py`에도 같은 경로 문제가 있었다. 자기 파일의 프로젝트 루트만 명시적으로 추가해 수정했다. 글꼴 누락도 결과 폴더 생성 전에 필요한 이름을 알리도록 했다. `verify_review_documents.py --review-folder`로 새 출력도 검증한다. 새 환경과 문서 의존성이 같은 환경에서 동작하는 것을 확인했다.

`review.py environment`는29개 또는 문서 포함36개를 모두 대조하고, `check`는 잘못된 Python/누락/버전 불일치에서 멈춘다. 실행 시 무조건 ‘기존 환경 사용/새 설치 미확인’이라고 기록하던 문구를 없앴다. 환경 검사는 설치 출처를 인증하는 기능이 아니며 설치 이력은 별도 영수증에 둔다. [전체 범위와 해시](../review/checks/clean_environment.json), [환경](../review/checks/clean_runtime.json), [검증 결과](../review/checks/clean_working_review.json)를 확인할 수 있다.

## 남은 범위와 다음 검토

전체1,015회 재학습은 수행하지 않았다. 코드·원본·고정 설정은 있고 대표2회 학습 경로와 저장170모델이 이 환경에서 동작했으므로 추가 전체 재실행을 시도할 기반은 있다. 그러나 모든 분할/모델군의 재학습 동일성·총시간은 확인하지 않았다. 현재 문서·재현 문제를 해결하는 데 공개 test의 전체 재학습은 새 일반화 근거를 더하지 않는다. 차이가 발견되면 해당 고정 작업만 먼저 재현하고 선택이나 튜닝에 쓰지 않는다.

Python 실행기·Windows 자체·Microsoft Office·글꼴 설치는 새로 검증하지 않았다. 문서 재렌더는 이 컴퓨터에 이미 설치된 PowerPoint16.0과 Batang/Malgun을 사용했다. Office/글꼴/실행기/wheel을 ZIP에 배포하지 않는다. 다른 운영체제·CPU·Python 패치 버전과 완전 오프라인 설치는 미검증이다. 이미 포함된 PDF 열람에는 이 생성 환경이 필요하지 않다.

과거3395생산·2879품질관측·505양성의 FIFO22.376%, Q20.871%, GQ20.238%는 바뀌지 않았다. 하나의 유효 기준선,0을 포함하는 조건부 구간 범위, 대기 차이, 공개 test의 한계를 유지한다. 다음 작업은 제출 규격·외부 증거 점검, 실제 발표 길이/팀 피드백에 따른 설명 개선이다. 독립 자료 없이 새로운 성능 우위를 주장하지 않는다.
