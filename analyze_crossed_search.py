"""Factorial model/data analysis, with fixed-configuration and equally tuned comparisons."""
import argparse
from datetime import datetime,timezone
import itertools
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from castguard import crossed_search as c
from castguard.oct06_research import metrics,write_json
from castguard.data import digest
from analyze_model_search import ranking

OUT=c.OUT


def get_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def shortlist():
    if (OUT/'shortlist.json').exists():raise FileExistsError('Shortlist immutable')
    if not all((OUT/f'{lane}_done.json').exists() for lane in ['cpu','neural']):raise ValueError('lanes incomplete')
    cfg=c.config();base=pd.DataFrame(get_json(c.directory('logistic_fixed__S',17)/'complete.json')['rows'])
    rows=[];all_metrics=[];failures=[]
    for candidate in cfg['candidates']:
        path=c.directory(candidate['id'],17)/'complete.json'
        if not path.exists():failures.append(candidate['id']);continue
        receipt=get_json(path);part=pd.DataFrame(receipt['rows'])
        assert len(part)==5
        rows.append(dict(id=candidate['id'],setting_id=candidate['setting_id'],family=candidate['family'],
            representation=candidate['representation'],**ranking(part,base)))
        all_metrics.extend(receipt['rows'])
    ranked=pd.DataFrame(rows).sort_values(['objective','within_ap','id'],ascending=[False,False,True])
    chosen=ranked.groupby(['representation','family'],sort=True).head(1)
    lookup={r['id']:r for r in cfg['candidates']}
    anchors={};selected={};ids=set()
    for rep in cfg['representations']:
        selected[rep]={r.family:r.id for r in chosen[chosen.representation==rep].itertuples()}
        ids.update(selected[rep].values())
    for root,reps in [('S',['S','SH','S_T','SH_T']),('S_FB',['S_FB','SH_FB','S_T_FB','SH_T_FB'])]:
        anchors[root]={}
        for family,identity in selected[root].items():
            setting=lookup[identity]['setting_id']
            anchors[root][family]={rep:setting+'__'+rep for rep in reps}
            ids.update(anchors[root][family].values())
    ranked.to_csv(OUT/'stage1_ranking.csv',index=False)
    pd.DataFrame(all_metrics).to_csv(OUT/'stage1_metrics.csv',index=False)
    write_json(OUT/'shortlist.json',dict(at=datetime.now(timezone.utc).isoformat(),selected=selected,anchors=anchors,
        refit_ids=sorted(ids),failures=failures,ranking_sha256=digest(OUT/'stage1_ranking.csv'),test_used=False))
    print('Selected model/representation groups',len(chosen),'refit settings including locked anchors',len(ids),'failures',len(failures),flush=True)
    print(chosen[['representation','family','id','within_ap','objective']].sort_values(['representation','family']).to_string(index=False),flush=True)


def components(role):
    if role=='test' and not (OUT/'selection_seal.json').exists():raise ValueError('test forbidden before selection seal')
    keys=list(c.development()['frames']);cfg=c.config();short=get_json(OUT/'shortlist.json')
    ids=short['refit_ids'];data={};hashes={};test=joblib.load(OUT/'test.joblib') if role=='test' else None
    for identity in ids:
        data[identity]={}
        for key in keys:
            frames=[]
            for seed in cfg['seeds']:
                folder=c.directory(identity,seed)/('__'.join(key))
                hashes[str(folder/'model.joblib')]=digest(folder/'model.joblib')
                if role=='validation':frame=pd.read_parquet(folder/'validation.parquet')
                else:
                    payload=joblib.load(folder/'model.joblib')
                    frame=test[key][['row_id','run_id','y_defect']].copy()
                    frame['probability']=c.predict(payload,test[key])
                    frame.to_parquet(folder/'test.parquet',index=False)
                frames.append(frame)
            for f in frames[1:]:
                np.testing.assert_array_equal(frames[0].row_id,f.row_id)
                np.testing.assert_array_equal(frames[0].y_defect,f.y_defect)
            mean=frames[0].copy();mean['probability']=np.mean([f.probability.to_numpy() for f in frames],axis=0)
            data[identity][key]=mean
    return data,hashes


def mix(components,weights,key):
    f=components[next(iter(weights))][key].copy()
    for identity in weights:
        np.testing.assert_array_equal(f.row_id,components[identity][key].row_id)
        np.testing.assert_array_equal(f.y_defect,components[identity][key].y_defect)
    f['probability']=sum(w*components[i][key].probability.to_numpy() for i,w in weights.items())
    return f


