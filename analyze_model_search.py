"""Validation selection, frozen ensembles and only then reused-test evaluation."""
from datetime import datetime, timezone
import argparse
import itertools
import json
from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed, parallel_config
from sklearn.metrics import average_precision_score

from castguard.data import digest
from castguard.model_search import OUT, CONFIG, candidate_dir, run_candidate, predict, deadline
from castguard.oct06_research import metrics, write_json


def read_config():
    cfg=json.loads(CONFIG.read_text())
    refine=Path('configs/oct08_model_refine.json')
    if refine.exists():cfg['candidates']+=json.loads(refine.read_text())['candidates']
    return cfg


def ranking(rows, baseline):
    g=rows.merge(baseline[['scheme','fold','ap','capture20']],on=['scheme','fold'],suffixes=('','_baseline'))
    g['ap_gain']=g.ap-g.ap_baseline;g['capture_gain']=g.capture20-g.capture20_baseline
    w=g[g.scheme=='within_run'].iloc[0];f=g[g.scheme=='forward_run']
    consistent=int(((f.ap_gain>=0)&(f.capture_gain>=0)).sum())
    return dict(objective=float(.5*w.ap_gain+.5*f.ap_gain.mean()),within_ap=float(w.ap),within_ap_gain=float(w.ap_gain),
                within_capture=float(w.capture20),within_capture_gain=float(w.capture_gain),
                forward_ap_gain=float(f.ap_gain.mean()),forward_consistent=consistent,
                qualifies=bool(w.ap_gain>=.02 and w.capture_gain>=.05 and consistent>=2))


def shortlist():
    cfg=read_config()
    if (OUT/'shortlist.json').exists():raise FileExistsError('shortlist already sealed')
    if not all((OUT/f'{lane}_done.json').exists() for lane in ['cpu','neural']):
        raise ValueError('Both lanes must finish or explicitly record interruption')
    if Path('configs/oct08_model_refine.json').exists() and not all((OUT/f'{lane}_refinement_done.json').exists() for lane in ['cpu','neural']):
        raise ValueError('Refinement lanes incomplete')
    base=pd.DataFrame(json.loads((OUT/'candidates/baseline/17/complete.json').read_text())['rows'])
    result=[];all_rows=[];failures=[]
    for c in cfg['candidates']:
        path=candidate_dir(c,17)/'complete.json'
        if not path.exists():
            failures.append(c['id']);continue
        rows=pd.DataFrame(json.loads(path.read_text())['rows'])
        if len(rows)!=5:raise ValueError('incomplete fold candidate')
        result.append(dict(id=c['id'],family=c['family'],representation=c['representation'],**ranking(rows,base)))
        all_rows.append(rows)
    table=pd.DataFrame(result).sort_values(['objective','within_ap','id'],ascending=[False,False,True])
    chosen=table.groupby('family',sort=True).head(1)
    table.to_csv(OUT/'stage1_ranking.csv',index=False)
    pd.concat(all_rows+[base],ignore_index=True).to_csv(OUT/'stage1_metrics.csv',index=False)
    write_json(OUT/'shortlist.json',dict(at=datetime.now(timezone.utc).isoformat(),
        ids=chosen.id.tolist(),ranking_sha256=digest(OUT/'stage1_ranking.csv'),failures=failures,
        rule='per-family highest preregistered validation objective; no test metrics used'))
    print(chosen.to_string(index=False),flush=True)


def refit(lane):
    cfg=read_config();deadline(cfg,'finalist_deadline')
    ids=json.loads((OUT/'shortlist.json').read_text())['ids']
    cs=[c for c in cfg['candidates'] if c['id'] in ids and ((c['family'] in ['mlp','tabm'])==(lane=='neural'))]
    tasks=[(c,s) for c in cs for s in cfg['seeds'][1:]]
    if lane=='cpu':
        with parallel_config(backend='loky',inner_max_num_threads=cfg['threads_per_job']):
            results=Parallel(n_jobs=cfg['cpu_jobs'])(delayed(run_candidate)(c,s) for c,s in tasks)
    else:results=[run_candidate(c,s) for c,s in tasks]
    for r in results:print(r['id'],r['seed'],r['status'],r.get('error',''),flush=True)
    write_json(OUT/f'{lane}_refit_done.json',dict(at=datetime.now(timezone.utc).isoformat(),statuses=[{k:r[k] for k in ['id','seed','status']} for r in results]))


