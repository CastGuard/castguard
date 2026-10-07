"""Deterministic genuine error cases and explicit invalid-input scenarios."""
from pathlib import Path
import copy
import json
import numpy as np
import pandas as pd
from castguard.oct06_research import prepare_frames, write_json, FB
from castguard.submission_reader import ResearchReader, features_from_packet, PROCESS, SENSORS, SCHEMA, render_html

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reports/oct06_research'


def packet(row, frame, timeline):
    t=int(row.event_order);run=int(row.run_id);rk=f'run-{run}'
    past=timeline[(timeline.run_id==run)&(timeline.event_order>=max(0,t-20))&(timeline.event_order<t)]
    observed=frame[(frame.run_id==run)&(frame.event_order<=t-20)&(frame.role!='excluded')]
    finite=lambda v:float(v) if pd.notna(v) else None
    return {'record_id':row.row_id,'run_key':rk,'event_order':t,'shot':int(row.Shot),
        'product_type':int(row.Product_Type),'measurements':{c:finite(row[c]) for c in PROCESS+SENSORS},
        'process_history':[{'run_key':rk,'event_order':int(h.event_order),'shot':int(h.Shot),
                            'measurements':{c:finite(h[c]) for c in PROCESS}} for _,h in past.iterrows()],
        'feedback_ledger_complete':True,
        'quality_feedback':[{'run_key':rk,'event_order':int(h.event_order),'available_event':int(h.event_order)+20,
                             'defect':int(h.y_defect)} for _,h in observed.iterrows()]}


def main():
    cfg=json.loads((ROOT/'configs/oct06_research.json').read_text())
    frames,_=prepare_frames(ROOT,cfg);f=frames[('within_run','primary')]
    m=pd.read_parquet(ROOT/'data/processed/m41_timeline.parquet').sort_values(['run_id','source_row'])
    m['event_order']=m.groupby('run_id').cumcount()
    examples=pd.read_csv(OUT/'diagnostic_examples.csv');records=[];provenance=[]
    for _,row in examples.iterrows():
        q=f[f.row_id==row.row_id].iloc[0];records.append(packet(q,f,m))
        provenance.append({'record_id':row.row_id,'source_row_id':row.row_id,'case':row.error_type,'selection':'lexicographically first post-hoc error class; diagnostic only'})
    first=f[(f.role=='test')&f[PROCESS+SENSORS].notna().all(axis=1)].sort_values(['run_id','event_order']).groupby('Product_Type').head(1)
    for _,q in first.iterrows():
        if q.row_id not in [x['record_id'] for x in records]:
            records.append(packet(q,f,m));provenance.append({'record_id':q.row_id,'source_row_id':q.row_id,'case':'first_complete_by_product','selection':'fixed order, not prediction success'})
    base=records[0]
    for label in ['missing_measurement','unseen_product','future_feedback','current_label','no_feedback']:
        x=copy.deepcopy(base);x['record_id']=label;x['run_key']=label
        for h in x['process_history']+x['quality_feedback']:h['run_key']=label
        if label=='missing_measurement':x['measurements'].pop('Casting_Pressure')
        elif label=='unseen_product':x['product_type']=999
        elif label=='future_feedback':x['quality_feedback'].append({'run_key':label,'event_order':x['event_order'],'available_event':x['event_order']+20,'defect':1})
        elif label=='current_label':x['y_defect']=1
        else:x['quality_feedback']=[]
        records.append(x);provenance.append({'record_id':label,'source_row_id':base['record_id'],'case':'explicit synthetic variant','selection':'functional failure scenario; not new production observation'})
    env={'schema_version':SCHEMA,'records':records}
    examples_path=ROOT/'examples/submission_reader';examples_path.mkdir(parents=True,exist_ok=True)
    write_json(examples_path/'shots.json',env);write_json(examples_path/'provenance.json',provenance)
    reader=ResearchReader(ROOT);result=reader.review(env)
    write_json(OUT/'demo_output.json',result);(OUT/'demo.html').write_text(render_html(result),encoding='utf-8')
    # Twenty fixed chronological test observations: compare runtime vs stored selected predictions.
    stored=pd.read_parquet(OUT/'selected_predictions.parquet');sp=stored[(stored.scheme=='within_run')&(stored.role=='test')&(stored.seed==17)&(stored.representation=='S_FB')].set_index('row_id')
    checked=[]
    for _,q in f[(f.role=='test')&f[PROCESS+SENSORS].notna().all(axis=1)].sort_values(['run_id','event_order']).iloc[::60].head(24).iterrows():
        x=packet(q,f,m);v,_=features_from_packet(x,reader.payload['features'])
        for c in reader.payload['features']:
            assert np.isclose(v[c],q[c],equal_nan=True),c
        rr=reader.review({'schema_version':SCHEMA,'records':[x]})['records'][0]
        assert rr['quality'] is not None,rr
        error=abs(rr['quality']['score']-float(sp.loc[q.row_id,'probability']))
        assert error<1e-10
        checked.append({'row_id':q.row_id,'absolute_error':error,'status':rr['status']})
    variants={x['record_id']:x for x in result['records']}
    assert variants['missing_measurement']['quality'] is None
    assert variants['future_feedback']['quality'] is None
    assert variants['current_label']['quality'] is None
    assert variants['unseen_product']['action']=='manual_review' or variants['unseen_product']['action']=='manual_quality_and_equipment_review'
    assert 'unseen_product' in variants['unseen_product']['warnings']
    assert variants['no_feedback']['action'].startswith('manual')
    write_json(OUT/'demo_verification.json',{'passed':True,'rows':checked,'max_prediction_error':max(x['absolute_error'] for x in checked),'synthetic_invalid_cases':5,
        'checks':['runtime features equal research features','stored prediction replay','current label rejected','future label rejected','missing input abstention','unseen product warning','zero feedback manual review'],
        'no_new_independent_data':True})
    print('demo records',len(records),'prediction replays',len(checked),'max error',max(x['absolute_error'] for x in checked))


if __name__=='__main__':main()
