# CastGuard · 소스와 검증 코드

설비 가동이력과 다이캐스팅 품질을 연결하는 분석·검사 대기열의 연구 코드입니다. `JH`는 소스·테스트·설정·기술 문서를 공개하는 브랜치입니다. 기존 저장소에 추적된 데이터 9개는 그대로 유지합니다. 새로운 데이터, 저장 모델, 행별 예측, ZIP, 생성 보고서·발표, 외부 원문 사본, 내부 작업 기록은 이번 변경에 포함하지 않습니다.

품질 모델과 Gate는 기존 연구 목표를 함께 달성하지 못했습니다. 최근 수정은 평가 분모·후보 비교·검사 시점의 신뢰성 개선이며, 저장된 성능 수치의 상승이나 새로운 독립 평가가 아닙니다. [실험 검토](reports/today_closeout/EXPERIMENT_REVIEW.md)와 [실행 범위](CURRENT_REVIEW.md)를 함께 읽으세요.

## 설치와 소스 테스트

확인 환경은 Windows x64 / CPython 3.12.14입니다. 새 폴더에 체크아웃하고 Python 3.12로 실행합니다. 잠금 파일은 36개 의존성의 버전·wheel 해시를 고정하며, 설치에는 공식 PyPI 연결이 필요합니다.

```powershell
python --version
python -I -X utf8 -m venv .venv
& ./.venv/Scripts/python.exe -I -X utf8 -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r requirements-review-win-py312.lock
& ./.venv/Scripts/python.exe -I -X utf8 -m pip check
& ./.venv/Scripts/python.exe -I -B -X utf8 run_review_tests.py --source-only
```

소스 전용 복사본에서 **223개 통과, 7개 명시적 제외**를 확인했습니다. 합성 사례와 기존 추적 데이터로 누수 방어·분할 재구성·대기열·평가 계약을 검사합니다. 제외 목록과 이유는 [실행기](run_review_tests.py)에 고정돼 있고 매 실행 영수증에도 기록됩니다. 실패를 자동으로 건너뛰지 않습니다. `make test`도 같은 범위입니다.

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
