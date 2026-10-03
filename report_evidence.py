"""Bind report values to frozen evidence with selectors, units, and hashes."""
from pathlib import Path
from hashlib import sha256
import json
import pandas as pd

ROOT=Path(__file__).resolve().parent
def sha(path): return sha256(path.read_bytes()).hexdigest()

def collect(root=ROOT):
    facts={}
    def add(key,value,path,selector,unit='value',fmt='.3f',mult=1):
        shown=format(value*mult,fmt) if isinstance(value,(float,int)) else str(value)
        facts[key]={'value':value,'display':shown,'unit':unit,'source':path,'selector':selector,'sha256':sha(root/path)}
    p='reports/oct03_evidence/final/lineage_audit.json'; a=json.loads((root/p).read_text(encoding='utf-8'))
    for key,name in [('Q_RAW','q42'),('M_RAW','m41'),('P_RAW','p40')]: add(key,a['raw_shapes'][name][0],p,f'raw_shapes.{name}[0]','rows',',d')
    for key,field in [('DUPLICATES','q42_duplicate_rows_removed'),('Q_POS','q42_positive_shots'),('WARM_Q','warm_state_code_1_quality_rows')]: add(key,a[field],p,field,'rows',',d')
    add('Q_N',a['join']['quality_rows'],p,'join.quality_rows','shots',',d'); add('JOIN_VALUES',a['join']['process_values_equal_nonmissing'],p,'join.process_values_equal_nonmissing','cells',',d')
    p='reports/oct02/ablation_summary.csv'; frame=pd.read_csv(root/p,dtype={'fold':str})
    for variant in ['A0','A','B']:
        row=frame.loc[(frame.dataset=='q42')&(frame.population=='all')&(frame.scheme=='within_run')&(frame.experiment==variant)].squeeze()
        for measure in ['ap','auc']:
            add(f'{variant}_{measure.upper()}',float(row[measure+'_mean']),p,f'q42/all/within_run/primary/{variant}.{measure}_mean','5-seed mean','.4f')
        if variant=='A':
            add('OLD_TEST_N',int(row.n),p,'q42/all/within_run/primary/A.n','shots',',d');add('OLD_TEST_POS',int(row.positive),p,'q42/all/within_run/primary/A.positive','shots',',d')
    add('B_AP_GAIN',facts['B_AP']['value']-facts['A_AP']['value'],p,'B.ap_mean - A.ap_mean (means of seed metrics)','AP difference','.5f')
    for _,row in frame.loc[(frame.dataset=='q42')&(frame.population=='all')&(frame.scheme=='forward_run')&(frame.experiment=='A')].iterrows():
        add('FWD_AUC_'+row.fold,float(row.auc_mean),p,f'q42/all/forward_run/{row.fold}/A.auc_mean','5-seed mean','.3f')
    for variant,name in [('E_full','P40_FULL'),('E_no_mold6','P40_REMOVE')]:
        row=frame.loc[(frame.dataset=='p40')&(frame.population=='normal_pressure')&(frame.experiment==variant)].squeeze()
        add(name,float(row.auc_mean),p,f'p40/normal_pressure/chronological/{variant}.auc_mean','ROC AUC','.4f')
    p='reports/oct03_pilot_r2/q1_fold_summary.csv'; frame=pd.read_csv(root/p,dtype={'fold':str})
    for fold in ['2','6']: add('Q1_GAIN_'+fold,float(frame.loc[(frame.scheme=='forward_run')&(frame.fold==fold),'gain'].iloc[0]),p,f'forward_run/{fold}.gain','percentage points','.2f',100)
    p='reports/oct03_pilot_r2/reused_test/g1_run_holdout_totals.csv'; frame=pd.read_csv(root/p)
    for policy,key in [('baseline','GATE_OLD'),('constrained','GATE_NEW')]:
        rows=frame.loc[frame.policy.eq(policy)]
        add(key,float(rows.pooled_fpr.mean()),p,f'policy={policy}; mean(pooled_fpr) over seeds','percent','.2f',100)
        if policy=='constrained':
            add('GATE_EP',float(rows.detected.mean()),p,'constrained mean(detected)','mean episodes','.1f')
            for col,key in [('normal','GATE_NORMAL'),('total','GATE_TOTAL'),('observable','GATE_OBS')]:
                assert rows[col].nunique()==1;add(key,int(rows[col].iloc[0]),p,'constrained common '+col,'count',',d')
    p='reports/oct03_queue_review/pooled_at20.csv'; frame=pd.read_csv(root/p).set_index('policy')
    for policy in ['Q','GQ','OOD05','OOD1']:
        row=frame.loc[policy]
        for field,code,unit,fmt,mult in [
          ('quality_capture_pooled','CAPTURE','percent','.3f',100),('quality_captured','HITS','positive shots','.1f',1),
          ('inspected','INSPECTED','records',',.0f',1),('auto_fpr_all_normal','FPR','percent','.3f',100),
          ('normal_intervention_rate','INTERVENTION','percent','.3f',100),('coverage','COVERAGE','percent','.3f',100),
          ('hold_rate','HOLD_RATE','percent','.3f',100),('hold_backlog','BACKLOG','records',',.0f',1),
          ('episodes_auto_detected','AUTO_EP','mean episodes','.1f',1),('episodes_inspection_reached','REACH_EP','episodes','.0f',1),
          ('inspection_hours_at3min','HOURS','assumed person hours','.2f',1),('backlog_hours_at3min','PENDING_HOURS','assumed person hours','.2f',1)]:
            add(policy+'_'+code,float(row[field]),p,f'policy={policy}; {field}',unit,fmt,mult)
    for field,key in [('n_total','QUEUE_N'),('normal_total','QUEUE_NORMAL'),('quality_known','QUEUE_LABELLED'),('quality_positive','QUEUE_POS'),('episodes_total','QUEUE_EP'),('episodes_observable','QUEUE_OBS_EP')]:
        assert frame[field].nunique()==1;add(key,int(frame.loc['Q',field]),p,f'all policies common {field}','count',',d')
    p='reports/oct03_queue_review/conditional_uncertainty.json'; a=json.loads((root/p).read_text())
    for field,key in [('estimate','GAIN_POOLED'),('lower95','GAIN_LOW'),('upper95','GAIN_HIGH')]: add(key,float(a[field]),p,field,'percentage points','.3f',100)
    p='reports/oct03_queue_review/decision.json'; a=json.loads((root/p).read_text());add('GAIN_MACRO',float(a['macro_gain_vs_Q']),p,'macro_gain_vs_Q','percentage points','.3f',100)
    p='reports/oct03_queue_review/outer_fold_means_at20.csv'; frame=pd.read_csv(root/p,dtype={'fold':str})
    for fold in ['2','3','4','6']:
        for policy in ['Q','GQ']:
            row=frame.loc[frame.fold.eq(fold)&frame.policy.eq(policy)].squeeze()
            add(f'RUN_{fold}_{policy}',float(row.quality_capture),p,f'fold={fold},policy={policy}.quality_capture','percent','.2f',100)
            if policy=='Q': add('RUN_'+fold+'_POS',int(row.quality_positive),p,f'fold={fold},policy=Q.quality_positive','positive shots',',d')
    p='reports/oct03_evidence/final/conditional_value_sensitivity.csv'; frame=pd.read_csv(root/p)
    row=frame.loc[frame.budget.eq(.2)&frame.policy.eq('GQ')&frame.avoidable_loss_per_detected_positive_ratio.eq(20)&frame.inspection_sensitivity_assumed.eq(1)&frame.pending_hold_penalty_ratio.eq(0)].squeeze()
    for field,key in [('conditional_value_in_inspection_cost_units','VALUE_DELTA'),('required_value_per_extra_episode','BREAK_EVEN')]: add(key,float(row[field]),p,'budget=.2 policy=GQ r=20 s=1 p=0; '+field,'inspection-cost units','.2f')
    for field,key,fmt in [('inspection_delta','EXTRA_INSPECT','.0f'),('capture_delta','CAPTURE_DELTA','.1f'),('extra_inspection_reached_episodes','EXTRA_EP','.0f')]:
        add(key,float(row[field]),p,'budget=.2 policy=GQ r=20 s=1 p=0; '+field,'count',fmt)
    return facts

def fill(text,facts):
    import re
    def replace(match):
        if match[1] not in facts: raise ValueError('Unbound evidence: '+match[1])
        return facts[match[1]]['display']
    return re.sub(r'\{\{([A-Z0-9_]+)\}\}',replace,text)

if __name__=='__main__':
    print(json.dumps(collect(),ensure_ascii=False,indent=2))
