# CastGuard · 소스와 검증 코드

다이캐스팅 공정·품질·설비 이력의 모델과 검사 정책을 검토하는 연구 코드입니다. 이번 소스 업데이트는 보고서의 수치/가정 회귀 검사와 두 개의 명시적 판독 경로를 제공합니다. 기능 검증을 예측 성능 향상·현장 효과·제출 완료로 해석하지 않습니다.

## 공개 범위

소스·합성 시험·입력 스키마·기술 문서를 제공합니다. **저장 모델, 학습 데이터에서 계산한 실행 프로필, 실제 관측 예제, 행별 예측, 생성 보고서·발표·ZIP, 내부 감사/작업 기록은 포함하지 않습니다.** 저장소에서 이미 추적 중이던 데이터 9개는 변경하지 않았으며 새 데이터를 추가하지 않았습니다.

두 판독 CLI의 실제 추론에는 권한이 있는 로컬 모델/프로필 묶음이 필요합니다. 이 소스만으로 해당 모델을 내려받거나 자동으로 학습하지 않습니다. 합성 fixture를 사용하는 source-only 시험은 모델 묶음 없이 실행할 수 있습니다.

## 설치와 source-only 검사

검증 환경은 Windows x64 / CPython 3.12.14입니다. 기존 잠금 파일은 의존성 버전과 wheel 해시를 고정합니다. 설치에는 공식 PyPI 연결이 필요합니다.

```powershell
python -I -X utf8 -m venv .venv
& .\.venv/Scripts/python.exe -I -X utf8 -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r requirements-review-win-py312.lock
& .\.venv/Scripts/python.exe -I -X utf8 -m pip check
& .\.venv/Scripts/python.exe -I -B -X utf8 run_review_tests.py --source-only
```

현재 공개 후보에서 **391개 통과, 기존 artifact 검사 7개 명시적 제외**를 확인했습니다. 제외 목록과 이유는 [시험 실행기](run_review_tests.py)에 고정돼 있습니다. 실패를 자동으로 건너뛰지 않습니다. 실제 공개 후보의 파일만 가진 별도 복사본에서 검사했으며, 로컬 비공개 파일을 읽은 전체 검사 결과로 대신하지 않았습니다. 자세한 경계는 [CURRENT_REVIEW](CURRENT_REVIEW.md)를 보세요.

## 판독 경로

| 경로 | 입력 계약 | 공개 소스의 실행 경계 |
|---|---|---|
| [공정14 관측 입력](docs/OBSERVABLE_QUALITY.md) · observable_quality.py | 완료된 동일 Shot의 공정값 14개. 품질 파일·카운터·과거 이력 불필요 | 기존 A0 동결 모델을 명시적으로 사용. 신규 입력 형식 계산 가능성이 현장 수신·미래 성능 검증을 뜻하지 않음 |
| [역사적 A/queue 재생](docs/DECISION_REVIEW.md) · decision_review.py | 역사적 품질 파일 순서와 정확한 공정 이력 패킷 | 과거 카운터를 생산 순번으로 바꾸지 않음. 모델 간 자동 fallback 없음 |

둘 다 실제 모델 점수와 log-odds 개별 설명을 출력하며, 미지원 입력·미학습 제품·결측을 명시합니다. 자동 설비 제어·검사 정책 변경·검증된 불량 확률은 제공하지 않습니다. 원래 모델의 약한 성능과 데이터/제품/run 이동 한계는 남아 있습니다.

`review_claims.py`와 문서 검증 경로는 관측/전체 에피소드 분모, cavity 의미의 미확인, 비용 가정 등의 회귀를 검사합니다. 실제 문서 검증에는 별도 원고·원천·행별 행동 산출물이 필요하고 누락되면 실패합니다. 합성 시험의 성공은 비공개 보고서가 검증됐다는 뜻이 아닙니다.

## 기존 연구 자료

기존 기술 문서의 reports/, review/, artifacts/ 링크는 로컬 연구 묶음을 가리킬 수 있습니다. 이 업데이트는 해당 산출물을 새로 게시하지 않습니다. 이미 노출된 test의 재생은 독립 미래 검증이 아니며, 과거 자료를 다시 분할하거나 설명 기능을 추가한 것으로 일반화 성공을 주장하지 않습니다.
