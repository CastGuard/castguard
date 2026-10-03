"""Independent receipts, split/transform checks, full-population and queue accounting."""
import json
from pathlib import Path
from datetime import datetime, timezone
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from castguard.data import attach_roles, digest, read_inputs
from castguard.storage import write_json
from oct03_queue import make_identity, choose_policy
from historical_sources import resolve_historical_source

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'reports/oct03_queue'
REVIEW = ROOT / 'reports/oct03_queue_review'


def check(root=ROOT, out=OUT):
    receipt = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in receipt['input_hashes'].items():resolve_historical_source(root,name,expected)
    for name, expected in receipt['outputs'].items():
        assert digest(out/name) == expected
    frames, folds, _ = read_inputs(root)
    split = pd.read_csv(out/'nested_assignments.csv', dtype={'fold':str})
    assert not split.duplicated(['fold','dataset','row_id']).any()
    for fold in split.fold.unique():
        for dataset in ['q42','m41']:
            actual = split.loc[split.fold.eq(fold)&split.dataset.eq(dataset)]
            original = folds.loc[folds.fold.eq(fold)&folds.dataset.eq(dataset)&folds.scheme.eq('forward_run')]
            assert set(actual.row_id).isdisjoint(set(original.loc[original.role.eq('test'),'row_id']))
            if dataset == 'q42':
                assert set(actual.loc[actual.nested_role.eq('evaluation'),'row_id']) == set(original.loc[original.role.eq('validation'),'row_id'])
                assert set(actual.loc[actual.nested_role.ne('evaluation'),'row_id']) == set(original.loc[original.role.eq('train'),'row_id'])
            parts = actual.groupby('nested_role').source_row.agg(['min','max'])
            assert parts.loc['fit','max'] < parts.loc['calibration','min']
            assert parts.loc['calibration','max'] < parts.loc['evaluation','min']
            if dataset == 'm41':
                metadata = actual.merge(frames['m41'][['row_id','episode_id']], on='row_id', validate='one_to_one')
                assert metadata.dropna(subset=['episode_id']).groupby('episode_id').nested_role.nunique().max() == 1
    candidates = pd.read_parquet(out/'candidate_predictions.parquet')
    models = 0
    for path in (out/'models').glob('*.joblib'):
        item = joblib.load(path)
        dataset = 'q42' if item['task'] == 'quality' else 'm41'
        eligible = split.loc[split.fold.eq(item['fold']) & split.dataset.eq(dataset) & split.nested_role.eq('fit'),'row_id']
        fit = frames[dataset].loc[frames[dataset].row_id.isin(eligible)]
        if dataset == 'm41':
            fit = fit.loc[fit.gate_eligible]
        assert set(item['fit_row_ids']) == set(fit.row_id)
        features, pipeline = item['features'], item['pipeline']
        expected = fit[features].median().fillna(0).to_numpy()
        np.testing.assert_allclose(pipeline.named_steps['impute'].statistics_, expected, rtol=1e-12, atol=1e-12)
        if 'scale' in pipeline.named_steps:
            assert pipeline.named_steps['scale'].n_samples_seen_ == len(fit)
        prediction = candidates.loc[candidates.fold.eq(item['fold']) & candidates.task.eq(item['task'])
            & candidates.model.eq(item['model']) & candidates.seed.eq(item['seed'])]
        truth = frames[dataset].set_index('row_id').loc[prediction.row_id]
        with threadpool_limits(limits=1):
            np.testing.assert_allclose(pipeline.predict_proba(truth[features])[:,1], prediction.probability,rtol=1e-12,atol=1e-12)
        models += 1
    assert models == 80
    selections = json.loads((out/'selection.json').read_text(encoding='utf-8'))
    inner = pd.read_csv(out/'inner_policy_metrics.csv',dtype={'fold':str},float_precision='round_trip')
    for choice in selections['folds']:
        assert choose_policy(inner.loc[inner.fold.eq(choice['fold'])]) == choice['selected_policy']
    checked = 0
    action_count = 0
    for prefix in ['inner','outer']:
        records = pd.read_parquet(out/f'{prefix}_actions.parquet')
        metrics = pd.read_csv(out/f'{prefix}_policy_metrics.csv',dtype={'fold':str},float_precision='round_trip')
        keys = ['fold','seed','policy','budget']
        assert not records.duplicated(keys+['row_id']).any()
        assert not metrics.duplicated(keys).any()
        indexed = metrics.set_index(keys)
        for key, rows in records.groupby(keys):
            saved = indexed.loc[key]
            budget = key[-1]
            assert saved.n_total == len(rows)
            normal = rows.Machine_Status.eq(0)
            warm = rows.Machine_Status.eq(1)
            assert normal.sum()+warm.sum()+rows.Machine_Status.isna().sum() == len(rows)
            assert saved.normal_total == normal.sum() and saved.warm_total == warm.sum()
            assert saved.auto_false_alarms == (normal & rows.alarm).sum()
            assert saved.normal_alarm_or_hold == (normal & (rows.alarm|rows.hold)).sum()
            np.testing.assert_allclose(saved.normal_intervention_rate, saved.normal_alarm_or_hold/saved.normal_total)
            assert saved.hold_requested == rows.hold.sum()
            assert saved.hold_requested == saved.hold_served + saved.hold_backlog
            assert saved.hold_backlog == (rows.hold & ~rows.inspected).sum()
            np.testing.assert_allclose(saved.coverage, (rows.process_complete & ~rows.ood).mean())
            assert saved.inspected == rows.inspected.sum() <= int(np.floor(len(rows)*budget+1e-12))
            served = rows.loc[rows.inspected]
            assert served.service_step.ge(served.arrival_step).all()
            assert not served.service_step.duplicated().any()
            counts = np.bincount(served.service_step.to_numpy(dtype=int),minlength=len(rows)).cumsum()
            assert np.all(counts <= np.floor(np.arange(1,len(rows)+1)*budget+1e-12))
            np.testing.assert_allclose(served.wait_records,served.service_step-served.arrival_step)
            assert saved.quality_positive == rows.y_defect.eq(1).sum()
            assert saved.quality_captured == (rows.y_defect.eq(1)&rows.inspected).sum()
            assert saved.quality_known == rows.y_defect.notna().sum()
            np.testing.assert_allclose(saved.quality_capture, saved.quality_captured/saved.quality_positive)
            assert saved.quality_inspected+saved.quality_missing_inspected == saved.inspected
            episodes = rows.loc[warm].groupby('episode_id')
            assert saved.episodes_total == len(episodes)
            assert saved.episodes_auto_detected == sum(part.alarm.any() for _,part in episodes)
            assert saved.episodes_inspection_reached == sum(part.inspected.any() for _,part in episodes)
            checked += 1
        action_count += len(records)
    assert checked == 480
    return {'verified_at':datetime.now(timezone.utc).isoformat(),'models_reloaded':models,'queue_metric_groups':checked,
        'action_rows':action_count,'nested_chronology_verified':True,'legacy_test_rows_in_experiment':0,
        'train_only_imputation_verified':True,'prefix_budget_and_delay_verified':True,
        'full_population_and_backlog_conservation_verified':True,'inner_only_selection_recomputed':True}


