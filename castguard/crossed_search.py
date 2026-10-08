"""Complete model-by-dataset experiment with explicit pure-42 reference and locked ablations."""
from __future__ import annotations
from datetime import datetime,timezone
from functools import lru_cache
import argparse
import json
from pathlib import Path
import shutil
import time
import traceback

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel,delayed,parallel_config
from threadpoolctl import threadpool_limits

from . import model_search as ms
from .data import digest,read_inputs,attach_roles
from .models import build_model
from .oct06_research import FB,prepare_frames,metrics,write_json
from .oct08_fusion import TrainECDF

OUT=Path('reports/oct08_crossed_search')
CONFIG=Path('configs/oct08_crossed_search.json')


@lru_cache(maxsize=1)
def config():return json.loads(CONFIG.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def development():return joblib.load(OUT/'development.joblib')


@lru_cache(maxsize=1)
def source():return joblib.load(OUT/'source/model.joblib')


def add_transfer(frame, transform):
    out=frame.copy();s=source()
    out['transfer_score']=s['model'].predict_proba(transform.transform(out[list(s['mapping'].values())]))[:,1]
    return out


def transfer_inner(train):
    a,b=ms.inner_split(train)
    transform=TrainECDF().fit(a[list(config()['mapping'].values())])
    return add_transfer(a,transform),add_transfer(b,transform),transform


def fit(train,features,candidate,seed):
    cfg=config();family=candidate['family']
    if family in ['logistic','random_forest']:
        model=build_model(family,seed,candidate['params'])
        model.fit(train[features],train.y_defect.astype(int))
        return dict(family='baseline',algorithm=family,features=features,model=model,rounds=None)
    if 'transfer_score' not in features:
        return ms.fit_payload(train,features,candidate,seed,cfg)
    # Source is fixed independently; target ECDF for early stopping sees inner-fit only.
    a,b,_=transfer_inner(train)
    pre=ms.Preprocessor(features,family,seed).fit(a)
    x,xv=pre.transform(a),pre.transform(b);y,yv=a.y_defect.astype(int),b.y_defect.astype(int)
    params=candidate['params']
    if family in ['mlp','tabm']:
        _,rounds=ms.train_neural(x,y,family,params,seed,cfg,stop=(xv,yv))
    else:
        model=ms.tree_model(family,params,seed,cfg['max_iterations'],cfg,early=True)
        kwargs=dict(eval_set=[(xv,yv)])
        if family=='catboost':kwargs.update(early_stopping_rounds=cfg['early_stopping_trees'],verbose=False)
        elif family=='xgboost':kwargs['verbose']=False
        else:
            import lightgbm as lgb
            model.set_params(metric='average_precision')
            kwargs.update(eval_metric='average_precision',callbacks=[lgb.early_stopping(cfg['early_stopping_trees'],first_metric_only=True,verbose=False)])
        model.fit(x,y,**kwargs)
        rounds=max(1,int(model.get_best_iteration()+1 if family=='catboost' else model.best_iteration+1 if family=='xgboost' else model.best_iteration_))
    pre=ms.Preprocessor(features,family,seed).fit(train);x=pre.transform(train)
    if family in ['mlp','tabm']:
        state,_=ms.train_neural(x,train.y_defect,family,params,seed,cfg,rounds=rounds)
        return dict(family=family,features=features,preprocessor=pre,state=state,input_dim=x.shape[1],params=params,rounds=rounds)
    model=ms.tree_model(family,params,seed,rounds,cfg)
    if family=='lightgbm':model.set_params(metric='average_precision')
    model.fit(x,train.y_defect.astype(int))
    return dict(family=family,features=features,preprocessor=pre,model=model,rounds=rounds)


def predict(payload,frame):
    if 'transfer_score' in payload['features']:
        frame=add_transfer(frame,payload['target_ecdf'])
    return ms.predict(payload,frame)


def directory(identity,seed):return OUT/'candidates'/identity/str(seed)


def cached(candidate,seed,folder):
    previous=candidate.get('reuse_id')
    if previous is None:return None
    old=Path('reports/oct08_model_search/candidates')/previous/str(seed)
    if not (old/'complete.json').exists():return None
    receipt=json.loads((old/'complete.json').read_text())
    if receipt['status']!='completed' or len(receipt['rows'])!=5:raise ValueError('bad cache')
    rows=[];hashes={}
    for row in receipt['rows']:
        key=f"{row['scheme']}__{row['fold']}"
        dest=folder/key;dest.mkdir(exist_ok=True)
        for name in ['model.joblib','validation.parquet']:
            shutil.copy2(old/key/name,dest/name)
            hashes[str(old/key/name)]=digest(old/key/name)
        rows.append(dict(row,id=candidate['id'],family=candidate['family'],setting_id=candidate['setting_id']))
        write_json(dest/'validation.json',rows[-1])
    result=dict(status='completed',id=candidate['id'],seed=seed,rows=rows,cache_from=str(old),cache_hashes=hashes)
    write_json(folder/'complete.json',result)
    return result


def run_candidate(candidate,seed=17):
    folder=directory(candidate['id'],seed)
    if (folder/'complete.json').exists():return json.loads((folder/'complete.json').read_text())
    folder.mkdir(parents=True,exist_ok=True)
    start=time.monotonic()
    try:
        ms.deadline(config())
        result=cached(candidate,seed,folder)
        if result:return result
        data=development();features=data['sets'][candidate['representation']];rows=[]
        with threadpool_limits(limits=config()['threads_per_job']):
            for key,parts in data['frames'].items():
                ms.deadline(config())
                dest=folder/('__'.join(key));dest.mkdir(exist_ok=True)
                train,val=parts['train'],parts['validation']
                payload=fit(train,features,candidate,seed)
                if 'transfer_score' in features:payload['target_ecdf']=data['transforms'][key]
                p=predict(payload,val);t=float(np.nextafter(np.quantile(p,.8),np.inf))
                payload.update(candidate=candidate,seed=seed,threshold=t)
                joblib.dump(payload,dest/'model.joblib',compress=3)
                frame=val[['row_id','run_id','y_defect']].copy();frame['probability']=p
                frame.to_parquet(dest/'validation.parquet',index=False)
                row=dict(id=candidate['id'],setting_id=candidate['setting_id'],family=candidate['family'],representation=candidate['representation'],
                    seed=seed,scheme=key[0],fold=key[1],rounds=payload['rounds'],**metrics(val.y_defect,p,t,val.row_id))
                write_json(dest/'validation.json',row);rows.append(row)
        result=dict(status='completed',id=candidate['id'],seed=seed,seconds=time.monotonic()-start,rows=rows)
        write_json(folder/'complete.json',result)
    except Exception as e:
        result=dict(status='failed',id=candidate['id'],seed=seed,error=str(e),traceback=traceback.format_exc())
        write_json(folder/'failure.json',result)
    return result


def register():
    OUT.mkdir(parents=True,exist_ok=False)
    cfg=config()
    paths=[CONFIG,Path(__file__),Path(ms.__file__),Path('castguard/oct08_fusion.py'),Path('castguard/oct06_research.py'),
           Path('docs/OCT08_CROSSED_SEARCH_PROTOCOL.md'),Path('configs/oct08_fusion.json')]
    paths += [p for p in Path('data/processed').iterdir() if p.is_file()]
    write_json(OUT/'registration.json',dict(at=datetime.now(timezone.utc).isoformat(),config=cfg,
        hashes={str(p):digest(p) for p in paths},submission_hashes={p.name:digest(p) for p in Path('submission').iterdir() if p.is_file()},
        old_search_seal_sha256=digest('reports/oct08_model_search/selection_seal.json'),
        past_test_exposure=True,test_for_new_selection=False))
    oldreg=json.loads(Path('reports/oct08_model_search/registration.json').read_text(encoding='utf-8'))
    code_key=next(p for p in oldreg['hashes'] if Path(p).resolve()==Path(ms.__file__).resolve())
    if digest(ms.__file__)!=oldreg['hashes'][code_key]:raise ValueError('old training code changed; cache invalid')
    frames,folds,_=read_inputs(Path.cwd())
    s=attach_roles(frames['p40'],folds,'p40','chronological','primary')
    s=s[(s.role=='train')&s.normal_pressure&s.y_defect.notna()]
    transform=TrainECDF().fit(s[list(cfg['mapping'])])
    model=build_model('random_forest',cfg['source_seed'],json.loads(Path('configs/oct08_fusion.json').read_text())['models']['random_forest'])
    model.fit(transform.transform(s[list(cfg['mapping'])]),s.y_defect.astype(int))
    (OUT/'source').mkdir()
    joblib.dump(dict(model=model,transform=transform,mapping=cfg['mapping'],train_row_ids=s.row_id.tolist()),OUT/'source/model.joblib',compress=3)
    frames,sets=prepare_frames(Path.cwd(),cfg)
    sets.update(S_T=sets['S']+['transfer_score'],SH_T=sets['SH']+['transfer_score'],
                S_T_FB=sets['S']+['transfer_score']+FB,SH_T_FB=sets['SH']+['transfer_score']+FB)
    dev={};test={};transforms={}
    old=joblib.load('reports/oct08_model_search/development.joblib')
    for key,f in frames.items():
        for role in ['train','validation']:
            pd.testing.assert_frame_equal(f[f.role==role],old['frames'][key][role])
        for name in ['S','SH','S_FB','SH_FB']:assert sets[name]==old['sets'][name]
        tx=TrainECDF().fit(f.loc[f.role=='train',list(cfg['mapping'].values())]);transforms[key]=tx
        f=add_transfer(f,tx)
        dev[key]={r:f[f.role==r].copy() for r in ['train','validation']}
        test[key]=f[f.role=='test'].copy()
    joblib.dump(dict(frames=dev,sets=sets,transforms=transforms),OUT/'development.joblib',compress=3)
    joblib.dump(test,OUT/'test.joblib',compress=3)
    write_json(OUT/'prepared.json',dict(source_sha256=digest(OUT/'source/model.joblib'),development_sha256=digest(OUT/'development.joblib'),
        test_sha256=digest(OUT/'test.joblib'),cache_inputs_equal=True,source_train_rows=len(s),
        input_counts={k:len(v) for k,v in sets.items()}))
    print('Registered',len(cfg['candidates']),'candidates',flush=True)


def lane(which,finalists=False):
    cfg=config();ms.deadline(cfg,'finalist_deadline' if finalists else 'stage1_deadline')
    if finalists:
        ids=json.loads((OUT/'shortlist.json').read_text())['refit_ids']
        tasks=[(c,s) for c in cfg['candidates'] if c['id'] in ids for s in cfg['seeds'][1:]]
    else:tasks=[(c,17) for c in cfg['candidates']]
    tasks=[(c,s) for c,s in tasks if ((c['family'] in ['mlp','tabm'])==(which=='neural'))]
    jobs=cfg['gpu_jobs'] if which=='neural' else cfg['cpu_jobs']
    started=time.monotonic()
    with parallel_config(backend='loky',inner_max_num_threads=2 if which=='neural' else cfg['threads_per_job']):
        stream=Parallel(n_jobs=jobs,return_as='generator_unordered',pre_dispatch=jobs)(delayed(run_candidate)(c,s) for c,s in tasks)
        for i,r in enumerate(stream,1):
            if i%4==0 or r['status']!='completed' or i==len(tasks):
                print(which,i,len(tasks),r['id'],r['seed'],r['status'],r.get('error',''),round(time.monotonic()-started),flush=True)
    name=f'{which}_'+('refit_done' if finalists else 'done')+'.json'
    write_json(OUT/name,dict(at=datetime.now(timezone.utc).isoformat(),tasks=len(tasks),seconds=time.monotonic()-started))


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['register','cpu','neural','cpu_refit','neural_refit']);a=p.parse_args()
    if a.action=='register':register()
    else:lane(a.action.split('_')[0],a.action.endswith('_refit'))


if __name__=='__main__':
    from castguard.crossed_search import main as entry
    entry()
