"""Independent consequential checks of labels, ranks, selection, causal feedback and preservation."""
from pathlib import Path
import json
import math
import hashlib
import pandas as pd
import numpy as np
from castguard.oct06_research import prepare_frames,write_json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reports/oct06_research'


def independent_ap(y,score):
    q=pd.DataFrame({'y':np.asarray(y,int),'p':np.asarray(score,float)}).groupby('p').agg(n=('y','size'),positive=('y','sum')).sort_index(ascending=False)
    return float(((q.positive.cumsum()/q.n.cumsum())*q.positive).sum()/q.positive.sum())


def main():
    cfg=json.loads((ROOT/'configs/oct06_research.json').read_text())
    reg=json.loads((OUT/'registration.json').read_text(encoding='utf-8'))
    for path,h in reg['hashes'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h,path
    q=pd.read_parquet(ROOT/'data/processed/joined.parquet').set_index('row_id')
    pred=pd.read_parquet(OUT/'selected_predictions.parquet')
    assert np.array_equal(pred.y_defect.to_numpy(),q.loc[pred.row_id,'y_defect'].to_numpy())
    vals=pd.read_csv(OUT/'validation_candidates.csv',dtype={'fold':str})
    selected=json.loads((OUT/'selection.json').read_text())
    assert hashlib.sha256((OUT/'validation_candidates.csv').read_bytes()).hexdigest()==selected['validation_sha256']
    for s in selected['selections']:
        v=vals[(vals.scheme==s['scheme'])&(vals.fold==s['fold'])&(vals.representation==s['representation'])]
        rank=v.groupby('model').ap.mean().reset_index().sort_values(['ap','model'],ascending=[False,True])
        assert rank.iloc[0].model==s['model']
    computed=[]
    metrics=pd.read_csv(OUT/'selected_metrics.csv',dtype={'fold':str})
    for key,g in pred.groupby(['scheme','fold','representation','seed','role']):
        got=metrics[(metrics.scheme==key[0])&(metrics.fold==key[1])&(metrics.representation==key[2])&(metrics.seed==key[3])&(metrics.role==key[4])].iloc[0]
        assert len(g)==got.n and int(g.y_defect.sum())==got.positive
        ap=independent_ap(g.y_defect,g.probability)
        ranked=g.sort_values(['probability','row_id'],ascending=[False,True])
        caught=int(ranked.iloc[:len(g)//5].y_defect.sum())
        assert abs(ap-got.ap)<1e-10 and caught==got.caught20
        prediction=g.probability>=g.threshold
        assert int((prediction & g.y_defect.eq(0)).sum())==got.fp
        computed.append(abs(ap-got.ap))
    frames,_=prepare_frames(ROOT,cfg);checks=0
    for _,f in frames.items():
        for _,v in f[f.role!='excluded'].iloc[::37].iterrows():
            donor=f[(f.run_id==v.run_id)&(f.event_order<=v.event_order-20)&(f.role!='excluded')]
            assert len(donor)==v.fb_known_count
            for width in [20,100]:
                z=donor[donor.event_order>v.event_order-20-width]
                expected=z.y_defect.mean()
                assert np.isclose(expected,v[f'fb_rate{width}'],equal_nan=True)
            checks+=1
    receipt={'passed':True,'preserved_registered_hashes':len(reg['hashes']),'selection_groups':len(selected['selections']),
             'metric_groups':len(computed),'max_independent_ap_error':max(computed),'independent_feedback_records':checks,
             'checks':['raw quality label equality','validation-only model choice','exact top20 rank denominator','normal FPR counts','independent process-event delayed label window','original data and protocol hashes'],
             'boundary':'reused data computational validation; not independent field performance'}
    write_json(OUT/'independent_verification.json',receipt);print(json.dumps(receipt))


if __name__=='__main__':main()
