"""10/8 time-window aggregation study (#41 timeline -> #42 quality).

Pre-registered bounded experiment. The competition notice explicitly allows
time-window aggregation / resampling as a linkage technique. Prior studies used
only four hand-made #41 history variables (SH). Here the full #41 timeline
(including rows without quality labels) is summarised over the previous k shots
of the same run, strictly excluding the current shot, and appended to the pure
#42 input S. Models, seeds and folds are the fixed oct06/oct08 settings.
Selection uses train/validation only; test is the already-exposed reuse split.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
import json
import sys

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from castguard.data import read_inputs, attach_roles  # noqa: E402
from castguard.models import build_model  # noqa: E402
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/oct08_window_search'
PROCESS = ['Velocity_1', 'Velocity_2', 'Velocity_3', 'High_Velocity', 'Cylinder_Pressure', 'Rapid_Rise_Time',
           'Biscuit_Thickness', 'Clamping_Force', 'Cycle_Time', 'Pressure_Rise_Time', 'Casting_Pressure',
           'Spray_Time', 'Spray_1_Time', 'Spray_2_Time']
SENSOR = ['Melting_Furnace_Temp', 'Air_Pressure', 'Coolant_Temp', 'Coolant_Pressure', 'Factory_Temp', 'Factory_Humidity']
S = PROCESS + SENSOR + ['Product_Type']
MODELS = {
    'logistic': {'C': 0.3, 'max_iter': 3000},
    'random_forest': {'n_estimators': 300, 'min_samples_leaf': 20, 'max_features': 0.5},
    'lightgbm': {'n_estimators': 300, 'learning_rate': 0.02, 'num_leaves': 7, 'min_child_samples': 40, 'reg_lambda': 5.0,
                 'colsample_bytree': 0.7, 'subsample': 0.8, 'subsample_freq': 1},
    'catboost': {'iterations': 300, 'depth': 4, 'learning_rate': 0.03, 'l2_leaf_reg': 5.0, 'boosting_type': 'Ordered', 'has_time': True},
}
SEEDS = [17, 29, 43]
FOLDS = [('within_run', 'primary'), ('forward_run', '2'), ('forward_run', '3'), ('forward_run', '4'), ('forward_run', '6')]
CRITERIA = {'minimum_validation_ap_gain': 0.02, 'minimum_validation_capture20_gain': 0.05, 'minimum_forward_validation_folds_nondecreasing': 2}


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def window_features(m41):
    """Rolling statistics over the previous k #41 rows of the same run, current row excluded."""
    m = m41.sort_values(['run_id', 'source_row']).copy()
    out = {}
    g = m.groupby('run_id', sort=False)
    for name in PROCESS:
        prev = g[name].shift(1)
        for k in (5, 20):
            roll = prev.groupby(m.run_id).rolling(k, min_periods=1)
            mean = roll.mean().reset_index(level=0, drop=True)
            out[f'w{k}_mean_{name}'] = mean
            if k == 20:
                std = roll.std().reset_index(level=0, drop=True)
                out[f'w{k}_std_{name}'] = std
                out[f'w{k}_dev_{name}'] = m[name] - mean
    prev_missing = g['process_missing'].shift(1).astype(float)
    out['w20_missing_rows'] = prev_missing.groupby(m.run_id).rolling(20, min_periods=1).sum().reset_index(level=0, drop=True)
    prev_status = g['Machine_Status'].shift(1)
    out['w20_warm_rows'] = prev_status.groupby(m.run_id).rolling(20, min_periods=1).sum().reset_index(level=0, drop=True)
    feats = pd.DataFrame(out, index=m.index)
    feats['run_id'] = m.run_id.values
    feats['Shot'] = m.Shot.values
    return feats


def representations(q42, m41):
    feats = window_features(m41)
    frame = q42.merge(feats, on=['run_id', 'Shot'], how='left', validate='one_to_one')
    assert len(frame) == len(q42)
    dev = [c for c in feats.columns if c.startswith('w20_dev_')]
    full = [c for c in feats.columns if c.startswith('w') and c not in ('run_id', 'Shot')]
    sets = {'S': S, 'SWd': S + dev, 'SW': S + full}
    return frame, sets


def capture(y, p, rate=0.2):
    n = int(round(len(y) * rate))
    order = np.argsort(-p, kind='stable')[:n]
    return int(y[order].sum()), n


