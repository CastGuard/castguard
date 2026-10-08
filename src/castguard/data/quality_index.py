"""데이터 품질 점검 : 열 단위 탐지와 품질지수 요약"""

from collections.abc import Iterable

import pandas as pd



# 결측을 제외하고 값이 1종류 이하인 컬럼
def find_constant_cols(df:pd.DataFrame, cols:Iterable[str] | None = None) -> list[str]:
    cols = df.columns if cols is None else cols
    return [c for c in cols if df[c].nunique(dropna=False) <= 1]


# 품질지수 한 행
def quality_summary(
    df: pd.DataFrame,
    dataset: str,
    stage: str,
    cols: Iterable[str],
    invalid_rules: Iterable[str] = (),
    consistency: float | None = None,
) -> dict:
    """
    품질지수 한 행

    cols: 평가할 '원본 데이터 컬럼'. id·raw_order·is_* 같은 추가 컬럼은 넣지 않음
    invalid_rules: DataFrame.eval 식 목록. 하나라도 True면 그 행은 의심값
    """

    cols = [c for c in cols if c in df.columns]
    sub = df[cols]

    invalid = pd.Series(False, index=df.index)
    for expr in invalid_rules:
        invalid |= df.eval(expr).fillna(False).astype(bool)

    return {
        "dataset": dataset,
        "stage": stage,
        "row": len(df),
        "cols": len(cols),
        "completeness": round(1 - float(sub.isna().mean().mean()), 4),
        "uniqueness": round(1 - float(sub.duplicated().mean()), 4),
        "validity": round(1 - float(invalid.mean()), 4),
        "consistency": consistency,
        "n_constant_cols": len(find_constant_cols(sub)),
    }
