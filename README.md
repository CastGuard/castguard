# CastGuard

**설비 가동이력 인지형 다이캐스팅 품질불량 조기예측 및 공정개선 AI**
2026 제6회 K-인공지능 제조데이터 분석 경진대회 · 주제 ②

설비가 품질예측 가능한 정상 상태인지 먼저 판단하고(Gate), 정상 상태에서 불량 위험과 유형을 예측해,
추가검사·재작업·조건조정·생산중지 같은 현장 조치로 연결한다. 성능은 중복 제거와 구간 내 시간순 검증으로
누수 없이 측정하고, 모델이 실패하는 조건(새 가동구간)까지 정량으로 보고한다.

## 실행

```bash
pip install -r requirements.txt     # KAMP Note에는 이미 설치되어 있음
python -m castguard all             # 환경 점검 → 전처리 → 학습 → 분석 → 보고서 초안
python -m pytest -q tests           # 누수·계보·분할 검사
```

단계별: `python -m castguard env | prepare | train | analyze | report` · 빠른 점검: `--quick` (seed 1개, 보고용 아님) · 병렬 수: `--jobs 16`

KAMP Note(JupyterLab)에서 실행하는 방법은 [docs/KAMP_GUIDE.md](docs/KAMP_GUIDE.md)를 본다.

## 데이터

`data/raw/`에 KAMP 원본 3종을 둔다 (파일명 그대로).

| 파일 | 데이터 | 역할 |
|---|---|---|
| `DieCasting_Quality_Raw_Data.csv` | #42 주조 품질보증 | 주 데이터 (정답) |
| `DieCasting_Raw_Data.csv` | #41 주조 설비 예지보전 | 보조1: 가동 타임라인·설비상태 → Gate |
| `Investment_Casting.csv` | #40 주조 공정최적화 | 보조2: 타 공장 외부검증·금형온도 가치 |

## 구조

```
castguard/
  prepare.py    원본 → joined/m41_timeline/d40_clean.parquet, folds.csv, 입력계약, 품질지수 (JH 전처리 기반)
  features.py   입력 세트(A0·A·B·FB·A_FB·B_FB)와 검사결과 피드백(지연 반영)
  models.py     후보: 로지스틱·RF·LightGBM·CatBoost·XGBoost·앙상블
  train.py      품질·Gate·유형·#40 실험 (선택은 validation으로만)
  analysis.py   Ablation·실패조건·조건별 오류·SHAP·상호작용·KPI·비용·운전창·제출 예측
  report.py     reports/REPORT_DRAFT.md 자동 작성
configs/castguard.json   seed·지연·임계값·모델 설정
tests/                   누수(피드백·이력 미래 참조), 1:1 조인, 분할 순서, 에피소드 비분할
reports/tables, figures  결과 표·그림 (코드가 생성)
outputs/predictions/test_predictions.csv   제출용 test 예측결과
```

## 산출물 읽는 순서

1. `reports/REPORT_DRAFT.md` — 공고문 6개 평가항목 순서의 보고서 초안
2. `reports/tables/ablation.csv`, `model_comparison.csv`, `ablation_decisions.json` — 베이스라인·전후비교·선정근거
3. `reports/tables/failure_conditions.csv`, `error_by_condition.csv` — 실패 조건·조건별 성능
4. `reports/tables/kpi_inspection.csv`, `kpi_cost_sensitivity.csv`, `gate_results.csv` — 현장 KPI
5. `outputs/predictions/test_predictions.csv` — Shot별 위험·유형·Gate·조치

## 브랜치 관계

- `JH`: 팀원의 검증 연구 코드(평가 무결성 감사·대기열 실험 포함). 전처리와 고정 분할은 이 브랜치를 그대로 계승했고,
  `prepare.py` 결과가 JH 산출물과 값 단위로 같음을 확인했다(#42·#41). #40만 시간 정렬 방식을 바로잡았다.
- `add`: 제출용 파이프라인 (이 브랜치).

## 출처

중소벤처기업부, Korea AI Manufacturing Platform(KAMP), 주조 품질보증 / 주조 설비 예지보전 / 주조 공정최적화 AI 데이터셋,
스마트제조혁신추진단, 2022.12.23., www.kamp-ai.kr
