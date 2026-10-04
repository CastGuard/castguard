"""폴더 구조. 경로는 여기서만 정의한다 (표준 라이브러리만 사용)."""
import os
from pathlib import Path

ROOT = Path(os.environ.get("CASTGUARD_ROOT", Path(__file__).resolve().parents[1]))
CONFIG = ROOT / "configs" / "castguard.json"

RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
RAW_Q42 = RAW / "DieCasting_Quality_Raw_Data.csv"
RAW_M41 = RAW / "DieCasting_Raw_Data.csv"
RAW_D40 = RAW / "Investment_Casting.csv"

JOINED = PROCESSED / "joined.parquet"
M41 = PROCESSED / "m41_timeline.parquet"
P40 = PROCESSED / "d40_clean.parquet"
FOLDS = PROCESSED / "folds.csv"
CONTRACT = PROCESSED / "feature_contract.json"

OUTPUTS = ROOT / "outputs"
RUNS = OUTPUTS / "runs"                   # 학습 결과(지표·예측) 캐시
MODELS = OUTPUTS / "models"
PREDICTIONS = OUTPUTS / "predictions"
TABLES = ROOT / "reports" / "tables"
FIGURES = ROOT / "reports" / "figures"
REPORT = ROOT / "reports" / "REPORT_DRAFT.md"


def ensure_dirs() -> None:
    for p in (PROCESSED, RUNS, MODELS, PREDICTIONS, TABLES, FIGURES):
        p.mkdir(parents=True, exist_ok=True)
