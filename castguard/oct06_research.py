"""Bounded October 6 research. Fixed folds, causal delayed labels, sealed validation selection."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed, parallel_config
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
from threadpoolctl import threadpool_limits
from .data import attach_roles, digest, read_inputs
from .models import build_model

FB = ['fb_rate20', 'fb_rate100', 'fb_ewm', 'fb_known_count']


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False,
                                   default=lambda x: x.item() if hasattr(x, 'item') else str(x)), encoding='utf-8')


def event_frame(q, m):
    """Map to ALL process events, never reindex according to label presence."""
    m = m.sort_values(['run_id', 'source_row'], kind='stable').copy()
    m['event_order'] = m.groupby('run_id').cumcount()
    mapping = m[['run_id', 'source_row', 'event_order']].rename(columns={'source_row': 'source_row_m41'})
    if mapping.duplicated(['run_id', 'source_row_m41']).any():
        raise ValueError('duplicate process event')
    out = q.merge(mapping, on=['run_id', 'source_row_m41'], how='left', validate='many_to_one')
    if out.dropna(subset=['event_order']).duplicated(['run_id', 'event_order']).any():
        raise ValueError('multiple quality records on the same process event')
    return out


def delayed_feedback(frame, delay=20, coverage=1., blocked_roles=()):
    """Prior labels arrive after delay process events; deterministic missing-return scenario."""
    if not isinstance(delay, int) or delay < 1 or not 0 < coverage <= 1:
        raise ValueError('delay>=1 and coverage in (0,1] required')
    result = pd.DataFrame(np.nan, index=frame.index, columns=FB)
    for _, g in frame.dropna(subset=['event_order']).groupby('run_id', sort=False):
        g = g.sort_values('event_order', kind='stable')
        donors = g.loc[~g.role.isin(['excluded', *blocked_roles])].copy()
        keep = donors.row_id.map(lambda v: int(hashlib.sha256(str(v).encode()).hexdigest()[:12], 16) / 16**12 < coverage)
        donors = donors.loc[keep]
        order = donors.event_order.to_numpy(float)
        target = donors.y_defect.to_numpy(float)
        for idx, row in g.iterrows():
            available = order <= row.event_order - delay
            o, y = order[available], target[available]
            values = []
            for width in [20, 100]:
                z = y[o > row.event_order - delay - width]
                values.append(float(z.mean()) if len(z) else np.nan)
            if len(y):
                # event-distance EWMA: missing labels do not compress elapsed event time.
                w = np.exp2(-(row.event_order - delay - o) / 15.)
                ew = float(np.dot(w, y) / w.sum())
            else:
                ew = np.nan
            result.loc[idx] = [*values, ew, len(y)]
    return result


def feature_sets(contract):
    p = contract['q42_A0']
    s = [x for x in contract['q42_A'] if x != 'shot_position']
    h = [x for x in contract['q42_B'] if x not in contract['q42_A']]
    return {'P': p, 'H': p+h, 'S': s, 'SH': s+h, 'FB': FB,
            'S_FB': s+FB, 'SH_FB': s+h+FB}


def metrics(y, p, threshold, ids):
    y, p = np.asarray(y, int), np.asarray(p, float)
    if len(y) == 0 or not np.isfinite(p).all():
        raise ValueError('empty/nonfinite predictions')
    pred = p >= threshold
    out = {'n': len(y), 'positive': int(y.sum()), 'prevalence': float(y.mean()),
           'ap': float(average_precision_score(y, p)) if len(set(y)) == 2 else None,
           'auc': float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
           'brier': float(brier_score_loss(y, p)), 'threshold': float(threshold),
           'tp': int((pred & (y == 1)).sum()), 'fp': int((pred & (y == 0)).sum()),
           'fn': int((~pred & (y == 1)).sum()), 'tn': int((~pred & (y == 0)).sum())}
    out['fpr'] = out['fp']/int((y == 0).sum()) if (y == 0).any() else None
    ranked = np.lexsort((np.asarray(ids).astype(str), -p))
    for rate in [10, 20, 30]:
        k = int(len(y)*rate/100)
        caught = int(y[ranked[:k]].sum())
        out[f'inspect{rate}'] = k
        out[f'caught{rate}'] = caught
        out[f'capture{rate}'] = caught/int(y.sum()) if y.sum() else None
    return out


def model_for(name, seed, cfg):
    if name == 'hist_gradient':
        return HistGradientBoostingClassifier(random_state=seed, **cfg['models'][name])
    return build_model(name, seed, cfg['models'][name])


def fit_candidate(frame, features, name, seed, cfg, folder, identity):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    train, val = frame[frame.role == 'train'], frame[frame.role == 'validation']
    if train.y_defect.nunique() < 2 or val.y_defect.nunique() < 2:
        raise ValueError('insufficient classes')
    model = model_for(name, seed, cfg)
    t = time.monotonic()
    with threadpool_limits(limits=1):
        model.fit(train[features], train.y_defect.astype(int))
        p = model.predict_proba(val[features])[:, 1]
    threshold = float(np.nextafter(np.quantile(p, .8), np.inf))
    row = {**identity, 'model': name, 'seed': seed, 'fit_seconds': time.monotonic()-t,
           **metrics(val.y_defect, p, threshold, val.row_id)}
    joblib.dump({'model': model, 'features': features, 'threshold': threshold,
                 'identity': identity, 'model_name': name, 'seed': seed}, folder/'model.joblib', compress=3)
    write_json(folder/'validation.json', row)
    return row


def prepare_frames(root, cfg):
    frames, folds, contract = read_inputs(root)
    q = event_frame(frames['q42'], frames['m41'])
    sets = feature_sets(contract)
    splits = folds[(folds.dataset == 'q42') & folds.scheme.isin(cfg['schemes'])][['scheme', 'fold']].drop_duplicates()
    out = {}
    for scheme, fold in splits.itertuples(index=False, name=None):
        f = attach_roles(q, folds, 'q42', scheme, str(fold)).sort_values(['run_id', 'event_order'], kind='stable').reset_index(drop=True)
        if f.loc[f.role != 'excluded', 'event_order'].isna().any():
            raise ValueError('eligible quality record missing a process event')
        f[FB] = delayed_feedback(f)
        out[(scheme, str(fold))] = f
    return out, sets


def run(root, output, jobs=4):
    root, out = Path(root), Path(output)
    cfg = json.loads((root/'configs/oct06_research.json').read_text(encoding='utf-8'))
    reg = json.loads((out/'registration.json').read_text(encoding='utf-8'))
    for path, h in reg['hashes'].items():
        if digest(root/path) != h:
            raise ValueError(f'changed registered input: {path}')
    if (out/'selection.json').exists() or (out/'validation_candidates.csv').exists():
        raise FileExistsError('sealed outputs already exist; use a new registered execution')
    start = time.monotonic()
    split_frames, sets = prepare_frames(root, cfg)
    tasks = []
    audit = []
    for (scheme, fold), f in split_frames.items():
        for role, g in f[f.role != 'excluded'].groupby('role'):
            audit.append({'scheme': scheme, 'fold': fold, 'role': role, 'n':len(g),
                          'positive':int(g.y_defect.sum()), 'runs': sorted(g.run_id.unique().tolist()),
                          'products':sorted(g.Product_Type.unique().tolist()),
                          'feedback_available':int((g.fb_known_count > 0).sum())})
        for representation in cfg['representations']:
            ident = {'scheme':scheme, 'fold':fold, 'representation':representation}
            for name in cfg['models']:
                for seed in cfg['seeds']:
                    folder = out/'models'/f'{scheme}__{fold}__{representation}__{name}__{seed}'
                    tasks.append((f, sets[representation], name, seed, cfg, folder, ident))
    write_json(out/'sample_audit.json', audit)
    if len(tasks) > cfg['max_fits']:
        raise ValueError('fit cap exceeded')
    write_json(out/'run_state.json', {'status':'running_validation', 'fits':len(tasks), 'started_at':datetime.now(timezone.utc).isoformat(), 'source_sha256':digest(Path(__file__))})
    results = []
    with parallel_config(backend='loky', inner_max_num_threads=1):
        stream = Parallel(n_jobs=jobs, return_as='generator_unordered')(delayed(fit_candidate)(*x) for x in tasks)
        for i, result in enumerate(stream, 1):
            results.append(result)
            if i % 15 == 0 or i == len(tasks):
                print(f'validation fits {i}/{len(tasks)} elapsed={time.monotonic()-start:.1f}s', flush=True)
                write_json(out/'run_state.json', {'status':'running_validation', 'completed_fits':i, 'total_fits':len(tasks), 'elapsed_seconds':time.monotonic()-start})
            if time.monotonic()-start > cfg['wall_hours_limit']*3600:
                raise TimeoutError('registered wall-time cap')
    table = pd.DataFrame(results).sort_values(['scheme','fold','representation','model','seed'])
    table.to_csv(out/'validation_candidates.csv', index=False)
    selections = []
    for key, g in table.groupby(['scheme','fold','representation'], sort=True):
        rank = g.groupby('model', as_index=False).ap.mean().sort_values(['ap','model'], ascending=[False, True])
        selections.append(dict(zip(['scheme','fold','representation'],key), model=rank.iloc[0]['model'], validation_ap=float(rank.iloc[0].ap)))
    write_json(out/'selection.json', {'sealed_at':datetime.now(timezone.utc).isoformat(), 'rule':cfg['selection'],
               'validation_sha256':digest(out/'validation_candidates.csv'), 'selections':selections,
               'test_used_for_selection':False, 'independent_new_data':False})
    print('Validation selections sealed; beginning reused-test evaluation', flush=True)
    evaluate(root, out, split_frames, sets, cfg, selections)
    write_json(out/'run_state.json', {'status':'completed', 'completed_fits':len(tasks),
               'elapsed_seconds':time.monotonic()-start, 'completed_at':datetime.now(timezone.utc).isoformat(),
               'selection_sha256':digest(out/'selection.json')})


def evaluate(root, out, frames, sets, cfg, selections):
    rows, predictions, sensitivities = [], [], []
    for selected in selections:
        scheme, fold, rep, name = [selected[k] for k in ['scheme','fold','representation','model']]
        f = frames[(scheme,fold)]
        for seed in cfg['seeds']:
            path = out/'models'/f'{scheme}__{fold}__{rep}__{name}__{seed}'/'model.joblib'
            payload = joblib.load(path)
            model, feat, threshold = [payload[k] for k in ['model','features','threshold']]
            with threadpool_limits(limits=1):
                for role in ['validation', 'test']:
                    part = f[f.role == role]
                    p = model.predict_proba(part[feat])[:,1]
                    ident = {**selected, 'seed':seed, 'role':role}
                    rows.append({**ident, **metrics(part.y_defect,p,threshold,part.row_id)})
                    pred = part[['row_id','run_id','Product_Type','event_order','y_defect']].copy()
                    pred['probability'], pred['threshold'] = p, threshold
                    for k,v in ident.items(): pred[k]=v
                    predictions.append(pred)
                if rep.endswith('_FB') or rep == 'FB':
                    scenarios = [(f'delay{d}',d,1.,()) for d in cfg['sensitivity']['delays']]
                    scenarios += [(f'coverage{c}',20,c,()) for c in cfg['sensitivity']['coverages']]
                    for role in ['validation','test']:
                        for label,d,c,blocked in scenarios+ [('no_current_partition_returns',20,1.,(role,))]:
                            stress = f.copy();stress[FB]=delayed_feedback(stress,d,c,blocked)
                            part=stress[stress.role==role];p=model.predict_proba(part[feat])[:,1]
                            sensitivities.append({**selected,'seed':seed,'role':role,'scenario':label,
                                                  **metrics(part.y_defect,p,threshold,part.row_id)})
    pd.DataFrame(rows).to_csv(out/'selected_metrics.csv', index=False)
    pd.concat(predictions, ignore_index=True).to_parquet(out/'selected_predictions.parquet', index=False)
    pd.DataFrame(sensitivities).to_csv(out/'feedback_sensitivity.csv',index=False)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='reports/oct06_research');p.add_argument('--jobs',type=int,default=4)
    args=p.parse_args();run(Path.cwd(),args.output,args.jobs)


if __name__=='__main__': main()
