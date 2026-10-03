# 공개 소스와 로컬 산출물

시작은 [README](README.md), 실행 범위는 [CURRENT_REVIEW](CURRENT_REVIEW.md)입니다.

| 경로 | 공개 범위 |
|---|---|
| `castguard/`, 루트 Python·PowerShell | 학습·평가·검증·문서 생성 소스. 일부 명령은 별도 산출물 필요 |
| `configs/`, 의존성 잠금 파일 | 기존 설정과 재현 환경 |
| `tests/` | 전체 시험 소스. `--source-only`는 223개 실행, 7개 의존성 제한을 명시 |
| `templates/` | 빈 미래 평가 입력 양식·계약 |
| `legacy/` | 역사적 코드 확인에 필요한 보관 소스. 현재 평가 우회 권한 아님 |
| `docs/` | 선택한 기술 문서. 과거 로컬 근거 경로가 남아 있을 수 있음 |
| `notebooks/oct03_evidence.ipynb` | 저장 출력이 없는 분석 노트북. 전체 실행에는 별도 결과 필요 |
| `reports/today_closeout/EXPERIMENT_REVIEW.md` | 수정과 해석의 서술. 연결된 상세 산출물은 로컬 보관 |
| `data/` | 이번 변경 이전부터 추적된 원본·전처리 9개 파일 유지. 새 데이터 추가 없음 |

`deliverables/`, `review/`, 나머지 `reports/`, `artifacts/`, `docs/sources/`, `docs/archive/`, `docs/daily/`와 내부 작업 기록은 새 업로드에서 제외합니다. 로컬 파일은 원래 경로에 그대로 남습니다. 기존 추적 파일은 `.gitignore`에 추가해도 삭제되거나 추적 해제되지 않습니다.
