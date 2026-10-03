"""Current future-collection validator (revision 3, CSV schema 1).

Structural and local-file consistency only; no performance or field certification.
Historical implementations are preserved under legacy/ for evidence reproduction.
"""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import argparse,csv,json,math,re,io
import pandas as pd
ROOT=Path(__file__).resolve().parent
SCHEMAS={
 'events':['event_id','original_event_id','run_id','produced_at','event_available_at'],
 'features':['event_id','feature','value','measured_at','available_at'],
 'scores':['policy','event_id','decision_at','priority_class','score'],
 'audit_sample':['event_id','selected_at','selected','probability'],
 'quality_results':['event_id','inspection_started_at','inspection_completed_at','label_available_at','y_defect'],
 'capacity_slots':['slot_id','resource_id','start_at','complete_at'],
 'assignments':['policy','slot_id','event_id'],
 'label_uses':['policy','label_event_id','label_available_at','used_at'],
}
ATTESTATIONS=['independent_future_collection','sampling_independent_of_policy_and_outcome',
 'event_ids_fixed_before_outcomes','complete_event_and_input_trace','capacity_and_expiry_agreed',
 'training_label_trace_complete','source_and_clock_provenance_reviewed']
FORBIDDEN=re.compile(r'(^y_|label|defect|pass.?or.?fail|machine.?status|inspection|quality.?available|has.?quality|oracle)',re.I)

def draft_contract():
    return {'schema_version':1,'data_kind':'unconfigured','protocol_frozen_at':None,
      'evaluation_start_at':None,'evaluation_end_at':None,'outcome_cutoff_at':None,
      'required_features':['Velocity_1','Cycle_Time'],'resources':[],
      'max_wait_seconds':None,'max_queue_size':None,'service_seconds':None,
      'overflow_rule':'drop_new','expiry_rule':'complete_by_event_expiry',
      'window_end_rule':'complete_by_evaluation_end','missing_input_rule':'hold_fifo',
      'sampling':{'design':None,'probability':None,'seed':None,'frozen_at':None,
                  'audit_resource_mode':'separate_from_policy_capacity',
                  'event_id_rule':None,'definition_path':None,'definition_sha256':None},
      'policies':[{'policy':'FIFO','priority_rule':'fifo','definition_path':None,'definition_sha256':None,'frozen_at':None,'uses_labels':False},
                  {'policy':'Q','priority_rule':'score_desc','definition_path':None,'definition_sha256':None,'frozen_at':None,'uses_labels':True}],
      'source_files':[],'attestations':{key:False for key in ATTESTATIONS},
      'warning':'DRAFT: replace field choices using real operations and freeze before new labels; no performance certification'}

def timestamp(value):
    if value is None or pd.isna(value) or str(value).strip()=='':raise ValueError('missing timestamp')
    if isinstance(value,str):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})',value) or value.endswith('-00:00'):
            raise ValueError('use unambiguous ISO 8601 with explicit known offset (Z or +/-HH:MM)')
    elif not isinstance(value,(pd.Timestamp,datetime)):
        raise ValueError('timestamp must be ISO text or an aware datetime')
    t=pd.Timestamp(value)
    if t.tzinfo is None:raise ValueError('timestamp must have an explicit timezone')
    return t.tz_convert('UTC')

def audit_selected(event_id,seed,probability):
    """Frozen SHA256 Bernoulli draw; IDs and seed must be fixed before outcomes."""
    number=int(sha256(f'{seed}:{event_id}'.encode('utf-8')).hexdigest(),16)
    return number/2**256 < probability