def component_predictions(role):
    if role not in ['validation','test']:raise ValueError('unsupported role')
    if role=='test' and not (OUT/'selection_seal.json').exists():
        raise ValueError('Test evaluation requires a sealed validation selection')
    cfg=read_config();ids=json.loads((OUT/'shortlist.json').read_text())['ids']
    ids=['baseline']+[i for i in ids if all((OUT/'candidates'/i/str(s)/'complete.json').exists() for s in cfg['seeds'])]
    keys=list(joblib.load(OUT/'development.joblib')['frames'])
    test=joblib.load(OUT/'test.joblib') if role=='test' else None
    components={};payload_hashes={}
    for identity in ids:
        predictions={}
        for scheme,fold in keys:
            frames=[]
            for seed in ([17] if identity=='baseline' else cfg['seeds']):
                folder=OUT/'candidates'/identity/str(seed)/f'{scheme}__{fold}'
                payload_hashes[str(folder/'model.joblib')]=digest(folder/'model.joblib')
                if role=='validation':p=pd.read_parquet(folder/'validation.parquet')
                else:
                    deadline(cfg)
                    part=test[(scheme,fold)]
                    payload=joblib.load(folder/'model.joblib')
                    p=part[['row_id','run_id','y_defect']].copy()
                    p['probability']=predict(payload,part)
                    p.to_parquet(folder/'test.parquet',index=False)
                frames.append(p.set_index('row_id'))
            for p in frames[1:]:
                pd.testing.assert_index_equal(frames[0].index,p.index)
                np.testing.assert_array_equal(frames[0].y_defect,p.y_defect)
            frame=frames[0].copy();frame['probability']=np.mean([p.probability.to_numpy() for p in frames],axis=0)
            predictions[(scheme,fold)]=frame.reset_index()
        components[identity]=predictions
    return components,payload_hashes


def combinations(ids):
    variants={i:{i:1.} for i in ids}
    for a,b in itertools.combinations(sorted(ids),2):
        for w in [.25,.5,.75]:variants[f'blend__{a}__{b}__{w}']={a:w,b:1-w}
    new=[i for i in ids if i!='baseline']
    if new:variants['mean_new']={i:1/len(new) for i in new}
    variants['mean_all']={i:1/len(ids) for i in ids}
    return variants


def blended(components,weights,key):
    frame=components[next(iter(weights))][key].copy()
    for i in weights:
        pd.testing.assert_series_equal(frame.row_id,components[i][key].row_id)
        np.testing.assert_array_equal(frame.y_defect,components[i][key].y_defect)
    frame['probability']=sum(components[i][key].probability.to_numpy()*w for i,w in weights.items())
    return frame


