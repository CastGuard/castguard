"""후보 모델. 결측 대체·스케일링은 파이프라인 안에서 train fold에만 fit된다."""
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

TREE_MODELS = {"random_forest", "lightgbm", "catboost", "xgboost"}


def build_model(name: str, seed: int, params: dict, use_gpu: bool = False):
    steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True))]
    if name == "logistic":
        steps.append(("scale", StandardScaler()))
        model = LogisticRegression(random_state=seed, **params)
    elif name == "random_forest":
        model = RandomForestClassifier(random_state=seed, n_jobs=1, **params)
    elif name == "lightgbm":
        from lightgbm import LGBMClassifier
        model = LGBMClassifier(random_state=seed, n_jobs=1, verbosity=-1, deterministic=True, force_col_wise=True, **params)
    elif name == "catboost":
        from catboost import CatBoostClassifier
        extra = {"task_type": "GPU"} if use_gpu else {"thread_count": 1}
        model = CatBoostClassifier(random_seed=seed, verbose=False, allow_writing_files=False, **extra, **params)
    elif name == "xgboost":
        from xgboost import XGBClassifier
        extra = {"device": "cuda"} if use_gpu else {"n_jobs": 1}
        model = XGBClassifier(random_state=seed, tree_method="hist", eval_metric="logloss", **extra, **params)
    else:
        raise ValueError(name)
    return Pipeline(steps + [("model", model)])


class Ensemble:
    """멤버 모델 확률의 단순 평균 (가중치 학습 없음 → 추가 과적합 없음)."""

    def __init__(self, members: list[str], seed: int, params: dict, use_gpu: bool = False):
        self.models = [build_model(m, seed, params[m], use_gpu) for m in members]

    def fit(self, X, y):
        for m in self.models:
            m.fit(X, y)
        return self

    def predict_proba(self, X):
        p = np.mean([m.predict_proba(X)[:, 1] for m in self.models], axis=0)
        return np.column_stack([1 - p, p])


def make(name: str, seed: int, cfg: dict, params: dict | None = None):
    """name은 후보 이름. params를 주면 설정의 하이퍼파라미터 대신 사용한다(탐색 결과 채택 시)."""
    if name == "ensemble":
        return Ensemble(cfg["ensemble_members"], seed, cfg["candidate_models"], cfg["use_gpu"])
    return build_model(name, seed, params if params is not None else cfg["candidate_models"][name], cfg["use_gpu"])