def metrics(y, p, threshold):
    y = np.asarray(y).astype(int); p = np.asarray(p, float)
    both = len(np.unique(y)) == 2
    pred = p >= threshold
    tp = int(((y == 1) & pred).sum()); fp = int(((y == 0) & pred).sum()); fn = int(((y == 1) & ~pred).sum()); tn = int(((y == 0) & ~pred).sum())
    c20, n20 = capture(y, p, 0.2)
    return dict(n=len(y), positive=int(y.sum()), ap=float(average_precision_score(y, p)) if both else np.nan,
                auc=float(roc_auc_score(y, p)) if both else np.nan, brier=float(brier_score_loss(y, p)), threshold=float(threshold),
                tp=tp, fp=fp, fn=fn, tn=tn, fpr=fp / (fp + tn) if fp + tn else np.nan,
                inspect20=n20, caught20=c20, capture20=c20 / y.sum() if y.sum() else np.nan)


def fit_one(frame, folds, sets, rep, model, seed, scheme, fold):
    f = attach_roles(frame, folds, 'q42', scheme, fold)
    cols = sets[rep]
    tr = f[f.role == 'train']; va = f[f.role == 'validation']; te = f[f.role == 'test']
    m = build_model(model, seed, MODELS[model])
    m.fit(tr[cols], tr.y_defect.astype(int))
    pv = m.predict_proba(va[cols])[:, 1]; pt = m.predict_proba(te[cols])[:, 1]
    threshold = float(np.nextafter(np.quantile(pv, 0.8), np.inf))
    rows = []
    for role, part, p in (('validation', va, pv), ('test', te, pt)):
        rows.append(dict(representation=rep, model=model, seed=seed, scheme=scheme, fold=fold, role=role, **metrics(part.y_defect.values, p, threshold)))
    preds = pd.DataFrame(dict(representation=rep, model=model, seed=seed, scheme=scheme, fold=fold, role='test', row_id=te.row_id.values, y=te.y_defect.values, p=pt))
    return rows, preds


def block_bootstrap(preds_a, preds_b, runs, reps=1000, seed=20261008):
    rng = np.random.default_rng(seed)
    a = preds_a.set_index('row_id'); b = preds_b.set_index('row_id').loc[a.index]
    run = runs.loc[a.index].values
    uniq = np.unique(run)
    diffs = []
    for _ in range(reps):
        pick = rng.choice(uniq, len(uniq), replace=True)
        idx = np.concatenate([np.flatnonzero(run == r) for r in pick])
        y = a.y.values[idx]
        if len(np.unique(y)) < 2:
            continue
        diffs.append(average_precision_score(y, b.p.values[idx]) - average_precision_score(y, a.p.values[idx]))
    return [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))], len(diffs)


