# 미래 평가 v2 호환 안내 — 기본 구현은 revision 3

`future_evaluation_v2.py`와 버전 없는 `future_evaluation.py`는 이제 모두 `future_evaluation_core.py`의 revision 3을 실행한다. 새 실행에서는 아래 기본 명령을 사용한다.

```powershell
python -B future_evaluation.py init --output incoming/new_collection
python -B future_evaluation.py validate --directory incoming/new_collection --output reports/future_validation/new_receipt.json
```

CSV schema1과 공개 함수는 유지하며, 과거 v2 명령을 사용하는 스크립트도 현재 구현을 호출한다. 원본 v2 코드는 `legacy/future_evaluation_v2.py`, 당시 이 안내는 [보존본](archive/round10_legacy/FUTURE_EVALUATION_V2.md)에 바이트 그대로 있다. 보존본은 과거 재현용이며 현재 실행 안내가 아니다.

회차9에서 고친 opaque ID·빈 run/resource·bool queue 문제는 유지한다. 회차10에서 입력 모양·날짜·학습 라벨 키·검사 동시각·만료/종료 경계·추출계획 파일과 결과 상태를 보완했다. [현행 계약](FUTURE_EVALUATION_CONTRACT.md), [변경과 검증 범위](FUTURE_VALIDATION_REVIEW_ROUND10.md), [자료 요청서](DATA_REQUEST_ROUND8.md), [미동결 통계 계획](FUTURE_STATISTICAL_PLAN_ROUND9.md)을 함께 사용한다. 새 성능평가 결과는 없다.
