import os
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(os.environ.get("CASTGUARD_ROOT", Path(__file__).resolve().parents[3]))

# utf-8-sig : BOM(\ufeff)을 자동 제거, 일반 utf-8도 읽음
_ENCODINGS = ("utf-8-sig", "cp949")


# ── 설정 ───────────────────────────────────────────
def load_config(path: str | Path = "configs/base.yaml") -> dict:
    """yaml을 읽고 paths의 상대경로를 레포 루트 기준 Path로 바꾼다."""
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["paths"] = {k: ROOT / v for k, v in cfg["paths"].items()}
    return cfg


# ── 내부 도우미 ─────────────────────────────────────
def _read_csv(path: Path, **kwargs) -> pd.DataFrame:
    last_err = None
    for enc in _ENCODINGS:
        try:
            return pd.read_csv(path, encoding=enc, **kwargs)
        except UnicodeDecodeError as e:
            last_err = e
    raise last_err


def _strip_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    return out


def _require(df: pd.DataFrame, cols: set, name: str) -> None:
    missing = cols - set(df.columns)
    if missing:
        raise ValueError(f"[{name}] 필수 컬럼 없음: {sorted(missing)}")


# ── 원본 로더 ───────────────────────────────────────
def load_q42(path: Path) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """#42: 2줄 헤더를 1줄로 펴고, 그룹(Process/Sensor/Defects) 목록을 따로 돌려준다."""
    raw = _read_csv(path, header=[0, 1])
    lvl0 = pd.Series(raw.columns.get_level_values(0), dtype=str).str.strip()
    lvl1 = pd.Series(raw.columns.get_level_values(1), dtype=str).str.strip()
    lvl0 = lvl0.where(~lvl0.str.startswith("Unnamed")).ffill()

    df = raw.copy()
    df.columns = lvl1.tolist()
    if df.columns.duplicated().any():
        raise ValueError(f"[q42] 중복 컬럼: {df.columns[df.columns.duplicated()].tolist()}")

    col_groups = {g: lvl1[lvl0 == g].tolist() for g in lvl0.unique()}
    if set(col_groups) != {"Process", "Sensor", "Defects"}:
        raise ValueError(f"[q42] 예상과 다른 그룹 이름: {list(col_groups)}")
    _require(df, {"id", "Shot", "Product_Type"}, "q42")
    return df, col_groups


def load_m41(path: Path) -> pd.DataFrame:
    df = _strip_columns(_read_csv(path))
    _require(df, {"Shot", "Machine_Status", "_id"}, "m41")
    return df


def load_d40(path: Path) -> pd.DataFrame:
    df = _strip_columns(_read_csv(path))
    _require(df, {"timestamp", "date", "PassOrFail"}, "d40")
    return df