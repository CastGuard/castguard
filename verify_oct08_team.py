"""Replay the team's retained add Gate/type models without changing JH or source snapshot."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score
from threadpoolctl import threadpool_limits


def run(reference, output):
    ref, out = Path(reference).resolve(), Path(output)
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location('team_add', ref/'castguard/__init__.py', submodule_search_locations=[str(ref/'castguard')])
    module = importlib.util.module_from_spec(spec)
    sys.modules['team_add'] = module
    spec.loader.exec_module(module)
    from team_add.train import load_inputs, with_roles, fit_eval, _task
    from team_add.features import add_feedback, quality_feature_sets
    from team_add.analysis import adaptive_alarm
    cfg = json.loads((ref/'configs/castguard.json').read_text(encoding='utf-8'))
    q, m, _, folds, contract = load_inputs()
    registration = {'reference_commit':'90402e0', 'purpose':'retained model replay; no new selection',
                    'hashes':{str(p.relative_to(ref)):hashlib.sha256(p.read_bytes()).hexdigest() for p in ref.rglob('*') if p.is_file() and '__pycache__' not in p.parts},
                    'gate_model':'catboost', 'gate_features':'m41_gate_rel', 'quality_representation':'A_FB'}
    (out/'registration.json').write_text(json.dumps(registration,ensure_ascii=False,indent=2),encoding='utf-8')
    all_predictions, gate_rows, type_rows = [], [], []
    splits = folds[folds.dataset == 'm41'][['scheme','fold']].drop_duplicates()
    with threadpool_limits(limits=1):
        for scheme, fold in splits.itertuples(index=False, name=None):
            full = with_roles(m, folds, 'm41', scheme, fold)
            frame = full[full.role != 'excluded'].copy()
            for seed in cfg['seeds']:
                task = _task('gate',scheme,fold,'Gate','catboost',seed,'Machine_Status',contract['m41_gate_rel'])
                _, pred = fit_eval(frame,task,cfg)
                all_predictions.append(pred)
                d = pred[pred.role == 'test'].merge(m[['row_id','run_id','source_row','episode_id']],on='row_id',validate='one_to_one').sort_values('source_row')
                for policy in ['고정','적응형']:
                    alarm = pd.Series(False,index=d.index)
                    if policy == '고정':
                        alarm = d.p >= d.threshold
                    else:
                        for _, g in d.groupby('run_id',sort=False):
                            alarm.loc[g.index] = adaptive_alarm(g,cfg)
                    episodes = d[d.episode_id.notna()].groupby('episode_id')
                    detected = sum(bool(alarm.loc[e.index].iloc[:cfg['gate_detect_within_shots']].any()) for _,e in episodes)
                    normal = d.y == 0
                    # Includes episodes excluded from scoring but located in test run/Shot boundaries.
                    all_episode_ids = set()
                    for run_id, g in d.groupby('run_id'):
                        timeline = m[(m.run_id == run_id) & m.source_row.between(g.source_row.min(), g.source_row.max())]
                        all_episode_ids.update(timeline.episode_id.dropna().unique())
                    gate_rows.append({'policy':policy,'scheme':scheme,'fold':fold,'seed':seed,
                        'episodes':episodes.ngroups,'all_episodes_in_test_boundaries':len(all_episode_ids),
                        'detected_within_k':detected,'normal_rows':int(normal.sum()),'false_positive':int(alarm[normal].sum()),
                        'false_stop_rate':float(alarm[normal].mean()),'warmup_row_recall':float(alarm[d.y==1].mean()),
                        'row_auc':roc_auc_score(d.y,d.p)})
            print('team Gate replay',scheme,fold,flush=True)
        qfb = add_feedback(q,cfg['label_delay_shots'],cfg['feedback_windows'],cfg['feedback_halflife'])
        f = with_roles(qfb,folds,'q42','within_run','primary')
        feat = quality_feature_sets(contract,cfg['feedback_windows'])['A_FB']
        selection = pd.read_csv(ref/'reports/tables/defect_type_model_selection.csv')
        for row in selection[selection.selected].itertuples():
            for seed in cfg['seeds']:
                task = _task('type','within_run','primary','A_FB',row.model,seed,row.target,feat,delay=20)
                _, pred = fit_eval(f,task,cfg)
                all_predictions.append(pred)
                d = pred[pred.role == 'test']
                type_rows.append({'target':row.target.removeprefix('y_type_'),'model':row.model,'seed':seed,
                    'test_positive':int(d.y.sum()),'n':len(d),'prevalence':float(d.y.mean()),
                    'test_auc':roc_auc_score(d.y,d.p),'test_ap':average_precision_score(d.y,d.p)})
            print('team type replay',row.target,flush=True)
    g = pd.DataFrame(gate_rows)
    t = pd.DataFrame(type_rows)
    g.to_csv(out/'gate_seed_metrics.csv',index=False)
    t.to_csv(out/'type_seed_metrics.csv',index=False)
    pd.concat(all_predictions,ignore_index=True).to_parquet(out/'predictions.parquet',index=False)
    gs = g.groupby(['policy','scheme','fold']).mean(numeric_only=True).reset_index()
    ts = t.groupby(['target','model']).mean(numeric_only=True).reset_index()
    gs.to_csv(out/'gate_summary.csv',index=False)
    ts.to_csv(out/'type_summary.csv',index=False)
    checks = {}
    for name, actual, keys, cols in [
        ('gate',gs,['policy','scheme','fold'],['episodes','detected_within_k','false_stop_rate','row_auc']),
        ('type',ts,['target','model'],['test_positive','prevalence','test_auc','test_ap'])]:
        filename = 'gate_results.csv' if name=='gate' else 'defect_type_results.csv'
        old = pd.read_csv(ref/'reports/tables'/filename,dtype={'fold':str})
        actual['fold'] = actual['fold'].astype(str) if 'fold' in actual else ''
        joined = actual.merge(old,on=keys,suffixes=('_new','_old'),validate='one_to_one')
        delta = max(float((joined[c+'_new']-joined[c+'_old']).abs().max()) for c in cols)
        checks[name] = {'rows':len(joined),'max_absolute_difference_from_rounded_table':delta,'matched_to_rounding':delta<=.000051}
    (out/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print(json.dumps(checks),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--reference',default='reports/oct08_team_reference/add_90402e0')
    p.add_argument('--output',default='reports/oct08_team_replay')
    a=p.parse_args();run(a.reference,a.output)
