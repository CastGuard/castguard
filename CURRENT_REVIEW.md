# CastGuard · 공개 소스의 검증 범위

이 브랜치는 [README](README.md)의 소스 공개 범위입니다. 로컬 전체 검토 ZIP과 구성물이 다르며, PDF/PPTX·저장 모델·행별 결과·외부 원문 사본은 포함하지 않습니다. 기존 저장소의 데이터 9개는 변경하지 않았습니다.

## 이 체크아웃에서 실행

README의 Python 3.12 잠금 의존성 환경을 준비한 뒤 실행합니다.

```powershell
& ./.venv/Scripts/python.exe -I -B -X utf8 run_review_tests.py --source-only
```

검증된 범위는 223개 시험입니다. 최근 세 차례에 추가한 평가 계약·누락 정답·대기열 회귀 62개도 포함합니다. 실행기는 독립적인 임시 폴더와 영수증을 `reports/reproduction/` 아래 만들며 기존 파일을 덮어쓰지 않습니다. 생성 결과는 Git에서 제외됩니다.

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