def variants(rep,selected):
    ids=sorted(selected.values());out={f'{rep}::single::{i}':{i:1.} for i in ids}
    for a,b in itertools.combinations(ids,2):
        for w in [.25,.5,.75]:out[f'{rep}::blend::{a}::{b}::{w}']={a:w,b:1-w}
    nonlog=[i for f,i in selected.items() if f!='logistic']
    out[f'{rep}::mean_nonlogistic']={i:1/len(nonlog) for i in nonlog}
    out[f'{rep}::mean_all']={i:1/len(ids) for i in ids}
    return out


def summarize_frame(identity,key,frame,threshold):
    return dict(id=identity,scheme=key[0],fold=key[1],**metrics(frame.y_defect,frame.probability,threshold,frame.row_id))


def compare(a,b):
    return ranking(pd.DataFrame(a),pd.DataFrame(b))


def seal():
    if (OUT/'selection_seal.json').exists():raise FileExistsError('immutable seal exists')
    if not all((OUT/f'{lane}_refit_done.json').exists() for lane in ['cpu','neural']):raise ValueError('refits incomplete')
    short=get_json(OUT/'shortlist.json');data,hashes=components('validation');keys=list(next(iter(data.values())))
    metric_rows=[];rank_rows=[];definitions={};thresholds={};component_thresholds={}
    component_rows=[];base=[]
    for identity,parts in data.items():
        component_thresholds[identity]={}
        for key,f in parts.items():
            t=float(np.nextafter(np.quantile(f.probability,.8),np.inf));component_thresholds[identity]['__'.join(key)]=t
            row=summarize_frame(identity,key,f,t);component_rows.append(row)
            if identity=='logistic_fixed__S':base.append(row)
    baseline=pd.DataFrame(base)
    for rep,chosen in short['selected'].items():
        defs=variants(rep,chosen);definitions.update(defs)
        for identity,weights in defs.items():
            rows=[];thresholds[identity]={}
            for key in keys:
                f=mix(data,weights,key);t=float(np.nextafter(np.quantile(f.probability,.8),np.inf))
                thresholds[identity]['__'.join(key)]=t
                rows.append(dict(representation=rep,**summarize_frame(identity,key,f,t)))
            metric_rows.extend(rows)
            rank_rows.append(dict(id=identity,representation=rep,**ranking(pd.DataFrame(rows),baseline)))
    table=pd.DataFrame(rank_rows).sort_values(['objective','within_ap','id'],ascending=[False,False,True])
    chosen=table.groupby('representation',sort=True).head(1)
    winners=dict(zip(chosen.representation,chosen.id))
    main=chosen[~chosen.representation.str.endswith('_FB')].iloc[0].id
    feedback=chosen[chosen.representation.str.endswith('_FB')].iloc[0].id
    table.to_csv(OUT/'ensemble_validation_ranking.csv',index=False)
    pd.DataFrame(metric_rows).to_csv(OUT/'ensemble_validation_metrics.csv',index=False)
    pd.DataFrame(component_rows).to_csv(OUT/'component_validation_metrics.csv',index=False)
    matrix=[]
    for rep,families in short['selected'].items():
        for family,identity in families.items():
            for row in component_rows:
                if row['id']==identity:matrix.append(dict(representation=rep,family=family,**row))
    pd.DataFrame(matrix).to_csv(OUT/'model_matrix_validation.csv',index=False)
    decisions=[]
    for tier,reps,root in [('no_feedback',['S','SH','S_T','SH_T'],'S'),('feedback',['S_FB','SH_FB','S_T_FB','SH_T_FB'],'S_FB')]:
        reference=[r for r in metric_rows if r['id']==winners[root]]
        for rep in reps:
            part=[r for r in metric_rows if r['id']==winners[rep]]
            decisions.append(dict(representation=rep,tier=tier,reference_representation=root,**compare(part,reference)))
    write_json(OUT/'selection_seal.json',dict(at=datetime.now(timezone.utc).isoformat(),
        winners=winners,primary_winner=main,feedback_winner=feedback,definitions=definitions,thresholds=thresholds,
        component_thresholds=component_thresholds,model_hashes=hashes,source_sha256=digest(OUT/'source/model.joblib'),
        validation_ranking_sha256=digest(OUT/'ensemble_validation_ranking.csv'),analysis_sha256=digest(Path(__file__)),
        inference_sha256=digest('castguard/crossed_reader.py'),
        ranking_helper_sha256=digest('analyze_model_search.py'),
        decisions=decisions,baseline='logistic_fixed__S: pure current #42, no history/transfer/feedback',
        strong_single_data_reference=winners['S'],past_test_exposure=True,test_used_for_current_selection=False,
        old_reader_replacement=False))
    print(chosen[['representation','id','within_ap','within_capture','objective']].to_string(index=False),flush=True)
    print('PRIMARY',main,'FEEDBACK',feedback,flush=True)
    print(pd.DataFrame(decisions)[['representation','within_ap_gain','within_capture_gain','forward_consistent','qualifies']].to_string(index=False),flush=True)