def validate_tables(contract,tables,legacy_ids=(),legacy_hashes=()):
    errors=[];trace=[]
    def error(code,message):errors.append({'code':code,'message':message})
    def stop():
        kind=contract.get('data_kind') if isinstance(contract,dict) else None
        return {'schema_version':1,'validator_revision':3,'data_kind':kind,'structural_checks_passed':not errors,
          'status':'blocked' if errors else 'synthetic_functional_checks_only' if kind=='synthetic' else 'tables_checked_bundle_evidence_required',
          'validation_scope':'tables_only','source_files_verified':False,
          'performance_evidence_created':False,'field_readiness_certified':False,
          'external_provenance_verified':False,'errors':errors,'queue_trace':trace,
          'limitations':['Declared timestamps, source authenticity, audit independence and actual model input usage require human provenance review.',
             'Supports one shared queue/resource pool, fixed service duration, drop-new overflow and completion-by-expiry only.',
             'No accuracy, capture, cost, policy selection or production operation is performed.']}
    try:
        if not isinstance(contract,dict):raise ValueError('contract must be a JSON object')
        if not isinstance(tables,dict):raise ValueError('tables must be a mapping of DataFrames')
        if not isinstance(contract.get('attestations',{}),dict):raise ValueError('attestations must be an object')
        if not isinstance(contract.get('source_files',[]),list) or any(not isinstance(x,dict) for x in contract.get('source_files',[])):
            raise ValueError('source_files must be a list of objects')
        if not isinstance(contract.get('sampling'),dict):raise ValueError('sampling must be an object')
        if not isinstance(contract.get('policies'),list) or any(not isinstance(x,dict) for x in contract['policies']):raise ValueError('policies must be a list of objects')
        if isinstance(contract.get('schema_version'),bool) or contract.get('schema_version')!=1:raise ValueError('unsupported schema_version')
        if contract.get('data_kind') not in ['synthetic','real']:raise ValueError('data_kind must be explicitly real or synthetic')
        frozen,start,end,cutoff=[timestamp(contract[k]) for k in ['protocol_frozen_at','evaluation_start_at','evaluation_end_at','outcome_cutoff_at']]
        if not frozen<start<end<=cutoff:raise ValueError('require protocol_frozen < start < end <= outcome cutoff')
        wait=float(contract['max_wait_seconds']);service=float(contract['service_seconds']);limit=int(contract['max_queue_size'])
        if any(isinstance(contract[k],bool) for k in ['max_queue_size','max_wait_seconds','service_seconds']) or not math.isfinite(wait) or not math.isfinite(service) or wait<=0 or service<=0 or limit<=0 or limit!=contract['max_queue_size']:
            raise ValueError('positive finite wait/service duration and positive integer queue size required')
        for key,value in {'overflow_rule':'drop_new','expiry_rule':'complete_by_event_expiry','window_end_rule':'complete_by_evaluation_end','missing_input_rule':'hold_fifo'}.items():
            if contract.get(key)!=value:raise ValueError('unsupported or unspecified common rule: '+key)
        features=contract['required_features'];resources=contract['resources']
        if not isinstance(features,list) or not features or any(not isinstance(x,str) or not x.strip() for x in features) or len(set(features))!=len(features) or any(FORBIDDEN.search(x) for x in features):raise ValueError('feature allowlist empty, duplicated or includes a target/availability proxy')
        if not isinstance(resources,list) or not resources or any(not isinstance(x,str) or not x.strip() for x in resources) or len(set(resources))!=len(resources):raise ValueError('declare nonempty shared resource IDs')
        if any(not isinstance(p.get('policy'),str) or not p['policy'].strip() for p in contract['policies']):raise ValueError('nonempty policy names required')
        policies={p['policy']:p for p in contract['policies']}
        if len(policies)<2 or len(policies)!=len(contract['policies']):raise ValueError('at least two unique frozen policies required')
        for name,p in policies.items():
            if p['priority_rule'] not in ['fifo','score_desc'] or not isinstance(p.get('uses_labels'),bool):raise ValueError('unsupported policy or unspecified label usage')
            if not re.fullmatch('[0-9a-f]{64}',str(p.get('definition_sha256',''))):raise ValueError('frozen policy definition SHA256 required: '+name)
            if timestamp(p['frozen_at'])>frozen:raise ValueError('policy frozen after protocol: '+name)
        sample=contract['sampling'];probability=float(sample['probability'])
        if isinstance(sample['probability'],bool) or sample['design'] not in ['census','hash_bernoulli'] or not 0<probability<=1:raise ValueError('declare census or positive-probability frozen Bernoulli sampling')
        if sample['design']=='census' and probability!=1:raise ValueError('census requires probability 1')
        if sample['design']=='hash_bernoulli' and (not isinstance(sample['seed'],int) or isinstance(sample['seed'],bool)):raise ValueError('fixed integer audit seed required')
        if timestamp(sample['frozen_at'])>frozen:raise ValueError('sampling frozen after protocol')
        if sample.get('audit_resource_mode')!='separate_from_policy_capacity':raise ValueError('shared audit resources require a separately reviewed capacity design; not supported here')
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        error('CONTRACT_INCOMPLETE',str(exc));return stop()
    if contract['data_kind']=='real':
        for key in ATTESTATIONS:
            if contract.get('attestations',{}).get(key) is not True:error('PROVENANCE_ATTESTATION_MISSING',key)
        if not contract.get('source_files'):error('SOURCE_RECORDS_MISSING','real data requires local source files and SHA256 records')
        if not isinstance(sample.get('definition_path'),str) or not sample['definition_path'].strip() or not re.fullmatch('[0-9a-f]{64}',str(sample.get('definition_sha256',''))) or not isinstance(sample.get('event_id_rule'),str) or not sample['event_id_rule'].strip():
            error('SAMPLING_EVIDENCE_MISSING','real data requires a hashed local sampling definition and a frozen event_id_rule')
        for source in contract.get('source_files',[]):
            if not re.fullmatch('[0-9a-f]{64}',str(source.get('sha256',''))):error('SOURCE_HASH','source SHA256 must be 64 lowercase hexadecimal characters')
            elif source['sha256'] in set(legacy_hashes):error('EXPOSED_SOURCE','source matches existing raw/processed data')
    data={}
    for name,columns in SCHEMAS.items():
        if name not in tables or not isinstance(tables[name],pd.DataFrame) or list(tables[name].columns)!=columns:
            error('SCHEMA',name+' requires exact columns: '+','.join(columns));continue
        df=tables[name].copy().reset_index(drop=True)
        for col in [x for x in columns if x.endswith('_at')]:
            try:df[col]=df[col].map(timestamp)
            except (TypeError,ValueError) as exc:error('TIMESTAMP',name+'.'+col+': '+str(exc))
        data[name]=df
    if len(data)!=len(SCHEMAS) or any(e['code']=='TIMESTAMP' for e in errors):return stop()
    ev=data['events'];ft=data['features'];sc=data['scores'];audit=data['audit_sample'];labels=data['quality_results'];slots=data['capacity_slots'];assign=data['assignments'];uses=data['label_uses']
    for column,values in [('events.run_id',ev.run_id),('capacity_slots.resource_id',slots.resource_id)]:
        if any(not isinstance(value,str) or not value.strip() for value in values):
            error('GROUP_OR_RESOURCE_ID',column+' requires nonempty opaque strings')
    def unique(df,cols,name):
        if df[cols].isna().any().any() or df.duplicated(cols).any() or any(not isinstance(v,str) or not v.strip() for c in cols for v in df[c]):error('DUPLICATE_OR_MISSING_KEY',name)
    for df,cols,name in [(ev,['event_id'],'events'),(ev,['original_event_id'],'original_event_id'),(ft,['event_id','feature'],'features'),
       (sc,['policy','event_id'],'scores'),(audit,['event_id'],'audit_sample'),(labels,['event_id'],'quality_results'),
       (slots,['slot_id'],'capacity_slots'),(assign,['policy','slot_id'],'assignments'),(uses,['policy','label_event_id'],'label_uses')]:unique(df,cols,name)
    if ev.empty or slots.empty:error('EMPTY_COHORT','events and capacity slots must be populated; no synthetic replacement is supplied')
    ids=set(ev.event_id);names=set(policies)
    if (set(ev.original_event_id)|ids).intersection(legacy_ids):error('EXPOSED_EVENT','event_id or original_event_id was present in existing project data')
    if contract['data_kind']=='real' and any('SYNTHETIC' in str(v).upper() for v in list(ev.event_id)+list(ev.original_event_id)):
        error('SYNTHETIC_AS_REAL','explicitly synthetic fixture IDs cannot be declared real')
    for name,df in [('features',ft),('scores',sc),('audit_sample',audit),('quality_results',labels)]:
        if not set(df.event_id)<=ids:error('FOREIGN_KEY',name+' contains an unknown event')
    if not set(ft.feature)<=set(features):error('FORBIDDEN_INPUT','feature table contains undeclared input, label or availability proxy')
    if set(sc.policy)!=names or set(assign.policy)!=names or not set(uses.policy)<=names:error('POLICY_COVERAGE','policy names must match the frozen contract')
    if set(zip(sc.policy,sc.event_id))!={(p,e) for p in names for e in ids}:error('SCORE_COHORT','every policy needs every production event, including unaudited/missing-input events')
    if set(audit.event_id)!=ids:error('AUDIT_FRAME','audit decisions must cover the complete production frame')
    if set(zip(assign.policy,assign.slot_id))!={(p,s) for p in names for s in slots.slot_id}:error('CAPACITY_COVERAGE','every policy needs the same complete slot roster; use blank event_id for idle')
    if not set(slots.resource_id)<=set(resources):error('RESOURCE','slot uses an undeclared resource')
    for name,df,columns in [('scores',sc,['score','priority_class']),('audit_sample',audit,['probability']),('quality_results',labels,['y_defect'])]:
        for col in columns:
            try:df[col]=pd.to_numeric(df[col],errors='raise')
            except (TypeError,ValueError):error('INVALID_NUMBER',name+'.'+col)
    if errors:return stop()
    events=ev.set_index('event_id');scores=sc.set_index(['policy','event_id']);quality=labels.set_index('event_id')
    expires={e:row.produced_at+pd.Timedelta(seconds=wait) for e,row in events.iterrows()}
    for e,row in events.iterrows():
        if not start<=row.produced_at<end or row.event_available_at<row.produced_at:error('EVENT_TIME','invalid production/event availability: '+e)
    for row in ft.itertuples():
        if row.measured_at>row.available_at:error('FEATURE_TIME','feature available before measurement: '+row.event_id+'/'+row.feature)
        if not pd.isna(row.value):
            try:
                if not math.isfinite(float(row.value)):raise ValueError()
            except (TypeError,ValueError):error('FEATURE_VALUE','nonfinite/nonnumeric feature: '+row.event_id+'/'+row.feature)
    for resource,group in slots.groupby('resource_id'):
        group=group.sort_values(['start_at','slot_id'])
        prior=None
        for row in group.itertuples():
            if not start<=row.start_at<row.complete_at<=end or (row.complete_at-row.start_at).total_seconds()!=service:error('CAPACITY_TIME','common slot duration/window violated: '+row.slot_id)
            if prior is not None and row.start_at<prior:error('RESOURCE_OVERLAP','overlapping slots on '+resource)
            prior=row.complete_at
    # Common event and feature availability are defined independently of quality observation.
    ready={};hold={}
    for e in ids:
        predictions=sc.loc[sc.event_id.eq(e)]
        if predictions.decision_at.nunique()!=1:error('UNEQUAL_DECISION_TIME','policies have different information times: '+e);continue
        at=predictions.decision_at.iloc[0];ready[e]=at
        if at<events.loc[e,'event_available_at'] or at>cutoff:error('SCORE_TIME','score precedes event availability or exceeds cutoff: '+e)
        available=ft.loc[ft.event_id.eq(e)&ft.available_at.le(at)&ft.value.notna()]
        hold[e]=set(available.feature)!=set(features)
        for row in predictions.itertuples():
            if hold[e]:
                if row.priority_class!=0 or not pd.isna(row.score):error('FUTURE_OR_MISSING_FEATURE','unavailable required feature must produce common hold, never a score: '+row.policy+'/'+e)
            else:
                if row.priority_class not in [1,2] or pd.isna(row.score) or not math.isfinite(float(row.score)):error('INVALID_SCORE','complete-input event requires a finite score and class 1/2: '+row.policy+'/'+e)
                if policies[row.policy]['priority_rule']=='fifo' and (row.priority_class!=2 or row.score!=0):error('FIFO_DEFINITION','FIFO must have constant zero score and quality class')
        if e in quality.index and at>=quality.loc[e,'inspection_started_at']:error('PREDICTION_AFTER_INSPECTION','prediction must be strictly before independent inspection starts; equal timestamps do not prove precedence: '+e)
    for row in audit.itertuples():
        if row.selected not in [True,False,0,1] or float(row.probability)!=probability:error('AUDIT_PROBABILITY','invalid audit selection/probability: '+row.event_id);continue
        expected=True if sample['design']=='census' else audit_selected(row.event_id,sample['seed'],probability)
        if bool(row.selected)!=expected:error('AUDIT_SELECTION','audit sample differs from frozen outcome-blind draw: '+row.event_id)
        if not events.loc[row.event_id,'event_available_at']<=row.selected_at<=ready.get(row.event_id,start):error('AUDIT_TIME','sample selection must occur after event arrival and before policy scores: '+row.event_id)
    selected=set(audit.loc[audit.selected.eq(True),'event_id'])
    if set(labels.event_id)!=selected:error('AUDIT_LABEL_COVERAGE','need independent labels for all and only selected audit events; do not mix policy-selected labels')
    for row in labels.itertuples():
        if not events.loc[row.event_id,'produced_at']<=row.inspection_started_at<=row.inspection_completed_at<=row.label_available_at<=cutoff:error('LABEL_TIME','inspection completion/label availability/cutoff violated: '+row.event_id)
        if row.y_defect not in [0,1]:error('LABEL_VALUE','binary Shot-level label required: '+row.event_id)
    for name,p in policies.items():
        if p['uses_labels'] and uses.loc[uses.policy.eq(name)].empty:error('LABEL_TRACE_MISSING','training label trace missing: '+name)
        if not p['uses_labels'] and not uses.loc[uses.policy.eq(name)].empty:error('UNDECLARED_LABEL_USE','label usage not declared: '+name)
    eval_identifiers=ids|set(ev.original_event_id)
    for row in uses.itertuples():
        if row.label_event_id in eval_identifiers:error('EVALUATION_LABEL_USE','evaluation labels cannot train/update a frozen policy')
        if not row.label_available_at<=row.used_at<=timestamp(policies[row.policy]['frozen_at']):error('FUTURE_LABEL','label was used before availability or after policy freeze')
    if errors:return stop()
    # Replay finite waiting space, common hold FIFO, expiry and complete service slots.
    # Scores are supplied by frozen policies; this validator never chooses/train models.
    roster=slots.sort_values(['start_at','resource_id','slot_id'])
    arrivals=sorted(ids,key=lambda e:(ready[e],e))
    for name,p in policies.items():
        pending={};cursor=0;chosen=set();policy_assign=assign.loc[assign.policy.eq(name)].set_index('slot_id')
        def expire(at):
            for e in list(pending):
                if expires[e]<=at:
                    trace.append({'policy':name,'event_id':e,'action':'expired','at':expires[e].isoformat()});del pending[e]
        def admit(e):
            if ready[e]>=end:
                trace.append({'policy':name,'event_id':e,'action':'unavailable_by_window_end','at':end.isoformat()})
                return
            expire(ready[e])
            if expires[e]<=ready[e]:action='expired_before_admission'
            elif len(pending)>=limit:action='overflow_drop_new'
            else:pending[e]=True;action='admitted'
            trace.append({'policy':name,'event_id':e,'action':action,'at':ready[e].isoformat()})
        for slot in roster.itertuples():
            while cursor<len(arrivals) and ready[arrivals[cursor]]<=slot.start_at:
                e=arrivals[cursor];cursor+=1;admit(e)
            expire(slot.start_at)
            feasible=[e for e in pending if expires[e]>=slot.complete_at]
            def key(e):
                row=scores.loc[(name,e)]
                if hold[e]:return (0,0.,ready[e],e)
                return (2,0.,ready[e],e) if p['priority_rule']=='fifo' else (int(row.priority_class),-float(row.score),ready[e],e)
            expected=min(feasible,key=key) if feasible else ''
            actual=policy_assign.loc[slot.slot_id,'event_id'];actual='' if pd.isna(actual) else str(actual)
            if actual!=expected:error('QUEUE_ASSIGNMENT',f'{name}/{slot.slot_id}: expected {expected or "idle"}, received {actual or "idle"}; check availability, hold, capacity, expiry, overflow and frozen rank')
            if expected:
                del pending[expected];chosen.add(expected)
                trace.append({'policy':name,'event_id':expected,'action':'inspection_completed','at':slot.complete_at.isoformat(),'slot_id':slot.slot_id})
        # Every production row remains represented, including arrivals after the last slot.
        for e in arrivals[cursor:]:admit(e)
        expire(end)
        for e in pending:trace.append({'policy':name,'event_id':e,'action':'unserved_at_window_end','at':end.isoformat()})
    return stop()