def seal():
    if (OUT/'selection_seal.json').exists():raise FileExistsError('selection already sealed')
    if not all((OUT/f'{lane}_refit_done.json').exists() for lane in ['cpu','neural']):raise ValueError('refits incomplete')
    components,hashes=component_predictions('validation')
    variants=combinations(list(components))
    keys=list(components['baseline'])
    baseline=[]
    for key,p in components['baseline'].items():
        t=float(np.nextafter(np.quantile(p.probability,.8),np.inf))
        baseline.append(dict(scheme=key[0],fold=key[1],**metrics(p.y_defect,p.probability,t,p.row_id)))
    baseline=pd.DataFrame(baseline)
    ranking_rows=[];metric_rows=[];thresholds={}
    for identity,weights in variants.items():
        rows=[];thresholds[identity]={}
        for key in keys:
            p=blended(components,weights,key)
            t=float(np.nextafter(np.quantile(p.probability,.8),np.inf))
            thresholds[identity]['__'.join(key)]=t
            rows.append(dict(id=identity,scheme=key[0],fold=key[1],**metrics(p.y_defect,p.probability,t,p.row_id)))
        metric_rows.extend(rows)
        ranking_rows.append(dict(id=identity,**ranking(pd.DataFrame(rows),baseline)))
    table=pd.DataFrame(ranking_rows).sort_values(['objective','within_ap','id'],ascending=[False,False,True])
    qualified=table[table.qualifies]
    winner=(qualified if len(qualified) else table).iloc[0].id
    table.to_csv(OUT/'ensemble_validation_ranking.csv',index=False)
    pd.DataFrame(metric_rows).to_csv(OUT/'ensemble_validation_metrics.csv',index=False)
    # Freeze ALL decisions and checkpoints before test data are opened by this analysis.
    write_json(OUT/'selection_seal.json',dict(at=datetime.now(timezone.utc).isoformat(),winner=winner,
        highest_objective=table.iloc[0].id,qualifies=bool(len(qualified)),qualified_count=len(qualified),
        weights=variants[winner],variants=variants,thresholds=thresholds,model_hashes=hashes,
        ranking_sha256=digest(OUT/'ensemble_validation_ranking.csv'),
        analysis_sha256=digest(Path(__file__)),
        inference_sha256=digest('castguard/search_reader.py'),
        test_used_for_selection=False,independent_validation=False,
        evaluate_ids=list(dict.fromkeys(['baseline',*components.keys(),winner])),
        deployment='separate research candidate; existing reader untouched'))
    print(table.head(12).to_string(index=False),flush=True)
    print('SEALED',winner,'qualifies',bool(len(qualified)),flush=True)


def evaluate():
    seal=json.loads((OUT/'selection_seal.json').read_text())
    if (OUT/'test_metrics.csv').exists():raise FileExistsError('test results already exist')
    for path,h in seal['model_hashes'].items():
        if digest(path)!=h:raise ValueError('changed checkpoint after sealing')
    components,_=component_predictions('test')
    rows=[];predictions=[]
    for identity in seal['evaluate_ids']:
        weights=seal['variants'][identity]
        for key in components['baseline']:
            p=blended(components,weights,key)
            t=seal['thresholds'][identity]['__'.join(key)]
            rows.append(dict(id=identity,scheme=key[0],fold=key[1],**metrics(p.y_defect,p.probability,t,p.row_id)))
            p['id']=identity;p['scheme']=key[0];p['fold']=key[1];p['threshold']=t
            predictions.append(p)
    table=pd.DataFrame(rows);table.to_csv(OUT/'test_metrics.csv',index=False)
    pd.concat(predictions,ignore_index=True).to_parquet(OUT/'test_predictions.parquet',index=False)
    key=('within_run','primary')
    a=blended(components,seal['weights'],key);b=components['baseline'][key]
    rng=np.random.default_rng(20261008);runs=np.unique(a.run_id);draws=[]
    for _ in range(1000):
        chosen=rng.choice(runs,len(runs),replace=True)
        ix=np.concatenate([np.flatnonzero(a.run_id.to_numpy()==r) for r in chosen])
        y=a.y_defect.to_numpy()[ix]
        if len(np.unique(y))<2:continue
        draws.append(average_precision_score(y,a.probability.to_numpy()[ix])-average_precision_score(y,b.probability.to_numpy()[ix]))
    write_json(OUT/'uncertainty.json',dict(method='paired run block bootstrap; reused within test; conditional on selected model',
        runs=len(runs),replicates=len(draws),ap_difference=float(average_precision_score(a.y_defect,a.probability)-average_precision_score(b.y_defect,b.probability)),
        interval95=np.quantile(draws,[.025,.975]).tolist(),not_seed_sd=True))
    print(table[table.scheme=='within_run'][['id','ap','auc','capture20','fpr','tp','fp']].to_string(index=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['shortlist','cpu','neural','seal','evaluate']);args=p.parse_args()
    if args.action=='shortlist':shortlist()
    elif args.action in ['cpu','neural']:refit(args.action)
    elif args.action=='seal':seal()
    else:evaluate()