def main(jobs=16):
    OUT.mkdir(parents=True, exist_ok=False)
    frames, folds, contract = read_inputs(ROOT)
    frame, sets = representations(frames['q42'], frames['m41'])
    forbidden = set(contract['target_columns'] + contract['forbidden'])
    for rep, cols in sets.items():
        assert not (set(cols) & forbidden) and len(cols) == len(set(cols)), rep
    registration = dict(at=datetime.now(timezone(timedelta(hours=9))).isoformat(),
        hypothesis='Time-window aggregation of the full #41 timeline (previous 5/20 shots, current shot excluded) adds quality value to pure #42 input S.',
        baseline='S: 21 current #42 features; fixed oct06 model settings; no feedback.',
        representations={k: len(v) for k, v in sets.items()}, models=MODELS, seeds=SEEDS, folds=FOLDS, criteria=CRITERIA,
        selection='validation only (mean over 3 seeds); test evaluated once after decisions are written; no reselection on test',
        test_exposure='reused, already-exposed split; exploratory, not independent validation',
        input_hashes={p.name: digest(p) for p in (ROOT / 'data/processed').iterdir() if p.is_file()},
        submission_hashes={p.name: digest(p) for p in (ROOT / 'submission').iterdir() if p.is_file()})
    (OUT / 'registration.json').write_text(json.dumps(registration, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'feature_sets.json').write_text(json.dumps(sets, ensure_ascii=False, indent=2), encoding='utf-8')
    tasks = [(rep, model, seed, scheme, fold) for rep in sets for model in MODELS for seed in SEEDS for scheme, fold in FOLDS]
    results = Parallel(n_jobs=jobs)(delayed(fit_one)(frame, folds, sets, *t) for t in tasks)
    rows = [r for rr, _ in results for r in rr]
    preds = pd.concat([p for _, p in results], ignore_index=True)
    metrics_df = pd.DataFrame(rows)
    metrics_df.to_csv(OUT / 'metrics.csv', index=False)
    preds.to_parquet(OUT / 'test_predictions.parquet', index=False)
    mean = metrics_df.groupby(['representation', 'model', 'scheme', 'fold', 'role'], as_index=False)[['ap', 'auc', 'capture20', 'fpr', 'caught20']].mean()
    mean.to_csv(OUT / 'seed_mean.csv', index=False)
    # Validation decisions (written before test is examined)
    decisions = []
    for model in MODELS:
        base = mean[(mean.representation == 'S') & (mean.model == model) & (mean.role == 'validation')].set_index(['scheme', 'fold'])
        for rep in ('SWd', 'SW'):
            cand = mean[(mean.representation == rep) & (mean.model == model) & (mean.role == 'validation')].set_index(['scheme', 'fold'])
            w = ('within_run', 'primary')
            ap_gain = float(cand.loc[w, 'ap'] - base.loc[w, 'ap']); cap_gain = float(cand.loc[w, 'capture20'] - base.loc[w, 'capture20'])
            fwd = [(f, float(cand.loc[('forward_run', f), 'ap'] - base.loc[('forward_run', f), 'ap']),
                    float(cand.loc[('forward_run', f), 'capture20'] - base.loc[('forward_run', f), 'capture20'])) for f in ['2', '3', '4', '6']]
            consistent = sum(1 for _, a, c in fwd if a >= 0 and c >= 0)
            decisions.append(dict(model=model, representation=rep, validation_within_ap=float(cand.loc[w, 'ap']), baseline_within_ap=float(base.loc[w, 'ap']),
                validation_ap_gain=ap_gain, validation_capture20_gain=cap_gain, forward_gains=fwd, forward_consistent=consistent,
                qualifies=bool(ap_gain >= CRITERIA['minimum_validation_ap_gain'] and cap_gain >= CRITERIA['minimum_validation_capture20_gain']
                               and consistent >= CRITERIA['minimum_forward_validation_folds_nondecreasing'])))
    (OUT / 'decisions.json').write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding='utf-8')
    # Validation-selected best (representation, model) by within validation AP, sealed before test table
    val = mean[(mean.role == 'validation') & (mean.scheme == 'within_run')].sort_values(['ap', 'representation', 'model'], ascending=[False, True, True])
    best = val.iloc[0]
    seal = dict(selected_representation=best.representation, selected_model=best.model, validation_within_ap=float(best.ap), rule='highest within validation AP, 3-seed mean')
    (OUT / 'selection_seal.json').write_text(json.dumps(seal, ensure_ascii=False, indent=2), encoding='utf-8')
    # Test table and uncertainty
    test = mean[mean.role == 'test']
    test.to_csv(OUT / 'test_seed_mean.csv', index=False)
    q = frames['q42'].set_index('row_id')
    runs = q.run_id
    unc = []
    for model in MODELS:
        for rep in ('SWd', 'SW'):
            pa = preds[(preds.representation == 'S') & (preds.model == model) & (preds.scheme == 'within_run')].groupby('row_id', as_index=False).agg(y=('y', 'first'), p=('p', 'mean'))
            pb = preds[(preds.representation == rep) & (preds.model == model) & (preds.scheme == 'within_run')].groupby('row_id', as_index=False).agg(y=('y', 'first'), p=('p', 'mean'))
            ci, used = block_bootstrap(pa, pb, runs)
            unc.append(dict(model=model, representation=rep, reference='S', test_ap_diff_interval95=ci, replicates=used))
    (OUT / 'uncertainty.json').write_text(json.dumps(unc, ensure_ascii=False, indent=2), encoding='utf-8')
    within = test[test.scheme == 'within_run'].set_index(['representation', 'model'])
    summary = dict(completed_at_kst=datetime.now(timezone(timedelta(hours=9))).isoformat(), fits=len(tasks), feature_counts={k: len(v) for k, v in sets.items()},
        qualifying_decisions=[d for d in decisions if d['qualifies']], decisions=decisions, selection_seal=seal,
        selected_test=within.loc[(seal['selected_representation'], seal['selected_model'])].to_dict(),
        baseline_logistic_S_test=within.loc[('S', 'logistic')].to_dict(),
        test_within=within.reset_index().to_dict('records'), uncertainty=unc,
        caveat='Reused exposed test; small cohort; window features derive from #41 rows with and without quality labels; no feedback layer; not independent validation.')
    (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding='utf-8')
    print(json.dumps(dict(seal=seal, qualifying=[(d['model'], d['representation']) for d in decisions if d['qualifies']],
                          selected_test=summary['selected_test'], baseline=summary['baseline_logistic_S_test']), ensure_ascii=False, default=float))


if __name__ == '__main__':
    main(jobs=int(sys.argv[1]) if len(sys.argv) > 1 else 16)
