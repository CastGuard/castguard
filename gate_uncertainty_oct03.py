"""Descriptive paired run-block uncertainty for the already frozen Gate policies."""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def main():
    frame = pd.read_csv(ROOT / 'reports/oct03_pilot_r2/reused_test/g1_metrics.csv', dtype={'fold': str})
    values = frame.groupby(['scheme', 'fold', 'policy'], as_index=False)[
        ['normal', 'false_alarms', 'episodes_observable', 'episodes_detected']].mean()
    results = []
    for scheme in ['run_holdout', 'forward_run']:
        table = values.loc[values.scheme == scheme]
        blocks = sorted(table.fold.unique())
        rng = np.random.default_rng(20261003)
        draws = rng.integers(0, len(blocks), (1000, len(blocks)))
        lookup = {policy: table.loc[table.policy == policy].set_index('fold').loc[blocks]
                  for policy in ['baseline', 'constrained', 'simple_rule']}
        base = lookup['baseline']
        for policy, rows in lookup.items():
            for metric, numerator, denominator in [('fpr', 'false_alarms', 'normal'),
                    ('observable_episode_recall', 'episodes_detected', 'episodes_observable')]:
                p, n = rows[numerator].to_numpy(), rows[denominator].to_numpy()
                bp, bn = base[numerator].to_numpy(), base[denominator].to_numpy()
                sample = p[draws].sum(axis=1) / n[draws].sum(axis=1)
                base_sample = bp[draws].sum(axis=1) / bn[draws].sum(axis=1)
                for comparison, estimate, sampled in [
                    ('absolute', p.sum() / n.sum(), sample),
                    ('minus_baseline', p.sum() / n.sum() - bp.sum() / bn.sum(), sample - base_sample)]:
                    low, high = np.quantile(sampled, [.025, .975])
                    results.append({'scheme': scheme, 'policy': policy, 'metric': metric, 'comparison': comparison,
                        'estimate': estimate, 'lower95': low, 'upper95': high, 'run_blocks': len(blocks),
                        'bootstrap_repetitions': 1000, 'scope': 'few_observed_runs_fixed_policy_not_unseen_run_guarantee'})
    output = pd.DataFrame(results)
    output.to_csv(ROOT / 'reports/oct03_review/g1_run_block_intervals.csv', index=False)
    print(output.loc[(output.policy == 'constrained') & (output.metric == 'fpr')].to_string(index=False))


if __name__ == '__main__':
    main()
