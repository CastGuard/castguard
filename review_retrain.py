"""Bounded reproduction of two frozen fits; never tune on the exposed historical test."""
from pathlib import Path
from datetime import datetime, timezone
from hashlib import sha256
import argparse, json, math, shutil, sys, time, uuid

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TASKS = [dict(dataset='q42', population='all', scheme='within_run', fold='primary',
              experiment='A', model=model, seed=17) for model in ['logistic', 'lightgbm']]
METRIC_ATOL = 1e-10
PREDICTION_ATOL = 1e-12


def compare_metrics(actual, expected):
    """Require every non-timing metric and exactly the two historical roles."""
    from castguard.experiment import IDENTITY
    ignored = set(IDENTITY + ['role', 'fit_seconds', 'predict_us_per_row'])
    columns = [c for c in expected.columns if c not in ignored]
    if set(actual.role) != {'validation', 'test'} or len(actual) != 2 or len(expected) != 2:
        raise ValueError('metric role/cardinality mismatch')
    left, right = actual.set_index('role'), expected.set_index('role')
    count, maximum = 0, 0.0
    for role in ['validation', 'test']:
        for name in columns:
            a, b = float(left.loc[role, name]), float(right.loc[role, name])
            if math.isnan(a) and math.isnan(b):
                continue
            if not math.isfinite(a) or not math.isfinite(b) or abs(a-b) > METRIC_ATOL:
                raise ValueError(f'metric mismatch: {role}/{name}: {a} vs {b}')
            maximum = max(maximum, abs(a-b)); count += 1
    return {'numeric_values_compared': count, 'maximum_absolute_error': maximum,
            'absolute_tolerance': METRIC_ATOL, 'timing_metrics_excluded': True}


def compare_predictions(actual, expected):
    import numpy as np
    keys = ['role', 'row_id']
    if actual.duplicated(keys).any() or expected.duplicated(keys).any():
        raise ValueError('duplicate prediction identity')
    left = actual.sort_values(keys).reset_index(drop=True)
    right = expected.sort_values(keys).reset_index(drop=True)
    if len(left) != len(right) or not left[keys + ['y', 'prediction']].equals(right[keys + ['y', 'prediction']]):
        raise ValueError('prediction row/role/label/decision mismatch')
    delta = np.abs(left[['probability', 'threshold']].to_numpy() - right[['probability', 'threshold']].to_numpy())
    if not np.isfinite(delta).all() or (delta > PREDICTION_ATOL).any():
        raise ValueError('prediction probability/threshold mismatch')
    return {'rows': len(left), 'numeric_values_compared': int(delta.size),
            'maximum_absolute_error': float(delta.max()), 'absolute_tolerance': PREDICTION_ATOL,
            'identity_labels_decisions_equal': True}


def run(output, root=ROOT):
    from review_environment import require
    from review import verify_manifest
    require(root)
    verify_manifest(Path(root))
    import pandas as pd
    from castguard.experiment import fit_one, task_name, IDENTITY, environment
    from castguard.rebuild import rebuild_check
    root, output = Path(root).resolve(), Path(output).resolve()
    if not output.is_relative_to(root / 'verification_runs'):
        raise ValueError('Output must be a new child of verification_runs')
    output.mkdir(parents=True, exist_ok=False)
    digest = lambda p: sha256(p.read_bytes()).hexdigest()
    frozen = ['configs/oct02.json', 'requirements-lock.txt', 'docs/CLEAN_REPRODUCTION_PROTOCOL.md', 'review_retrain.py']
    frozen += [p.relative_to(root).as_posix() for folder in ['castguard', 'data/raw', 'data/processed']
               for p in (root / folder).glob('*') if p.is_file()]
    frozen += ['reports/oct02/metrics.csv', 'reports/oct02/predictions.parquet']
    bindings = {name: digest(root / name) for name in frozen}
    save = lambda name, obj: (output / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    started = time.perf_counter()
    registration = {'registered_at': datetime.now(timezone.utc).isoformat(), 'tasks': TASKS,
                    'source_hashes': bindings, 'metric_atol': METRIC_ATOL,
                    'prediction_atol': PREDICTION_ATOL, 'environment': environment(),
                    'new_performance_evidence': False, 'tuning_performed': False}
    save('registration.json', registration)  # Written before fitting or reading comparison results.
    try:
        scratch = output / 'scratch'; scratch.mkdir()
        for folder in ['data/raw', 'data/processed']:
            shutil.copytree(root / folder, scratch / folder)
        rebuild_check(scratch, output / 'rebuild')
        config = json.loads((root / 'configs/oct02.json').read_text(encoding='utf-8'))
        fits = []
        for task in TASKS:
            start = time.perf_counter()
            fit_one(scratch, output / 'fits', task, config)
            fits.append({'task': task, 'wall_seconds': time.perf_counter() - start})
        # No model or configuration selection occurs after reading exposed comparison evidence.
        saved_metrics = pd.read_csv(root / 'reports/oct02/metrics.csv', dtype={'fold': str}, float_precision='round_trip')
        saved_predictions = pd.read_parquet(root / 'reports/oct02/predictions.parquet')
        for item in fits:
            task = item['task']; folder = output / 'fits' / task_name(task)
            actual = pd.read_csv(folder / 'metrics.csv', dtype={'fold': str}, float_precision='round_trip')
            expected = saved_metrics.loc[(saved_metrics[IDENTITY] == pd.Series(task)).all(axis=1)]
            item['metrics'] = compare_metrics(actual, expected)
            if task['model'] == 'lightgbm':
                expected = saved_predictions.loc[(saved_predictions[IDENTITY] == pd.Series(task)).all(axis=1)]
                item['predictions'] = compare_predictions(pd.read_parquet(folder / 'predictions.parquet'), expected)
            else:
                item['predictions'] = {'compared': False, 'reason': 'Original logistic row predictions are not included in the bundle'}
        for name, h in bindings.items():
            if digest(root / name) != h:
                raise ValueError('Frozen source changed during reproduction: ' + name)
        result = {'status': 'passed', 'checked_at': datetime.now(timezone.utc).isoformat(),
                  'elapsed_seconds': time.perf_counter() - started, 'fits': fits,
                  'rebuild': json.loads((output / 'rebuild/rebuild_verification.json').read_text(encoding='utf-8')),
                  'source_hashes_unchanged': True, 'full_matrix_retraining_performed': False,
                  'new_performance_evidence': False, 'independent_test': False, 'tuning_performed': False,
                  'receipt_directory': output.relative_to(root).as_posix()}
        save('summary.json', result); return result
    except Exception as exc:
        save('failure.json', {'status': 'failed', 'error_type': type(exc).__name__, 'reason': str(exc),
                             'elapsed_seconds': time.perf_counter() - started})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / 'verification_runs' / ('retrain_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8])
    print(json.dumps(run(output), ensure_ascii=False, indent=2, allow_nan=False))
