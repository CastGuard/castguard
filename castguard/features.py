"""입력 변수 세트와 '검사결과 피드백' 변수.

검사 피드백(fb_*): 현장은 모든 Shot을 사후 육안검사한다(As-Is). 그 결과는 생산보다 늦게
도착하므로, Shot t의 예측에는 같은 가동구간에서 t-delay 이전 Shot의 검사결과만 쓴다.
delay(기본 20 Shot ≈ Type1 7분 · Type2 12분)는 설정값이며 민감도 분석으로 함께 보고한다.
"""
import numpy as np
import pandas as pd

FB_PREFIX = "fb_"


def _since_last(values: np.ndarray) -> np.ndarray:
    out = np.full(len(values), np.nan)
    last = None
    for i, v in enumerate(values):
        if v == 1:
            last = i
        if last is not None:
            out[i] = i - last
    return out


def add_feedback(df: pd.DataFrame, delay: int, windows=(20, 50, 100), halflife: float = 15,
                 label: str = "y_defect", run_col: str = "run_id", order_col: str = "source_row") -> pd.DataFrame:
    """delay Shot 이전까지의 검사결과로 최근 불량률·지수평균·마지막 불량 이후 경과를 만든다."""
    out = df.sort_values([run_col, order_col], kind="stable").copy()
    known = out.groupby(run_col)[label].shift(delay)            # delay 이전 Shot의 결과만 '알려진' 값
    g = known.groupby(out[run_col])
    for w in windows:
        out[f"{FB_PREFIX}rate{w}"] = g.transform(lambda s, w=w: s.rolling(w, min_periods=1).mean())
    out[f"{FB_PREFIX}ewm"] = g.transform(lambda s: s.ewm(halflife=halflife, ignore_na=True).mean())
    out[f"{FB_PREFIX}since_defect"] = g.transform(lambda s: pd.Series(_since_last(s.to_numpy()), index=s.index))
    out[f"{FB_PREFIX}known_count"] = g.transform(lambda s: s.notna().cumsum()).astype(float)
    return out.loc[df.index]


def feedback_columns(windows=(20, 50, 100)) -> list[str]:
    return [f"{FB_PREFIX}rate{w}" for w in windows] + [f"{FB_PREFIX}ewm", f"{FB_PREFIX}since_defect", f"{FB_PREFIX}known_count"]


def quality_feature_sets(contract: dict, windows) -> dict[str, list[str]]:
    """Ablation 실험별 입력. 이름은 보고서 표와 같다."""
    fb = feedback_columns(windows)
    return {
        "A0": contract["q42_A0"],                  # 공정 14 (베이스라인)
        "A": contract["q42_A"],                    # + 센서 6 + 제품 + 구간 내 순번 (주 데이터 전체)
        "B": contract["q42_B"],                    # A + #41 가동이력 4 (보조 데이터 효과)
        "FB": fb,                                  # 검사결과 피드백 단독
        "A_FB": contract["q42_A"] + fb,            # 주 데이터 + 피드백
        "B_FB": contract["q42_B"] + fb,            # 주 + 보조 + 피드백
    }


def is_forbidden(name: str, contract: dict) -> bool:
    from fnmatch import fnmatchcase
    return any(fnmatchcase(name, pat) for pat in contract["target_columns"] + contract["forbidden"])
