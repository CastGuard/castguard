"""Metrics and validation-only decision thresholds."""
import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score


def binary_inputs(y, probability):
    y, p = np.asarray(y), np.asarray(probability, dtype=float)
    if y.ndim != 1 or p.ndim != 1 or len(y) != len(p):
        raise ValueError("Labels and probabilities must be equal-length one-dimensional arrays")
    if not np.isin(y, [0, 1]).all():
        raise ValueError("Labels must be binary 0/1 with no missing values")
    if not np.isfinite(p).all() or np.any((p < 0) | (p > 1)):
        raise ValueError("Invalid predictions")
    return y.astype(int), p


def choose_threshold(y, probability, max_fpr=None):
    y, p = binary_inputs(y, probability)
    if not len(y):
        raise ValueError("Validation partition is empty")
    if max_fpr is not None:
        if not 0 <= max_fpr < 1:
            raise ValueError("max_fpr must be in [0, 1)")
        negatives = np.sort(p[y == 0])[::-1]
        if not len(negatives):
            # No evidence to bound false stops: hold all alarms for this fold.
            return float(np.nextafter(1.0, np.inf))
        allowed = int(np.floor(max_fpr * len(negatives)))
        return float(np.nextafter(negatives[allowed], np.inf))
    if len(np.unique(y)) < 2:
        return 0.5
    precision, recall, thresholds = precision_recall_curve(y, p)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-15)
    # Prefer the highest threshold when scores tie.
    return float(thresholds[np.flatnonzero(f1 == f1.max())[-1]])


def score(y, probability, threshold=0.5):
    y, p = binary_inputs(y, probability)
    if not np.isfinite(threshold):
        raise ValueError("Threshold must be finite")
    if not len(y):
        return {"n": 0, "positive": 0, **{k: np.nan for k in ["prevalence", "roc_auc", "average_precision", "brier", "ece", "recall", "fpr", "precision", "fnr"]}, **{k: 0 for k in ["tp", "fp", "tn", "fn"]}}
    pred = p >= threshold
    tp = int(((y == 1) & pred).sum())
    fp = int(((y == 0) & pred).sum())
    tn = int(((y == 0) & ~pred).sum())
    fn = int(((y == 1) & ~pred).sum())
    bins = np.minimum((p * 10).astype(int), 9)
    ece = sum(abs(y[bins == b].mean() - p[bins == b].mean()) * (bins == b).mean() for b in range(10) if (bins == b).any())
    both = len(np.unique(y)) == 2
    return {"n": len(y), "positive": int(y.sum()), "prevalence": float(y.mean()),
            "roc_auc": float(roc_auc_score(y, p)) if both else np.nan,
            "average_precision": float(average_precision_score(y, p)) if both else np.nan,
            "brier": float(brier_score_loss(y, p)), "ece": float(ece),
            "recall": tp / (tp + fn) if tp + fn else np.nan,
            "fnr": fn / (tp + fn) if tp + fn else np.nan,
            "fpr": fp / (fp + tn) if fp + tn else np.nan,
            "precision": tp / (tp + fp) if tp + fp else 0.0,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn}
