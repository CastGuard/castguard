"""Registered second validation-only search; preserves the initial search registry."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path

import numpy as np
from joblib import Parallel, delayed, parallel_config

from castguard.data import digest
from castguard.model_search import OUT, CONFIG, run_candidate, deadline
from castguard.oct06_research import write_json

REFINE=Path('configs/oct08_model_refine.json')


def register():
    if REFINE.exists() or (OUT/'selection_seal.json').exists():raise FileExistsError('registration after evaluation/duplicate refused')
    if not all((OUT/f'{lane}_done.json').exists() for lane in ['cpu','neural']):raise ValueError('initial phase incomplete')
    rng=np.random.default_rng(202610081)
    cs=[]
    for family in ['xgboost','catboost','lightgbm','mlp','tabm']:
        for i in range(16 if family in ['xgboost','catboost','lightgbm'] else 12):
            if family=='xgboost':
                p=dict(max_depth=int(rng.choice([1,2,3,4,6,8])),learning_rate=float(10**rng.uniform(-2.3,-.6)),
                    min_child_weight=float(rng.choice([1,3,8,15,30])),reg_lambda=float(10**rng.uniform(-2,2)),
                    reg_alpha=float(rng.choice([0,.01,.1,1,5])),subsample=float(rng.choice([.6,.8,1.])),
                    colsample_bytree=float(rng.choice([.5,.8,1.])),max_bin=int(rng.choice([32,64,128,256])))
            elif family=='catboost':
                p=dict(depth=int(rng.choice([2,3,4,5,6,7,8])),learning_rate=float(10**rng.uniform(-2.3,-.6)),
                    l2_leaf_reg=float(10**rng.uniform(-1,2.3)),random_strength=float(rng.choice([0,.1,1,5])),
                    bagging_temperature=float(rng.choice([0,.5,1,3])),boosting_type=['Ordered','Plain'][i%2],
                    has_time=True,border_count=int(rng.choice([32,64,128])))
            elif family=='lightgbm':
                p=dict(num_leaves=int(rng.choice([3,7,15,31,63])),learning_rate=float(10**rng.uniform(-2.3,-.6)),
                    min_child_samples=int(rng.choice([5,10,20,50,100])),reg_lambda=float(10**rng.uniform(-2,2)),
                    reg_alpha=float(rng.choice([0,.01,.1,1,5])),subsample=float(rng.choice([.6,.8,1.])),
                    colsample_bytree=float(rng.choice([.5,.8,1.])),max_bin=int(rng.choice([31,63,127,255])))
            else:
                p=dict(width=int(rng.choice([64,128,256,512])),depth=int(rng.choice([1,2,3,4])),
                    dropout=float(rng.choice([0,.1,.2,.35,.5])),lr=float(10**rng.uniform(-4,-2.3)),
                    weight_decay=float(10**rng.uniform(-6,-1)),batch_size=int(rng.choice([128,256,512])),
                    k=int(rng.choice([16,32])),embeddings=(family=='tabm' and i%2==0))
            for rep in ['S_FB','SH_FB']:
                cs.append(dict(id=f'{family}_refine{i:02d}_{rep}',family=family,representation=rep,params=p))
    cfg=dict(candidates=cs,reason='Initial 128 validation candidates show neural gains below adoption threshold; broaden tuning before any test evaluation',
        unchanged='original objectives, success thresholds, folds, inner stopping, seeds, wall deadlines and finalist rules',
        adaptive_validation_search=True,test_used=False)
    write_json(REFINE,cfg)
    write_json(OUT/'refinement_registration.json',dict(at=datetime.now(timezone.utc).isoformat(),config=cfg,
        hashes={str(p):digest(p) for p in [REFINE,Path(__file__),Path('docs/OCT08_MODEL_REFINE_PROTOCOL.md')]},
        initial_validation_receipts={str(p):digest(p) for p in (OUT/'candidates').glob('*/17/complete.json')}))
    print('Registered refinement candidates',len(cs),flush=True)


def run(lane):
    cfg=json.loads(CONFIG.read_text());deadline(cfg,'stage1_deadline')
    cs=[c for c in json.loads(REFINE.read_text())['candidates'] if ((c['family'] in ['mlp','tabm'])==(lane=='neural'))]
    if lane=='cpu':
        with parallel_config(backend='loky',inner_max_num_threads=cfg['threads_per_job']):
            stream=Parallel(n_jobs=cfg['cpu_jobs'],return_as='generator_unordered',pre_dispatch=cfg['cpu_jobs'])(delayed(run_candidate)(c) for c in cs)
            for i,r in enumerate(stream,1):print(i,len(cs),r['id'],r['status'],r.get('error',''),flush=True)
    else:
        for i,c in enumerate(cs,1):
            deadline(cfg,'stage1_deadline')
            r=run_candidate(c);print(i,len(cs),r['id'],r['status'],r.get('error',''),flush=True)
    write_json(OUT/f'{lane}_refinement_done.json',dict(at=datetime.now(timezone.utc).isoformat()))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['register','cpu','neural']);args=p.parse_args()
    if args.action=='register':register()
    else:run(args.action)
