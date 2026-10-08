"""Time-bounded validation-only model search; test evaluation is a separate sealed phase."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import time
import traceback

import joblib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed, parallel_config
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import OneHotEncoder, QuantileTransformer
from sklearn.metrics import average_precision_score
from threadpoolctl import threadpool_limits

from .data import digest
from .models import build_model
from .oct06_research import prepare_frames, metrics, write_json

OUT = Path('reports/oct08_model_search')
CONFIG = Path('configs/oct08_model_search.json')


def deadline(cfg, key='hard_deadline'):
    if datetime.now(timezone.utc) >= datetime.fromisoformat(cfg[key]):
        raise TimeoutError(key)


def inner_split(train):
    """Chronological tail per run, with a 20-process-event purge before the tail."""
    fit, stop = [], []
    for _, g in train.groupby('run_id', sort=True):
        g = g.sort_values('event_order')
        cut = max(1, int(len(g)*.8))
        tail = g.iloc[cut:]
        if len(tail):
            fit.extend(g.loc[g.event_order < tail.event_order.min()-20].index)
            stop.extend(tail.index)
    a, b = train.loc[fit], train.loc[stop]
    if a.y_defect.nunique() != 2 or b.y_defect.nunique() != 2:
        raise ValueError('inner chronological split lacks classes')
    return a, b


class Preprocessor:
    def __init__(self, features, family, seed):
        self.features, self.family, self.seed = features, family, seed
        self.numeric = [f for f in features if f != 'Product_Type']

    def fit(self, frame):
        self.imputer = SimpleImputer(strategy='median', keep_empty_features=True)
        x = self.imputer.fit_transform(frame[self.numeric])
        if self.family in ['mlp', 'tabm']:
            self.quantile = QuantileTransformer(n_quantiles=min(256,len(frame)), output_distribution='normal', random_state=self.seed)
            self.quantile.fit(x)
        self.encoder = OneHotEncoder(handle_unknown='ignore', sparse_output=False)
        self.encoder.fit(frame[['Product_Type']].astype(str))
        return self

    def transform(self, frame):
        x = self.imputer.transform(frame[self.numeric])
        if self.family == 'catboost':
            result = pd.DataFrame(x, columns=self.numeric, index=frame.index)
            result['Product_Type'] = frame.Product_Type.astype(str)
            return result
        if self.family in ['mlp', 'tabm']:
            x = self.quantile.transform(x)
        return np.column_stack([x, self.encoder.transform(frame[['Product_Type']].astype(str))]).astype(np.float32)


def neural_model(n_features, family, params):
    import torch.nn as nn
    if family == 'tabm':
        from tabm import TabM
        extra = {}
        if params['embeddings']:
            from rtdl_num_embeddings import LinearReLUEmbeddings
            extra['num_embeddings'] = LinearReLUEmbeddings(n_features, d_embedding=8)
        return TabM.make(n_num_features=n_features, d_out=1, n_blocks=params['depth'],
                         d_block=params['width'], dropout=params['dropout'], k=params['k'], **extra)
    layers = []
    width = n_features
    for _ in range(params['depth']):
        layers += [nn.Linear(width, params['width']), nn.ReLU(), nn.Dropout(params['dropout'])]
        width = params['width']
    return nn.Sequential(*layers, nn.Linear(width, 1))


def train_neural(x, y, family, params, seed, cfg, stop=None, rounds=None):
    import torch
    import torch.nn.functional as F
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    if not torch.cuda.is_available():
        raise RuntimeError('Registered CUDA neural lane unavailable')
    model = neural_model(x.shape[1], family, params).to('cuda')
    optimizer = torch.optim.AdamW(model.parameters(), lr=params['lr'], weight_decay=params['weight_decay'])
    tx = torch.as_tensor(x, device='cuda')
    ty = torch.as_tensor(np.asarray(y,np.float32), device='cuda')
    vx = torch.as_tensor(stop[0], device='cuda') if stop is not None else None
    best, best_epoch, best_state, stale = -np.inf, 0, None, 0
    for epoch in range(1, (rounds or cfg['max_epochs'])+1):
        deadline(cfg)
        model.train()
        indices = torch.randperm(len(tx), device='cuda')
        for idx in indices.split(params['batch_size']):
            optimizer.zero_grad(set_to_none=True)
            logits = model(tx[idx]).reshape(len(idx), -1)
            loss = F.binary_cross_entropy_with_logits(logits, ty[idx,None].expand_as(logits))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
        if stop is not None:
            model.eval()
            with torch.no_grad():
                prob = model(vx).reshape(len(vx),-1).sigmoid().mean(1).cpu().numpy()
            ap = average_precision_score(stop[1], prob)
            if ap > best + 1e-8:
                best, best_epoch, stale = ap, epoch, 0
                best_state = {k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
            else:
                stale += 1
            if stale >= cfg['early_stopping_nn']:
                break
    if stop is not None:
        model.load_state_dict(best_state)
    state = {k:v.detach().cpu() for k,v in model.state_dict().items()}
    del model, optimizer, tx, ty
    torch.cuda.empty_cache()
    return state, best_epoch if stop is not None else rounds


def tree_model(family, params, seed, rounds, cfg, early=False):
    common = dict(**params)
    if family == 'catboost':
        from catboost import CatBoostClassifier
        return CatBoostClassifier(**common, iterations=rounds, random_seed=seed, thread_count=cfg['threads_per_job'],
            loss_function='Logloss', eval_metric='PRAUC', verbose=False, allow_writing_files=False,
            cat_features=['Product_Type'], task_type='CPU')
    if family == 'xgboost':
        from xgboost import XGBClassifier
        return XGBClassifier(**common, n_estimators=rounds, random_state=seed, n_jobs=cfg['threads_per_job'],
            tree_method='hist', device='cpu', eval_metric='aucpr',
            **({'early_stopping_rounds':cfg['early_stopping_trees']} if early else {}))
    from lightgbm import LGBMClassifier
    return LGBMClassifier(**common, n_estimators=rounds, random_state=seed, n_jobs=cfg['threads_per_job'],
        verbosity=-1, deterministic=True, force_col_wise=True, subsample_freq=1)


def fit_payload(train, features, candidate, seed, cfg):
    family, params = candidate['family'], candidate['params']
    if family == 'baseline':
        model = build_model('logistic', seed, {'C':.3, 'max_iter':3000})
        model.fit(train[features], train.y_defect.astype(int))
        return dict(family=family, features=features, model=model, rounds=None)
    inner, stop = inner_split(train)
    pre = Preprocessor(features, family, seed).fit(inner)
    x, xv = pre.transform(inner), pre.transform(stop)
    y, yv = inner.y_defect.astype(int), stop.y_defect.astype(int)
    if family in ['mlp','tabm']:
        _, rounds = train_neural(x, y, family, params, seed, cfg, stop=(xv,yv))
    else:
        model = tree_model(family,params,seed,cfg['max_iterations'],cfg,early=True)
        kwargs = dict(eval_set=[(xv,yv)])
        if family == 'catboost':
            kwargs.update(early_stopping_rounds=cfg['early_stopping_trees'], verbose=False)
        elif family == 'xgboost':
            kwargs['verbose'] = False
        else:
            import lightgbm as lgb
            kwargs.update(eval_metric='average_precision',callbacks=[lgb.early_stopping(cfg['early_stopping_trees'], first_metric_only=True, verbose=False)])
            model.set_params(metric='average_precision')
        model.fit(x,y,**kwargs)
        rounds = (model.get_best_iteration()+1 if family=='catboost' else
                  model.best_iteration+1 if family=='xgboost' else model.best_iteration_)
        rounds = max(1,int(rounds))
    pre = Preprocessor(features, family, seed).fit(train)
    x = pre.transform(train)
    if family in ['mlp','tabm']:
        state, _ = train_neural(x, train.y_defect, family, params, seed, cfg, rounds=rounds)
        return dict(family=family,features=features,preprocessor=pre,state=state,input_dim=x.shape[1],params=params,rounds=rounds)
    model = tree_model(family,params,seed,rounds,cfg)
    if family=='lightgbm': model.set_params(metric='average_precision')
    model.fit(x,train.y_defect.astype(int))
    return dict(family=family,features=features,preprocessor=pre,model=model,rounds=rounds)


def predict(payload, frame):
    family = payload['family']
    if family == 'baseline':
        return payload['model'].predict_proba(frame[payload['features']])[:,1]
    x = payload['preprocessor'].transform(frame)
    if family in ['mlp','tabm']:
        import torch
        torch.set_num_threads(2)
        model = neural_model(payload['input_dim'],family,payload['params']).to('cuda')
        model.load_state_dict(payload['state'])
        model.eval()
        with torch.no_grad():
            p = model(torch.as_tensor(x,device='cuda')).reshape(len(x),-1).sigmoid().mean(1).cpu().numpy()
        del model
        return p.astype(float)
    return payload['model'].predict_proba(x)[:,1]


def candidate_dir(candidate, seed):
    return OUT/'candidates'/candidate['id']/str(seed)


def run_candidate(candidate, seed=17):
    cfg = json.loads(CONFIG.read_text())
    folder = candidate_dir(candidate,seed)
    if (folder/'complete.json').exists():
        return json.loads((folder/'complete.json').read_text())
    folder.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    try:
        deadline(cfg)
        data = joblib.load(OUT/'development.joblib')
        rows=[]
        with threadpool_limits(limits=cfg['threads_per_job']):
            for (scheme,fold), part in data['frames'].items():
                deadline(cfg)
                dest=folder/f'{scheme}__{fold}'
                dest.mkdir(exist_ok=True)
                if (dest/'validation.json').exists():
                    rows.append(json.loads((dest/'validation.json').read_text()))
                    continue
                train,val=part['train'],part['validation']
                payload=fit_payload(train,data['sets'][candidate['representation']],candidate,seed,cfg)
                p=predict(payload,val)
                threshold=float(np.nextafter(np.quantile(p,.8),np.inf))
                payload.update(candidate=candidate,seed=seed,threshold=threshold)
                joblib.dump(payload,dest/'model.joblib',compress=3)
                pred=val[['row_id','run_id','y_defect']].copy();pred['probability']=p
                pred.to_parquet(dest/'validation.parquet',index=False)
                row=dict(id=candidate['id'],family=candidate['family'],representation=candidate['representation'],seed=seed,
                         scheme=scheme,fold=fold,rounds=payload['rounds'],**metrics(val.y_defect,p,threshold,val.row_id))
                write_json(dest/'validation.json',row);rows.append(row)
        receipt=dict(status='completed',id=candidate['id'],seed=seed,seconds=time.monotonic()-started,rows=rows)
        write_json(folder/'complete.json',receipt)
    except Exception as exc:
        receipt=dict(status='failed',id=candidate['id'],seed=seed,error=str(exc),traceback=traceback.format_exc())
        write_json(folder/'failure.json',receipt)
    return receipt


def register():
    OUT.mkdir(parents=True,exist_ok=False)
    cfg=json.loads(CONFIG.read_text())
    paths=[CONFIG,Path('docs/OCT08_MODEL_SEARCH_PROTOCOL.md'),Path(__file__),Path('castguard/oct06_research.py')]
    paths += [p for p in Path('data/processed').iterdir() if p.is_file()]
    submission={p.name:digest(p) for p in Path('submission').iterdir() if p.is_file()}
    write_json(OUT/'registration.json',dict(at=datetime.now(timezone.utc).isoformat(),config=cfg,
        hashes={str(p):digest(p) for p in paths},submission_hashes=submission,
        independent_test=False,test_selection=False))
    frames,sets=prepare_frames(Path.cwd(),cfg)
    dev={k:{r:f[f.role==r].copy() for r in ['train','validation']} for k,f in frames.items()}
    test={k:f[f.role=='test'].copy() for k,f in frames.items()}
    joblib.dump(dict(frames=dev,sets=sets),OUT/'development.joblib',compress=3)
    joblib.dump(test,OUT/'test.joblib',compress=3)
    audit=[]
    for (scheme,fold),parts in dev.items():
        a,b=inner_split(parts['train'])
        audit.append(dict(scheme=scheme,fold=fold,train=len(parts['train']),validation=len(parts['validation']),inner_fit=len(a),inner_stop=len(b)))
    write_json(OUT/'split_audit.json',audit)
    print('Registered',len(cfg['candidates']),'candidates',flush=True)


def lane(which):
    cfg=json.loads(CONFIG.read_text())
    candidates=[c for c in cfg['candidates'] if ((c['family'] in ['mlp','tabm']) == (which=='neural'))]
    started=time.monotonic()
    if which=='cpu':
        candidates=[dict(id='baseline',family='baseline',representation='S_FB',params={})]+candidates
    def pending():
        for c in candidates:
            deadline(cfg,'stage1_deadline')
            yield c
    if which=='cpu':
        with parallel_config(backend='loky',inner_max_num_threads=cfg['threads_per_job']):
            stream=Parallel(n_jobs=cfg['cpu_jobs'],return_as='generator_unordered',pre_dispatch=cfg['cpu_jobs'])(delayed(run_candidate)(c) for c in pending())
            for i,r in enumerate(stream,1):
                print(which,i,len(candidates),r['id'],r['status'],r.get('error',''),round(time.monotonic()-started),flush=True)
    else:
        for i,c in enumerate(pending(),1):
            r=run_candidate(c)
            print(which,i,len(candidates),r['id'],r['status'],r.get('error',''),round(time.monotonic()-started),flush=True)
    write_json(OUT/f'{which}_done.json',dict(at=datetime.now(timezone.utc).isoformat(),seconds=time.monotonic()-started))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['register','cpu','neural'])
    arg=parser.parse_args()
    if arg.action=='register':register()
    else:lane(arg.action)


if __name__=='__main__':
    from castguard.model_search import main as entry
    entry()
