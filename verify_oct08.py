"""Cross-check stored predictions, fixed denominators and unchanged JH baseline metrics."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from castguard.data import digest

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reports/oct08_fusion'


def verify():
    m=pd.read_csv(OUT/'metrics.csv',dtype={'fold':str},float_precision='round_trip')
    p=pd.read_parquet(OUT/'predictions.parquet')
    keys=['scheme','fold','representation','model','seed','role']
    assert len(m)==480
    errors=[]
    for key,g in p.groupby(keys):
        row=m
        for k,v in zip(keys,key):row=row[row[k]==v]
        assert len(row)==1
        row=row.iloc[0]
        assert g.row_id.is_unique and len(g)==row.n and int(g.y_defect.sum())==row.positive
        assert g.threshold.nunique()==1
        y=g.y_defect.to_numpy(int);prob=g.probability.to_numpy(float)
        rank=np.lexsort((g.row_id.astype(str),-prob))
        caught=int(y[rank[:int(len(g)*.2)]].sum())
        predicted=prob>=row.threshold
        assert caught==row.caught20
        for name,value in [('tp',int((predicted&(y==1)).sum())),('fp',int((predicted&(y==0)).sum())),
                           ('fn',int((~predicted&(y==1)).sum())),('tn',int((~predicted&(y==0)).sum()))]:
            assert value==row[name]
        errors += [abs(average_precision_score(y,prob)-row.ap),abs(roc_auc_score(y,prob)-row.auc)]
    old=pd.read_csv(ROOT/'reports/oct06_research/selected_metrics.csv',dtype={'fold':str},float_precision='round_trip')
    pair=m.merge(old,on=keys,suffixes=('_new','_old'),validate='one_to_one')
    cols=['ap','auc','threshold','tp','fp','fn','tn','caught20','capture20']
    baseline_delta=max(float((pair[c+'_new']-pair[c+'_old']).abs().max()) for c in cols)
    assert len(pair)>0 and baseline_delta<1e-12
    r=pd.read_csv(ROOT/'reports/oct08_fusion_reproduction/metrics.csv',dtype={'fold':str},float_precision='round_trip')
    replay=m.merge(r,on=keys,suffixes=('_first','_replay'),validate='one_to_one')
    assert len(replay)==len(m)
    replay_delta=max(float((replay[c+'_first']-replay[c+'_replay']).abs().max()) for c in cols)
    assert replay_delta<1e-12
    first_reg=json.loads((OUT/'registration.json').read_text(encoding='utf-8'))
    for path,h in first_reg['hashes'].items():
        current=ROOT/path
        if path=='castguard/oct08_fusion.py':
            current=ROOT/'reports/oct08_submission/before/oct08_fusion_initial.py'
        assert digest(current)==h,path
    reg=json.loads((ROOT/'reports/oct08_fusion_reproduction/registration.json').read_text(encoding='utf-8'))
    for path,h in reg['hashes'].items():assert digest(ROOT/path)==h,path
    seal=json.loads((OUT/'validation_seal.json').read_text())
    assert digest(OUT/'validation_metrics.csv')==seal['sha256']
    # Same rows and labels across all eight representations, models and seeds.
    for _,g in p.groupby(['scheme','fold','role']):
        assert g.groupby('row_id').y_defect.nunique().max()==1
        assert g.groupby('row_id').size().nunique()==1
    result={'passed':True,'metric_groups':len(m),'maximum_metric_error':max(errors),
            'unchanged_oct06_baseline_groups':len(pair),'maximum_baseline_difference':baseline_delta,
            'full_replay_groups':len(replay),'maximum_replay_difference':replay_delta,
            'original_input_hashes_preserved':True,'validation_seal_valid':True,
            'code_revision':'Initial code preserved; final code adds explicit post-deadline reproduction mode and 45 minute cap only',
            'not_independent_performance_validation':True}
    (OUT/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))


if __name__=='__main__':verify()
