"""Registered four-combination study; source and target transforms fit train only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed, parallel_config
from threadpoolctl import threadpool_limits

from .data import attach_roles, digest, read_inputs
from .models import build_model
from .oct06_research import FB, fit_candidate, metrics, prepare_frames, write_json


class TrainECDF:
    """Deterministic mid-rank ECDF with train-only median imputation."""

    def fit(self, x):
        a = np.asarray(x, float)
        if a.ndim != 2 or not len(a) or np.isinf(a).any():
            raise ValueError('invalid fit matrix')
        if np.isnan(a).all(axis=0).any():
            raise ValueError('source mapping contains an entirely missing train column')
        self.medians_ = np.nanmedian(a, axis=0)
        self.sorted_ = np.sort(np.where(np.isnan(a), self.medians_, a), axis=0)
        return self

    def transform(self, x):
        a = np.asarray(x, float)
        if a.ndim != 2 or a.shape[1] != len(self.medians_) or np.isinf(a).any():
            raise ValueError('invalid transform matrix')
        a = np.where(np.isnan(a), self.medians_, a)
        return np.column_stack([
            (np.searchsorted(self.sorted_[:, j], a[:, j], side='left') +
             np.searchsorted(self.sorted_[:, j], a[:, j], side='right')) / (2 * len(self.sorted_))
            for j in range(a.shape[1])
        ])


def checkpoint(out, scheme, fold, rep, model, seed):
    return out/'models'/f'{scheme}__{fold}__{rep}__{model}__{seed}'


def run(root, output, jobs=4, reproduction=False):
    root, out = Path(root), Path(output)
    if out.exists():
        raise FileExistsError('Use a new output path; prior runs are immutable')
    cfg = json.loads((root/'configs/oct08_fusion.json').read_text(encoding='utf-8'))
    out.mkdir(parents=True)
    registered = ['configs/oct08_fusion.json', 'docs/OCT08_FUSION_PROTOCOL.md',
                  'castguard/oct08_fusion.py', 'castguard/oct06_research.py', 'castguard/models.py', 'castguard/data.py']
    registered += [str(p.relative_to(root)).replace('\\', '/') for p in (root/'data/processed').iterdir() if p.is_file()]
    write_json(out/'registration.json', {'registered_at': datetime.now(timezone.utc).isoformat(),
        'hashes': {p: digest(root/p) for p in registered}, 'config': cfg,
        'test_used_for_selection': False, 'independent_validation': False,
        'reader_replacement': False, 'computational_reproduction': reproduction})
    start = time.monotonic()
    deadline = datetime.fromisoformat(cfg['deadline_kst'])
    def state(status, **extra):
        write_json(out/'run_state.json', {'status': status, 'elapsed_seconds': time.monotonic()-start, **extra})
    def timecheck():
        if time.monotonic()-start >= 2700 or (not reproduction and datetime.now(timezone.utc) >= deadline):
            state('stopped_deadline')
            raise TimeoutError('Registered 21:30 KST deadline reached')
    timecheck()
    inputs, folds, _ = read_inputs(root)
    source = attach_roles(inputs['p40'], folds, 'p40', 'chronological', 'primary')
    source = source[source.normal_pressure & source.y_defect.notna()].copy()
    mapping = cfg['mapping']
    train = source[source.role == 'train']
    tx = TrainECDF().fit(train[list(mapping)])
    source_models, source_metrics = {}, []
    (out/'source').mkdir()
    state('source_training')
    with threadpool_limits(limits=1):
        for seed in cfg['seeds']:
            timecheck()
            model = build_model('random_forest', seed, cfg['models']['random_forest'])
            model.fit(tx.transform(train[list(mapping)]), train.y_defect.astype(int))
            source_models[seed] = model
            val = source[source.role == 'validation']
            pv = model.predict_proba(tx.transform(val[list(mapping)]))[:, 1]
            threshold = float(np.nextafter(np.quantile(pv, .8), np.inf))
            for role in ['validation', 'test']:
                g = source[source.role == role]
                p = model.predict_proba(tx.transform(g[list(mapping)]))[:, 1]
                source_metrics.append({'seed': seed, 'role': role, **metrics(g.y_defect, p, threshold, g.row_id)})
            joblib.dump({'model': model, 'transform': tx, 'mapping': mapping}, out/'source'/f'{seed}.joblib', compress=3)
    pd.DataFrame(source_metrics).to_csv(out/'source_metrics.csv', index=False)
    frames, sets = prepare_frames(root, cfg)
    sets.update({'S_T': sets['S']+['transfer_score'], 'SH_T': sets['SH']+['transfer_score'],
                 'S_T_FB': sets['S']+['transfer_score']+FB, 'SH_T_FB': sets['SH']+['transfer_score']+FB})
    seeded_frames, tasks, audit, transferred = {}, [], [], []
    for (scheme, fold), frame in frames.items():
        target_tx = TrainECDF().fit(frame.loc[frame.role == 'train', list(mapping.values())])
        joblib.dump(target_tx, out/'source'/f'target_ecdf_{scheme}_{fold}.joblib')
        for role, part in frame[frame.role != 'excluded'].groupby('role'):
            audit.append({'scheme': scheme, 'fold': fold, 'role': role, 'n': len(part), 'positive': int(part.y_defect.sum())})
        for seed in cfg['seeds']:
            f = frame.copy()
            f['transfer_score'] = source_models[seed].predict_proba(target_tx.transform(f[list(mapping.values())]))[:, 1]
            seeded_frames[(scheme, fold, seed)] = f
            a = f[['row_id', 'run_id', 'role', 'y_defect', 'transfer_score']].copy()
            a['scheme'], a['fold'], a['seed'] = scheme, fold, seed
            transferred.append(a)
            for rep in cfg['representations']:
                for name in cfg['models']:
                    tasks.append((f, sets[rep], name, seed, cfg, checkpoint(out, scheme, fold, rep, name, seed),
                                  {'scheme': scheme, 'fold': fold, 'representation': rep}))
    if len(tasks) != cfg['max_target_fits']:
        raise ValueError('Unexpected candidate count')
    write_json(out/'sample_audit.json', audit)
    pd.concat(transferred, ignore_index=True).to_parquet(out/'transfer_predictions.parquet', index=False)
    rows = []
    with parallel_config(backend='loky', inner_max_num_threads=1):
        stream = Parallel(n_jobs=jobs, return_as='generator_unordered')(delayed(fit_candidate)(*args) for args in tasks)
        for i, row in enumerate(stream, 1):
            rows.append(row)
            if i % 12 == 0:
                print(f'validation fits {i}/{len(tasks)}, elapsed {time.monotonic()-start:.1f}s', flush=True)
                state('validation', completed=i, total=len(tasks))
            timecheck()
    validation = pd.DataFrame(rows).sort_values(['scheme', 'fold', 'representation', 'model', 'seed'])
    validation.to_csv(out/'validation_metrics.csv', index=False)
    write_json(out/'validation_seal.json', {'sealed_at': datetime.now(timezone.utc).isoformat(),
        'sha256': digest(out/'validation_metrics.csv'), 'rule': 'All preregistered models retained; RF primary, logistic sensitivity',
        'test_used_for_selection': False, 'reader_replacement': False})
    print('Validation sealed; evaluating reused test for every fixed candidate', flush=True)
    evaluated, predictions = [], []
    with threadpool_limits(limits=1):
        for row in validation.to_dict('records'):
            timecheck()
            scheme, fold, rep, name, seed = [row[k] for k in ['scheme', 'fold', 'representation', 'model', 'seed']]
            payload = joblib.load(checkpoint(out, scheme, fold, rep, name, seed)/'model.joblib')
            f = seeded_frames[(scheme, fold, seed)]
            for role in ['validation', 'test']:
                g = f[f.role == role]
                p = payload['model'].predict_proba(g[payload['features']])[:, 1]
                ident = dict(scheme=scheme, fold=fold, representation=rep, model=name, seed=seed, role=role)
                evaluated.append({**ident, **metrics(g.y_defect, p, payload['threshold'], g.row_id)})
                part = g[['row_id', 'run_id', 'y_defect']].copy()
                for k, v in ident.items():
                    part[k] = v
                part['probability'], part['threshold'] = p, payload['threshold']
                predictions.append(part)
    pd.DataFrame(evaluated).to_csv(out/'metrics.csv', index=False)
    pd.concat(predictions, ignore_index=True).to_parquet(out/'predictions.parquet', index=False)
    summarize(out, cfg)
    reg = json.loads((out/'registration.json').read_text(encoding='utf-8'))
    if any(digest(root/p) != h for p, h in reg['hashes'].items()):
        raise ValueError('Registered inputs changed during execution')
    state('completed', target_fits=len(tasks), source_fits=len(source_models), completed_at=datetime.now(timezone.utc).isoformat())


def summarize(out, cfg):
    from sklearn.metrics import average_precision_score
    out = Path(out)
    m = pd.read_csv(out/'metrics.csv', dtype={'fold': str})
    keys = ['scheme', 'fold', 'representation', 'model', 'role']
    summary = m.groupby(keys).agg(n=('n','first'), positive=('positive','first'),
        ap=('ap','mean'), ap_seed_sd=('ap','std'), auc=('auc','mean'), capture20=('capture20','mean'),
        caught20=('caught20','mean'), inspect20=('inspect20','first'), fpr=('fpr','mean')).reset_index()
    summary.to_csv(out/'summary.csv', index=False)
    comparisons = []
    for suffix in ['', '_FB']:
        for added, base in [('S_T','S'), ('SH_T','SH'), ('SH','S'), ('SH_T','S_T')]:
            a = m[m.representation == added+suffix]
            b = m[m.representation == base+suffix]
            paired = a.merge(b, on=['scheme','fold','model','seed','role'], suffixes=('_a','_b'), validate='one_to_one')
            for r in paired.to_dict('records'):
                assert r['n_a'] == r['n_b'] and r['positive_a'] == r['positive_b']
                comparisons.append({**{k:r[k] for k in ['scheme','fold','model','seed','role']},
                    'added':added+suffix, 'base':base+suffix, 'ap_gain':r['ap_a']-r['ap_b'],
                    'capture20_gain':r['capture20_a']-r['capture20_b']})
    c = pd.DataFrame(comparisons)
    c.to_csv(out/'paired_comparisons.csv', index=False)
    decisions = []
    for (model, added, base), g in c[c.role == 'validation'].groupby(['model','added','base']):
        w = g[g.scheme == 'within_run'][['ap_gain','capture20_gain']].mean()
        f = g[g.scheme == 'forward_run'].groupby('fold')[['ap_gain','capture20_gain']].mean()
        nonnegative = int(((f.ap_gain >= 0) & (f.capture20_gain >= 0)).sum())
        decisions.append({'model':model, 'added':added, 'base':base, 'validation_ap_gain':w.ap_gain,
            'validation_capture20_gain':w.capture20_gain, 'nonnegative_forward_validation_folds':nonnegative,
            'criterion_met':bool(w.ap_gain >= .02 and w.capture20_gain >= .05 and nonnegative >= 2)})
    write_json(out/'decisions.json', decisions)
    pred = pd.read_parquet(out/'predictions.parquet')
    pred = pred[(pred.scheme == 'within_run') & (pred.role == 'test')]
    uncertainty = []
    for d in decisions:
        a = pred[(pred.model == d['model']) & (pred.representation == d['added'])]
        b = pred[(pred.model == d['model']) & (pred.representation == d['base'])]
        pair = a.merge(b, on=['row_id','seed'], suffixes=('_a','_b'), validate='one_to_one')
        assert (pair.y_defect_a == pair.y_defect_b).all()
        runs = sorted(pair.run_id_a.unique())
        rng = np.random.default_rng(cfg['bootstrap_seed'])
        values = []
        groups = {int(seed): {r: part[part.run_id_a == r] for r in runs} for seed, part in pair.groupby('seed')}
        for _ in range(cfg['bootstrap_repetitions']):
            chosen = rng.choice(runs, size=len(runs), replace=True)
            diffs = []
            for blocks in groups.values():
                sample = pd.concat([blocks[r] for r in chosen], ignore_index=True)
                if sample.y_defect_a.nunique() == 2:
                    diffs.append(average_precision_score(sample.y_defect_a, sample.probability_a) -
                                 average_precision_score(sample.y_defect_b, sample.probability_b))
            if diffs:
                values.append(float(np.mean(diffs)))
        uncertainty.append({'model':d['model'], 'added':d['added'], 'base':d['base'], 'runs':len(runs),
            'resamples':len(values), 'ap_gain_low':float(np.quantile(values,.025)), 'ap_gain_high':float(np.quantile(values,.975))})
    write_json(out/'uncertainty.json', uncertainty)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='reports/oct08_fusion')
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--reproduction', action='store_true', help='Replay fixed configuration after the competition date (45 minute cap)')
    args = p.parse_args()
    run(Path.cwd(), args.output, args.jobs, args.reproduction)