def init_bundle(folder):
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'contract.json').write_text(json.dumps(draft_contract(),ensure_ascii=False,indent=2),encoding='utf-8')
    for name,columns in SCHEMAS.items():
        with (folder/(name+'.csv')).open('w',newline='',encoding='utf-8') as f:csv.writer(f).writerow(columns)
    return {'created':str(folder),'status':'empty draft; not real or synthetic performance evidence','tables':len(SCHEMAS)}

def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON key: '+key)
            result[key]=value
        return result
    def constant(value):raise ValueError('nonfinite JSON constant: '+value)
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant)


def local_file(base,name):
    """Check containment before opening; never follow a link outside the bundle."""
    if not isinstance(name,str) or not name.strip():raise ValueError('nonempty relative file path required')
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts or relative.drive:raise ValueError('file path must remain inside bundle')
    path=base/relative
    if path.is_symlink() or not path.resolve().is_relative_to(base) or not path.is_file():raise ValueError('file must exist inside bundle without an external/symbolic link')
    return path


def validate_bundle(folder,root=ROOT):
    base=Path(folder).resolve();root=Path(root)
    # Parse and hash the same bytes; schema inputs receive the same containment check
    # as supporting files before any read, including a redirected contract/CSV.
    inputs={name:local_file(base,name).read_bytes() for name in ['contract.json']+[x+'.csv' for x in SCHEMAS]}
    contract=strict_json(inputs['contract.json'].decode('utf-8'))
    # Keys are opaque identifiers, including leading zeros and literal NA/NULL/nan.
    # Converters run on raw CSV cells; numeric/boolean/value columns retain pandas'
    # missing-value parsing, so blank scores/features and idle assignments still work.
    tables={name:pd.read_csv(io.BytesIO(inputs[name+'.csv']),keep_default_na=True,
        converters={column:str for column in columns if column.endswith('_id') or column in ['policy','feature']})
        for name,columns in SCHEMAS.items()}
    legacy_ids=set();legacy_hashes=set()
    for name in ['joined.parquet','m41_timeline.parquet']:
        path=root/'data/processed'/name
        if path.exists():legacy_ids.update(pd.read_parquet(path,columns=['row_id']).row_id)
    for sub in ['data/raw','data/processed']:
        for path in (root/sub).glob('*'):
            if path.is_file():legacy_hashes.add(sha256(path.read_bytes()).hexdigest())
    result=validate_tables(contract,tables,legacy_ids,legacy_hashes)
    source_errors=[];verified=[]
    # Malformed declarations already have structured errors; do not dereference them.
    if result['structural_checks_passed']:
        source_records=list(contract.get('source_files',[]))
        if contract.get('data_kind')=='real':
            source_records += [{'path':p.get('definition_path'),'sha256':p.get('definition_sha256')} for p in contract['policies']]
            sample=contract['sampling']
            source_records += [{'path':sample['definition_path'],'sha256':sample['definition_sha256'],'sampling':True}]
        for source in source_records:
            try:path=local_file(base,source.get('path'))
            except ValueError as exc:
                source_errors.append({'code':'SOURCE_PATH','message':str(exc)});continue
            raw=path.read_bytes();h=sha256(raw).hexdigest()
            if h!=source.get('sha256'):
                source_errors.append({'code':'SOURCE_HASH','message':'Source content does not match its declared SHA256: '+source['path']});continue
            verified.append({'path':source['path'],'sha256':h})
            if source.get('sampling'):
                try:
                    definition=strict_json(raw.decode('utf-8'))
                    keys=['design','probability','seed','frozen_at','audit_resource_mode','event_id_rule']
                    if not isinstance(definition,dict) or set(definition)!=set(keys):raise ValueError('sampling definition requires exactly: '+','.join(keys))
                    for key in keys:
                        if type(definition[key]) is not type(sample[key]) or definition[key]!=sample[key]:raise ValueError('sampling definition disagrees with contract: '+key)
                except (ValueError,TypeError,KeyError) as exc:source_errors.append({'code':'SAMPLING_DEFINITION','message':str(exc)})
        if source_errors:result['errors']+=source_errors;result['structural_checks_passed']=False;result['status']='blocked'
        elif contract.get('data_kind')=='real':
            result['source_files_verified']=True;result['status']='ready_for_human_provenance_review'
    result['validation_scope']='bundle_and_local_file_consistency'
    result['verified_local_files']=verified
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    result['input_hashes']={name:sha256(raw).hexdigest() for name,raw in inputs.items()}
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--output',type=Path,required=True)
    validate=sub.add_parser('validate');validate.add_argument('--directory',type=Path,required=True);validate.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='init':print(json.dumps(init_bundle(args.output),ensure_ascii=False));return 0
    if args.output.exists():raise FileExistsError('Use a new validation receipt path')
    try:result=validate_bundle(args.directory)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result={'schema_version':1,'validator_revision':3,'status':'blocked','structural_checks_passed':False,'performance_evidence_created':False,'field_readiness_certified':False,
          'source_files_verified':False,'external_provenance_verified':False,'validation_scope':'bundle_read_failed',
          'errors':[{'code':'BUNDLE_READ','message':str(exc)}]}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ['queue_trace','input_hashes']},ensure_ascii=False))
    return 0 if result['structural_checks_passed'] else 2

if __name__=='__main__':raise SystemExit(main())