def bootstrap(a,b,rng):
    np.testing.assert_array_equal(a.row_id,b.row_id)
    runs=np.unique(a.run_id);values=[];captures=[]
    for _ in range(1000):
        ix=np.concatenate([np.flatnonzero(a.run_id.to_numpy()==r) for r in rng.choice(runs,len(runs),replace=True)])
        y=a.y_defect.to_numpy()[ix]
        if len(np.unique(y))<2:continue
        pa,pb=a.probability.to_numpy()[ix],b.probability.to_numpy()[ix]
        values.append(average_precision_score(y,pa)-average_precision_score(y,pb))
        ids=a.row_id.to_numpy()[ix].astype(str);k=len(y)//5
        ia=np.lexsort((ids,-pa));ib=np.lexsort((ids,-pb))
        captures.append((int(y[ia[:k]].sum())-int(y[ib[:k]].sum()))/y.sum())
    return dict(ap_difference=float(average_precision_score(a.y_defect,a.probability)-average_precision_score(b.y_defect,b.probability)),
        ap_interval95=np.quantile(values,[.025,.975]).tolist(),capture_interval95=np.quantile(captures,[.025,.975]).tolist(),runs=len(runs),replicates=len(values))


def evaluate():
    seal=get_json(OUT/'selection_seal.json');short=get_json(OUT/'shortlist.json')
    if (OUT/'combo_test.csv').exists():raise FileExistsError('test results exist')
    for p,h in seal['model_hashes'].items():assert digest(p)==h,p
    assert digest(OUT/'source/model.joblib')==seal['source_sha256']
    data,_=components('test');keys=list(next(iter(data.values())));rows=[];preds=[]
    for identity,parts in data.items():
        for key,f in parts.items():
            t=seal['component_thresholds'][identity]['__'.join(key)]
            rows.append(summarize_frame(identity,key,f,t))
    pd.DataFrame(rows).to_csv(OUT/'component_test_metrics.csv',index=False)
    matrix=[];locked=[]
    for rep,families in short['selected'].items():
        for family,identity in families.items():
            matrix.extend(dict(representation=rep,family=family,**r) for r in rows if r['id']==identity)
    for root,families in short['anchors'].items():
        for family,reps in families.items():
            for rep,identity in reps.items():
                locked.extend(dict(reference_representation=root,representation=rep,family=family,**r) for r in rows if r['id']==identity)
    pd.DataFrame(matrix).to_csv(OUT/'model_matrix_test.csv',index=False)
    pd.DataFrame(locked).to_csv(OUT/'locked_settings_test.csv',index=False)
    combos=[]
    for rep,identity in seal['winners'].items():
        for key in keys:
            f=mix(data,seal['definitions'][identity],key)
            t=seal['thresholds'][identity]['__'.join(key)]
            combos.append(dict(representation=rep,**summarize_frame(identity,key,f,t)))
            f['id']=identity;f['representation']=rep;f['scheme']=key[0];f['fold']=key[1];f['threshold']=t;preds.append(f)
    pd.DataFrame(combos).to_csv(OUT/'combo_test.csv',index=False)
    pd.concat(preds,ignore_index=True).to_parquet(OUT/'combo_test_predictions.parquet',index=False)
    delta=[];uncertainty=[];key=('within_run','primary');rng=np.random.default_rng(202610082)
    for rep,identity in seal['winners'].items():
        root='S_FB' if rep.endswith('_FB') else 'S'
        ref=seal['winners'][root]
        a=mix(data,seal['definitions'][identity],key);b=mix(data,seal['definitions'][ref],key)
        am=pd.DataFrame([r for r in combos if r['representation']==rep]);bm=pd.DataFrame([r for r in combos if r['representation']==root])
        delta.append(dict(representation=rep,reference=root,**ranking(am,bm)))
        if rep!=root:uncertainty.append(dict(representation=rep,reference=root,**bootstrap(a,b,rng)))
    a=mix(data,seal['definitions'][seal['winners']['S']],key);b=data['logistic_fixed__S'][key]
    uncertainty.append(dict(representation='S_tuned',reference='S_logistic',**bootstrap(a,b,rng)))
    pd.DataFrame(delta).to_csv(OUT/'data_added_test_differences.csv',index=False)
    write_json(OUT/'uncertainty.json',dict(method='paired within-run block bootstrap; exploratory reused test; conditional on prior tuning/selection',comparisons=uncertainty))
    print(pd.DataFrame(combos).query("scheme=='within_run'")[['representation','ap','auc','capture20','caught20','fpr']].to_string(index=False),flush=True)
    print('B0',pd.DataFrame(rows).query("id=='logistic_fixed__S' and scheme=='within_run'")[['ap','auc','capture20','caught20']].to_string(index=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['shortlist','seal','evaluate']);a=p.parse_args()
    globals()[a.action]()
