"""Read-only source/lineage checks and conditional KPI scenarios. No model selection or fitting."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse, parse_qs
import argparse, itertools, json, re, zipfile
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from castguard.rebuild import with_run

ROOT=Path(__file__).resolve().parent
SOURCES=Path('docs/sources/oct03_round4')

def digest(path): return sha256(path.read_bytes()).hexdigest()
def save(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def hwpx_content(path):
    with zipfile.ZipFile(path) as z:
        sections=[ET.fromstring(z.read(n)) for n in sorted(z.namelist()) if n.startswith('Contents/section') and n.endswith('.xml')]
    def content(node): return ''.join((t.text or '') for t in node.iter() if t.tag.endswith('}t'))
    text='\n'.join(content(n) for root in sections for n in root.iter() if n.tag.endswith('}p'))
    tables=[[[content(c) for c in row if c.tag.endswith('}tc')] for row in tbl if row.tag.endswith('}tr')]
            for root in sections for tbl in root.iter() if tbl.tag.endswith('}tbl')]
    return text,tables

def require_current_notice(url,heading):
    parsed=urlparse(url); query=parse_qs(parsed.query)
    if parsed.hostname != 'www.kamp-ai.kr' or parsed.path not in ('/contestNoticeDetail','/noticeDetail'):
        raise ValueError('Wrong namespace: competition ID is not notice ID')
    key='CPT_NOTICE_SEQ' if parsed.path=='/contestNoticeDetail' else 'NOTICE_SEQ'
    if key not in query or not all(s in heading for s in ('2026년','제6회','중소','중견기업 재직자')):
        raise ValueError('Wrong edition, year, track, or notice query')
    return True

def verified_join(q,m,features):
    keys=['run_id','Shot']
    if q.duplicated(keys).any() or m.duplicated(keys).any():
        raise ValueError('Ambiguous join keys')
    joined=q[keys+features].merge(m[keys+features],on=keys,how='left',validate='one_to_one',indicator=True,suffixes=('_q','_m'))
    if not joined['_merge'].eq('both').all(): raise ValueError('Unmatched quality rows')
    compared=0
    for c in features:
        a,b=joined[c+'_q'],joined[c+'_m']
        if not (a.eq(b)|(a.isna()&b.isna())).all(): raise ValueError('Process mismatch: '+c)
        compared+=int((a.notna()&b.notna()).sum())
    return {'quality_rows':len(q),'matched':len(joined),'process_values_equal_nonmissing':compared,
            'physical_equipment_identity_confirmed':False,'join_type':'observed correspondence, derived run_id + Shot'}

def assert_input_contract(contract):
    forbidden={'Machine_Status','PassOrFail','Product_Quality','defect_type_count','episode_id','run_id','source_row','source_row_m41','id','_id'}
    defect_types=['Short_Shot','Bubble','Exfoliation','Blow_Hole','Stain','Dent','Deformation','Contamination','Impurity','Crack','Scratch','Buring_Mark','Inclusions']
    forbidden.update(f'{kind}_{cavity}' for kind in defect_types for cavity in [1,2])
    for name in ['q42_A0','q42_A','q42_B','m41_gate','p40_full']:
        columns=contract[name]
        if any(c in forbidden or c.startswith(('y_','oracle_')) for c in columns):
            raise ValueError('Label/post-outcome feature in '+name)
    return True

def conditional_value(row,base,loss_ratio,sensitivity,backlog_penalty):
    if loss_ratio<0 or not 0<=sensitivity<=1 or backlog_penalty<0: raise ValueError('Invalid scenario assumptions')
    captured_delta=float(row['quality_captured']-base['quality_captured'])
    inspection_delta=float(row['inspected']-base['inspected'])
    backlog_delta=float(row['hold_backlog']-base['hold_backlog'])
    value=loss_ratio*sensitivity*captured_delta-inspection_delta-backlog_penalty*backlog_delta
    extra_episodes=float(row['episodes_inspection_reached']-base['episodes_inspection_reached'])
    return {'capture_delta':captured_delta,'inspection_delta':inspection_delta,'backlog_delta':backlog_delta,
            'conditional_value_in_inspection_cost_units':value,
            'extra_inspection_reached_episodes':extra_episodes,
            'required_value_per_extra_episode':max(0,-value)/extra_episodes if extra_episodes>0 else None}

def run(root,out):
    out.mkdir(parents=True,exist_ok=False)
    src=root/SOURCES
    contract=json.loads((root/'data/processed/feature_contract.json').read_text(encoding='utf-8'))
    assert_input_contract(contract)
    tasktext,tables=hwpx_content(src/'employee_task_2026.hwpx')
    templatetext,_=hwpx_content(src/'employee_report_template_2026.hwpx')
    rubric=next(t for t in tables if any('AI 모델 및 통합성능' in ''.join(row) for row in t))
    rows=[row for row in rubric if row and re.match(r'\s*[1-6]\.',row[0])]
    taskweights=[int(row[-1].strip()) for row in rows]
    templatechapters=re.findall(r'제([1-6])장\.\s*([^〔\n]+)〔(\d+)점〕',templatetext)
    templateweights=[int(x[2]) for x in templatechapters]
    assert len(taskweights)==len(templateweights)==6 and sum(taskweights)==sum(templateweights)==100
    assert digest(src/'employee_task_2026.hwpx')==digest(src/'notice87_task.hwpx')
    assert digest(src/'employee_report_template_2026.hwpx')==digest(src/'notice87_report_template.hwpx')
    oldtask=next((root/'docs').glob('*.hwpx'))
    assert digest(oldtask)==digest(src/'employee_task_2026.hwpx')
    heading='2026년 제6회 K-인공지능 제조데이터 분석 경진대회 과제공개(중소·중견기업 재직자)'
    require_current_notice('https://www.kamp-ai.kr/contestNoticeDetail?CPT_NOTICE_SEQ=29',heading)
    assert heading in (src/'employee_notice.txt').read_text(encoding='utf-8')
    for period in ['2026년 9월 21일','2026년 10월 8일']:
        assert period in tasktext
    official={'year':2026,'edition':6,'track':'중소·중견기업 재직자','contest_id':39,'contest_notice_id':29,'general_notice_id':87,
       'registration':'2026-08-24 to 2026-09-17 KST','assignment_period':'2026-09-21 to 2026-10-08 23:59 KST',
       'old_competition_id_29':'2025 edition 5, not current','task_weights':taskweights,'template_weights':templateweights,
       'rubric_conflict':taskweights!=templateweights,'resolved_authoritative_weights':None,
       'same_attachments_on_both_boards':True,'local_task_matches_official':True,
       'template_chapters':templatechapters,'guide_download_requires_login':True}
    save(out/'official_contract.json',official)
    save(out/'task_rubric_tables.json',rubric)
    (out/'template_content.txt').write_text(templatetext,encoding='utf-8')

    qraw=pd.read_csv(root/'data/raw/DieCasting_Quality_Raw_Data.csv',header=1); qraw.columns=qraw.columns.str.strip()
    mraw=pd.read_csv(root/'data/raw/DieCasting_Raw_Data.csv'); praw=pd.read_csv(root/'data/raw/Investment_Casting.csv')
    q=with_run(qraw,'q42'); m=with_run(mraw,'m41')
    q=q.drop_duplicates(['run_id']+[c for c in qraw.columns if c!='id'])
    joined=verified_join(q,m,contract['q42_A0'])
    paired=q[['run_id','Shot']].merge(m[['run_id','Shot','Machine_Status']],on=['run_id','Shot'],validate='one_to_one')
    defects=[c for c in qraw if c not in contract['q42_A0'] and re.search(r'_[12]$',c)]
    assert len(defects)==26 and q[defects].notna().all().all()
    qlabels=q[defects].gt(0).any(axis=1).astype(int)
    qjoined=pd.read_parquet(root/'data/processed/joined.parquet')
    assert list(qlabels)==list(qjoined.y_defect)
    products=q.groupby('Product_Type').size().to_dict()
    measurement={'source':str(root/'data/raw'),'raw_shapes':{'q42':list(qraw.shape),'m41':list(mraw.shape),'p40':list(praw.shape)},
       'q42_duplicate_rows_removed':len(qraw)-len(q),'q42_positive_shots':int(qlabels.sum()),'quality_label_missing_cells':int(q[defects].isna().sum().sum()),
       'q42_positive_values_above_one':int(q[defects].gt(1).sum().sum()),'q42_product_codes':{str(k):int(v) for k,v in products.items()},
       'join':joined,'matched_state_codes':paired.Machine_Status.value_counts(dropna=False).to_dict(),
       'warm_state_code_1_quality_rows':int(paired.Machine_Status.eq(1).sum()),
       'q42_missing_physical_time':True,'m41_missing_physical_time':True,
       'p40_period':[str((praw.timestamp+' '+praw.date).pipe(pd.to_datetime).min()),str((praw.timestamp+' '+praw.date).pipe(pd.to_datetime).max())],
       'p40_timezone_known':False,'p40_line_codes':praw.line_unit.dropna().unique().tolist(),'p40_product_codes':praw.production.dropna().unique().tolist(),
       'p40_label_counts':{str(k):int(v) for k,v in praw.PassOrFail.value_counts(dropna=False).items()},
       'm41_state_counts':{str(k):int(v) for k,v in mraw.Machine_Status.value_counts(dropna=False).items()},
       'q42_shot_only_duplicate_keys':int(q.Shot.duplicated().sum()),'m41_shot_only_duplicate_keys':int(m.Shot.duplicated().sum()),
       'm41_p40_numeric_label_semantics_externally_confirmed':False,
       'no_direct_p40_q42_join':True,'causal_effect_identified':False,'real_economic_effect_measured':False}
    save(out/'lineage_audit.json',measurement)
    units=[]
    identifiers={'id','_id','Shot','Product_Type','line_unit','production','timestamp','date','production_count'}
    for alias,frame in [('q42',qraw),('m41',mraw),('p40',praw)]:
        for col in frame:
            role='target_or_outcome' if col in defects or col in ('Machine_Status','PassOrFail') else ('identifier_or_metadata' if col in identifiers else 'process_or_sensor')
            units.append({'dataset':alias,'column':col,'raw_dtype':str(frame[col].dtype),'missing':int(frame[col].isna().sum()),'distinct':int(frame[col].nunique()),
               'role':role,'physical_unit':'not_confirmed' if role=='process_or_sensor' else 'not_applicable_or_encoding_unconfirmed',
               'unit_source':'raw headers and public metadata contain no explicit units; guide/AAS unavailable',
               'live_availability':'post_outcome_not_predictor' if role=='target_or_outcome' else 'unverified_or_not_applicable'})
    pd.DataFrame(units).to_csv(out/'raw_column_registry.csv',index=False,encoding='utf-8-sig')

    metricpath=root/'reports/oct03_queue/outer_policy_metrics.csv'
    metrics=pd.read_csv(metricpath)
    counts=['n_total','normal_total','quality_known','quality_positive','quality_captured','inspected','hold_requested','hold_backlog','episodes_inspection_reached']
    seedtotals=metrics.groupby(['budget','policy','seed'])[counts].sum()
    totals=seedtotals.groupby(['budget','policy']).mean().reset_index()
    totals.to_csv(out/'kpi_population_totals.csv',index=False)
    scenarios=[]; labor=[]
    for _,row in totals.iterrows():
        base=totals.loc[totals.budget.eq(row.budget)&totals.policy.eq('Q')].iloc[0]
        for duration in [1,3,5]:
            labor.append({'budget':row.budget,'policy':row.policy,'minutes_per_inspection_assumed':duration,
              'served_person_hours':row.inspected*duration/60,'pending_hold_person_hours':row.hold_backlog*duration/60,
              'status':'conditional workload, not measured labor or savings'})
        for ratio,sensitivity,pending in itertools.product([1,5,20,100],[.8,1.],[0,1,5]):
            scenarios.append({'budget':row.budget,'policy':row.policy,'baseline':'Q','avoidable_loss_per_detected_positive_ratio':ratio,
              'inspection_sensitivity_assumed':sensitivity,'pending_hold_penalty_ratio':pending,**conditional_value(row,base,ratio,sensitivity,pending),
              'status':'scenario in normalized inspection-cost units; episode benefit unknown; not ROI'})
    pd.DataFrame(scenarios).to_csv(out/'conditional_value_sensitivity.csv',index=False)
    pd.DataFrame(labor).to_csv(out/'inspection_time_sensitivity.csv',index=False)
    sourcehashes={p.relative_to(root).as_posix():digest(p) for p in src.iterdir() if p.is_file()}
    inputpaths=['audit_oct03_evidence.py','data/processed/feature_contract.json','data/processed/joined.parquet',
        'data/raw/DieCasting_Quality_Raw_Data.csv','data/raw/DieCasting_Raw_Data.csv','data/raw/Investment_Casting.csv','reports/oct03_queue/outer_policy_metrics.csv']
    sourcehashes.update({name:digest(root/name) for name in inputpaths})
    save(out/'receipt.json',{'run_at':datetime.now(timezone.utc).isoformat(),'input_hashes':sourcehashes,
       'output_hashes':{p.name:digest(p) for p in out.iterdir() if p.is_file()},'new_training_runs':0,'test_selection_or_retuning':False,
       'checks':['official source edition/track/date and namespace','both-board attachment equality','rubric disagreement preserved','raw-to-quality labels',
        'one-to-one join + 14 exact process columns','forbidden model features','no manufactured warm quality labels','normalized cost and staffing scenarios'],
       'scenario_rows':len(scenarios),'unit_registry_rows':len(units),'rubric_conflict_open':True,'guide_access_block':'login required, not bypassed'})
    print(json.dumps({'quality_join':joined,'task_weights':taskweights,'template_weights':templateweights,'scenarios':len(scenarios),'raw_columns':len(units)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',default='reports/oct03_evidence/calculations'); args=parser.parse_args()
    run(ROOT,ROOT/args.output)
