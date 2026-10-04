"""평가 지표와 validation 전용 임계값 (JH 브랜치 metrics.py 기반)."""
import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score


def _arrays(y, p):
    y, p = np.asarray(y).astype(int), np.asarray(p, dtype=float)
    if len(y) != len(p) or not np.isfinite(p).all():
        raise ValueError("잘못된 예측값")
    return y, p


def threshold_f1(y, p) -> float:
    y, p = _arrays(y, p)
    if len(np.unique(y)) < 2:
        return 0.5
    precision, recall, thr = precision_recall_curve(y, p)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-15)
    return float(thr[np.flatnonzero(f1 == f1.max())[-1]])


def threshold_max_fpr(y, p, max_fpr: float) -> float:
    """정상 표본의 오경보율이 max_fpr 이하가 되는 가장 낮은 임계값."""
    y, p = _arrays(y, p)
    neg = np.sort(p[y == 0])[::-1]
    if not len(neg):
        return float(np.nextafter(1.0, np.inf))
    return float(np.nextafter(neg[int(np.floor(max_fpr * len(neg)))], np.inf))


def threshold_rate(p, rate: float) -> float:
    """validation에서 상위 rate 비율이 경보가 되는 임계값 (검사율 정책)."""
    p = np.asarray(p, dtype=float)
    return float(np.quantile(p, 1 - rate)) if len(p) else 1.0


def ece(y, p, bins: int = 10) -> float:
    y, p = _arrays(y, p)
    b = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum(abs(y[b == i].mean() - p[b == i].mean()) * (b == i).mean() for i in range(bins) if (b == i).any()))


def score(y, p, threshold: float = 0.5) -> dict:
    y, p = _arrays(y, p)
    if not len(y):
        return {"n": 0}
    pred = p >= threshold
    tp, fp = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum())
    fn, tn = int((~pred & (y == 1)).sum()), int((~pred & (y == 0)).sum())
    both = len(np.unique(y)) == 2
    return {"n": len(y), "positive": int(y.sum()), "prevalence": float(y.mean()),
            "roc_auc": float(roc_auc_score(y, p)) if both else np.nan,
            "average_precision": float(average_precision_score(y, p)) if both else np.nan,
            "ap_lift": float(average_precision_score(y, p) / y.mean()) if both else np.nan,
            "brier": float(brier_score_loss(y, p)), "ece": ece(y, p), "threshold": threshold,
            "alarm_rate": float(pred.mean()), "recall": tp / (tp + fn) if tp + fn else np.nan,
            "precision": tp / (tp + fp) if tp + fp else np.nan, "fpr": fp / (fp + tn) if fp + tn else np.nan,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn}
