"""All learned transforms are fitted on train only."""
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def build_model(name, seed, parameters):
    steps = [("impute", SimpleImputer(strategy="median", keep_empty_features=True).set_output(transform="pandas"))]
    if name == "logistic":
        steps.append(("scale", StandardScaler()))
        model = LogisticRegression(random_state=seed, **parameters)
    elif name == "random_forest":
        model = RandomForestClassifier(random_state=seed, n_jobs=1, **parameters)
    elif name == "lightgbm":
        model = LGBMClassifier(random_state=seed, n_jobs=1, verbosity=-1, deterministic=True, force_col_wise=True, **parameters)
    elif name == "catboost":
        model = CatBoostClassifier(random_seed=seed, thread_count=1, verbose=False, allow_writing_files=False, **parameters)
    else:
        raise ValueError(name)
    return Pipeline(steps + [("model", model)])