def summarize():
    frame = pd.read_csv(OUT/'outer_policy_metrics.csv',dtype={'fold':str})
    primary = frame.loc[frame.budget.eq(.2)]
    means = primary.groupby(['fold','policy'],as_index=False).mean(numeric_only=True)
    means.to_csv(REVIEW/'outer_fold_means_at20.csv',index=False)
    totals = means.groupby('policy')[['n_total','normal_total','auto_false_alarms','normal_alarm_or_hold',
        'hold_requested','hold_backlog','inspected','quality_positive','quality_captured','quality_known',
        'episodes_total','episodes_observable','episodes_auto_detected','episodes_inspection_reached']].sum()
    totals['quality_capture_pooled'] = totals.quality_captured/totals.quality_positive
    totals['auto_fpr_all_normal'] = totals.auto_false_alarms/totals.normal_total
    totals['normal_intervention_rate'] = totals.normal_alarm_or_hold/totals.normal_total
    totals['coverage'] = 1-totals.hold_requested/totals.n_total
    totals['hold_rate'] = totals.hold_requested/totals.n_total
    totals['inspection_hours_at3min'] = totals.inspected/20
    totals['backlog_hours_at3min'] = totals.hold_backlog/20
    totals.to_csv(REVIEW/'pooled_at20.csv')
    contrasts = []
    q = means.loc[means.policy.eq('Q')].set_index('fold')
    gq = means.loc[means.policy.eq('GQ')].set_index('fold')
    for policy in ['GQ','OOD1','OOD05']:
        p = means.loc[means.policy.eq(policy)].set_index('fold')
        for fold in p.index:
            contrasts.append({'fold':fold,'policy':policy,'capture_gain_vs_Q':p.loc[fold,'quality_capture']-q.loc[fold,'quality_capture'],
                'capture_gain_vs_GQ':p.loc[fold,'quality_capture']-gq.loc[fold,'quality_capture'],
                'hold_backlog_gain':p.loc[fold,'hold_backlog']-gq.loc[fold,'hold_backlog'],
                'normal_intervention_gain':p.loc[fold,'normal_intervention_rate']-gq.loc[fold,'normal_intervention_rate'],
                'warm_reach_gain':p.loc[fold,'episodes_inspection_reached']-gq.loc[fold,'episodes_inspection_reached']})
    contrast = pd.DataFrame(contrasts)
    contrast.to_csv(REVIEW/'policy_contrasts_at20.csv',index=False)
    select = json.loads((OUT/'selection.json').read_text(encoding='utf-8'))['folds']
    selected_rows = pd.concat([contrast.loc[contrast.fold.eq(s['fold'])&contrast.policy.eq(s['selected_policy'])] for s in select])
    gainq, gaing = selected_rows.capture_gain_vs_Q, selected_rows.capture_gain_vs_GQ
    adopted = (gainq.mean()>=.05 and gaing.mean()>=.05 and gainq.ge(0).all() and gaing.ge(0).all()
        and selected_rows.hold_backlog_gain.le(0).all() and selected_rows.normal_intervention_gain.le(0).all()
        and selected_rows.warm_reach_gain.ge(0).all())
    decision = {'adopt_ood_policy':bool(adopted),'selected_policies':{s['fold']:s['selected_policy'] for s in select},
        'macro_gain_vs_Q':gainq.mean(),'macro_gain_vs_GQ':gaing.mean(),
        'pooled_GQ_minus_Q':totals.loc['GQ','quality_capture_pooled']-totals.loc['Q','quality_capture_pooled'],
        'no_new_independent_evaluation':True,'deployment_changed':False}
    write_json(REVIEW/'decision.json',decision)
    # Fixed-policy paired run bootstrap; few historically seen development runs only.
    rng = np.random.default_rng(20261003)
    draw = rng.integers(0,len(q),(1000,len(q)))
    y=q.quality_positive.to_numpy()
    delta=gq.quality_captured.to_numpy()-q.quality_captured.to_numpy()
    boot=delta[draw].sum(axis=1)/y[draw].sum(axis=1)
    write_json(REVIEW/'conditional_uncertainty.json',{'contrast':'GQ minus Q pooled quality capture',
        'estimate':float(delta.sum()/y.sum()),'lower95':float(np.quantile(boot,.025)),
        'upper95':float(np.quantile(boot,.975)),'run_blocks':len(q),'repetitions':1000,
        'limitation':'fixed selected policies on four historically seen development runs; not independent confirmation'})
    print(totals.round(5).to_string())
    print(json.dumps(decision))


if __name__ == '__main__':
    result=check()
    REVIEW.mkdir(exist_ok=True)
    write_json(REVIEW/'verification.json',result)
    summarize()
    print(json.dumps(result))
