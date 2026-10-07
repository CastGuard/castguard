"""Research-only automatic quality review from explicit current/past input packets.

No source-table lookup, no current quality label, no actuator interface.
"""
from pathlib import Path
import argparse
import hashlib
import html
import json
import math
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from .decision_review import explain

SCHEMA='castguard-research-reader-v1'
PROCESS=['Velocity_1','Velocity_2','Velocity_3','High_Velocity','Cylinder_Pressure','Rapid_Rise_Time',
         'Biscuit_Thickness','Clamping_Force','Cycle_Time','Pressure_Rise_Time','Casting_Pressure',
         'Spray_Time','Spray_1_Time','Spray_2_Time']
SENSORS=['Melting_Furnace_Temp','Air_Pressure','Coolant_Temp','Coolant_Pressure','Factory_Temp','Factory_Humidity']
HISTORY=['prev_cycle_time','max_cycle_previous_5','missing_process_previous_20','missing_shots_before_current']
FB=['fb_rate20','fb_rate100','fb_ewm','fb_known_count']


def keys(obj, allowed, required=()):
    if not isinstance(obj,dict) or set(obj)-set(allowed) or set(required)-set(obj):
        raise ValueError('unsupported fields or missing required fields')


def number(x,nullable=False,integer=False):
    if x is None and nullable:return np.nan
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x):
        raise ValueError('finite numeric value required')
    if integer and (int(x)!=x or abs(x)>2**53):raise ValueError('exact integer required')
    return x


def features_from_packet(record, features):
    required=['record_id','run_key','event_order','shot','measurements','product_type']
    keys(record,required+['process_history','quality_feedback','feedback_ledger_complete'],required)
    if any(not isinstance(record[k],str) or not record[k].strip() for k in ['record_id','run_key']):
        raise ValueError('nonempty identifiers required')
    t=number(record['event_order'],integer=True);shot=number(record['shot'],integer=True)
    if t<0 or shot<0:raise ValueError('negative event/shot')
    product=number(record['product_type'],integer=True)
    keys(record['measurements'],PROCESS+SENSORS)
    values={k:number(v,nullable=True) for k,v in record['measurements'].items()}
    values['Product_Type']=product
    history=record.get('process_history',[])
    if not isinstance(history,list):raise ValueError('history must be an array')
    hh={}
    for h in history:
        keys(h,['run_key','event_order','shot','measurements'],['run_key','event_order','shot','measurements'])
        e=number(h['event_order'],integer=True);s=number(h['shot'],integer=True)
        if h['run_key']!=record['run_key'] or e<0 or e>=t or e in hh or s>=shot:
            raise ValueError('duplicate/future/cross-run/conflicting process history')
        keys(h['measurements'],PROCESS,PROCESS)
        hh[e]={'shot':s,'values':{k:number(v,nullable=True) for k,v in h['measurements'].items()}}
    need_history=any(c in HISTORY for c in features)
    history_complete=set(range(max(0,int(t)-20),int(t))).issubset(hh)
    if need_history and not history_complete:raise ValueError('complete last20 process events required')
    if history_complete and t>0:
        prev=hh[t-1];last5=[hh[i]['values']['Cycle_Time'] for i in range(max(0,int(t)-5),int(t))]
        values.update(prev_cycle_time=prev['values']['Cycle_Time'],
                      max_cycle_previous_5=float(np.nanmax(last5)) if np.isfinite(last5).any() else np.nan,
                      missing_process_previous_20=float(sum(any(not np.isfinite(v) for v in hh[i]['values'].values()) for i in range(max(0,int(t)-20),int(t)))),
                      missing_shots_before_current=max(0,shot-prev['shot']-1))
    else:
        values.update({k:np.nan for k in HISTORY})
    feedback=record.get('quality_feedback',[])
    if not isinstance(feedback,list):raise ValueError('quality_feedback must be an array')
    seen=set();events=[];labels=[]
    for z in feedback:
        keys(z,['run_key','event_order','available_event','defect'],['run_key','event_order','available_event','defect'])
        e=number(z['event_order'],integer=True);a=number(z['available_event'],integer=True);y=number(z['defect'],integer=True)
        if z['run_key']!=record['run_key'] or e<0 or e in seen or y not in [0,1] or e>t-20 or a<e+20 or a>t:
            raise ValueError('duplicate/current/future/early/cross-run quality feedback')
        seen.add(e);events.append(e);labels.append(y)
    if any(c in FB for c in features) and record.get('feedback_ledger_complete') is not True:
        raise ValueError('explicit complete available-feedback ledger required')
    o=np.asarray(events,float);y=np.asarray(labels,float)
    for w in [20,100]:
        z=y[o>t-20-w];values[f'fb_rate{w}']=float(z.mean()) if len(z) else np.nan
    weights=np.exp2(-(t-20-o)/15.)
    values['fb_ewm']=float(np.dot(weights,y)/weights.sum()) if len(y) else np.nan
    values['fb_known_count']=len(y)
    return values,history_complete


class ResearchReader:
    def __init__(self,root):
        self.root=Path(root).resolve()
        self.profile=json.loads((self.root/'reports/oct06_research/reader_profile.json').read_text(encoding='utf-8'))
        profile=self.profile;p=(self.root/profile['model_path']).resolve()
        if not p.is_relative_to(self.root) or hashlib.sha256(p.read_bytes()).hexdigest()!=profile['model_sha256']:
            raise ValueError('reader model hash/path mismatch')
        self.payload=joblib.load(p)
        if self.payload['features']!=profile['features']:raise ValueError('feature contract mismatch')
        gp=json.loads((self.root/'configs/decision_review.json').read_text(encoding='utf-8'))
        # First originally eligible frozen gate, seed17; no retrospective performance selection.
        self.gate_profile=gp['checkpoints']['queue-fold3-seed17']['gate']
        path=(self.root/self.gate_profile['path']).resolve()
        if not path.is_relative_to(self.root) or hashlib.sha256(path.read_bytes()).hexdigest()!=self.gate_profile['sha256']:
            raise ValueError('gate model hash/path mismatch')
        self.gate=joblib.load(path)

    def review(self,envelope):
        keys(envelope,['schema_version','records'],['schema_version','records'])
        if envelope['schema_version']!=SCHEMA or not isinstance(envelope['records'],list) or not envelope['records']:
            raise ValueError('unsupported schema/empty records')
        ids=[];events=[]
        for r in envelope['records']:
            if isinstance(r,dict):
                ids.append(r.get('record_id'));events.append((r.get('run_key'),r.get('event_order')))
        if len(set(ids))!=len(ids) or len(set(events))!=len(events):raise ValueError('duplicate records/events in packet')
        outputs=[]
        for record in envelope['records']:
            result={'record_id':record.get('record_id') if isinstance(record,dict) else None,
                    'status':'not_scored','action':'manual_review','warnings':[], 'quality':None,'gate':None,
                    'control_action':None,'field_effect_validated':False}
            try:
                values,history_complete=features_from_packet(record,self.payload['features'])
                missing=[f for f in self.payload['features'] if f not in FB and not np.isfinite(values.get(f,np.nan))]
                if missing:raise ValueError('missing measurements/history: '+', '.join(missing))
                if any(c in FB for c in self.payload['features']) and values['fb_known_count']==0:
                    result['warnings'].append('no_available_quality_feedback')
                if record['product_type'] not in self.profile['products']:result['warnings'].append('unseen_product')
                for f in self.payload['features']:
                    lo,hi=self.profile['ranges'][f]
                    if np.isfinite(values.get(f,np.nan)) and not lo<=values[f]<=hi:
                        result['warnings'].append('outside_training_range:'+f)
                bins=[]
                for f in self.profile['pair']:
                    bins.append(pd.cut(pd.Series([values[f]]),self.profile['edges'][f],labels=False,include_lowest=True).iloc[0])
                joint=next((x['n'] for x in self.profile['cells'] if x['product']==record['product_type'] and [x['x'],x['y']]==bins),0)
                result['joint_training_n']=joint
                if joint<30:result['warnings'].append('insufficient_joint_support')
                x=pd.DataFrame([{f:values.get(f,np.nan) for f in self.payload['features']}])
                with threadpool_limits(limits=1):
                    score=float(self.payload['model'].predict_proba(x)[:,1][0])
                explanation=None
                if self.payload['model_name'] in ['logistic','lightgbm']:
                    sx,explanation=explain(self.payload['model'],self.payload['model_name'],self.payload['features'],
                                           {k:(float(v) if np.isfinite(v) else None) for k,v in values.items()})
                    if abs(sx-score)>1e-6:raise ValueError('explanation reconstruction mismatch')
                high=score>=self.payload['threshold']
                result['quality']={'score':score,'threshold':self.payload['threshold'],'risk_flag':bool(high),
                    'interpretation':'uncalibrated research score','explanation':explanation}
                result['status']='scored_with_warning' if result['warnings'] else 'scored'
                result['action']='manual_review' if result['warnings'] else ('additional_inspection_review' if high else 'maintain_existing_inspection')
                if history_complete and all(np.isfinite(values.get(c,np.nan)) for c in self.gate_profile['features']):
                    gate_score,gate_explanation=explain(self.gate['pipeline'],self.gate_profile['model'],self.gate_profile['features'],values)
                    threshold=self.gate_profile['threshold']['threshold']
                    gate_warnings=[c for c,(lo,hi) in self.gate_profile['ranges'].items() if not lo<=values[c]<=hi]
                    flag=bool(gate_score>=threshold)
                    result['gate']={'score':gate_score,'threshold':threshold,'diagnostic_flag':flag,
                        'outside_training_range':gate_warnings,'checkpoint':'queue-fold3-seed17',
                        'meaning':'numeric state1; physical status coding and field FPR unverified',
                        'explanation':gate_explanation}
                    if flag:result['action']='manual_quality_and_equipment_review'
                else:result['gate']={'status':'not_scored','reason':'complete process history required'}
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                result['status']='invalid_or_incomplete_input';result['reason']=str(exc)
            outputs.append(result)
        return {'schema_version':'castguard-research-review-v1','mode':'offline_research_decision_support',
                'selection':self.profile['selection'],'model_sha256':self.profile['model_sha256'],
                'automation':'input checks + risk flags + human-review routing; no automatic actuation',
                'quality_feedback':'past results >=20 process events old; explicit received ledger; no current target',
                'records':outputs,
                'policy_comparison':{'population':3395,'observed_quality':2879,'observed_positives':505,
                    'capacity_opportunities':677,'FIFO_caught':113,'Q_caught_mean':105.4,'GQ_caught_mean':102.2,
                    'GQ_episode_reached':8,'episodes_all':15,'Q_episode_reached':1,
                    'unobserved_quality':516,'held':409,'end_backlog':241,
                    'source':'reports/oct03_round7/group_metrics.csv; reports/oct03_queue_review/pooled_at20.csv',
                    'warning':'historical frozen policies; not measured performance of this new reader'}}


def render_html(result):
    e=html.escape
    body=['<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CastGuard 판독</title>',
          '<style>body{font:16px/1.65 "Malgun Gothic",sans-serif;margin:40px auto;max-width:1100px;padding:0 24px;color:#172b43;background:#f6f8fc}article{background:white;padding:24px;margin:24px 0}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ccd5df;text-align:left}strong{color:#185fa0}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>',
          '<h1>CastGuard · 검사 판단 근거</h1><p>현재 공정 입력과 도착한 과거 검사결과로 위험을 표시하고 검토 대상을 자동 분류합니다. 연구용 미보정 점수이며 현장 확률·자동 제어·검사 대체를 보증하지 않습니다.</p>']
    labels={'manual_review':'입력·적용범위 사람 검토','additional_inspection_review':'추가검사 검토 요청',
            'maintain_existing_inspection':'기존 검사 절차 유지','manual_quality_and_equipment_review':'품질·설비 담당자 공동 검토'}
    for r in result['records']:
        body.append(f'<article><h2>{e(str(r["record_id"]))}</h2><p><strong>{labels.get(r["action"],r["action"])}</strong> · {e(r["status"])}</p>')
        if r.get('quality'):
            q=r['quality'];body.append(f'<p>품질 위험 점수 <strong>{q["score"]:.4f}</strong> / validation 고정 기준 {q["threshold"]:.4f} · 학습 공동지지 {r["joint_training_n"]}행</p>')
        if r.get('warnings'):body.append('<p>적용 경고: '+e(', '.join(r['warnings']))+'</p>')
        if r.get('reason'):body.append('<p>'+e(r['reason'])+'</p>')
        if r.get('gate'):body.append('<p>설비 상태: '+e(json.dumps({k:v for k,v in r['gate'].items() if k!='explanation'},ensure_ascii=False))+'</p>')
        body.append('<details><summary>입력 판단·모델 설명 전체 보기</summary><pre>'+e(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details></article>')
    body.append('<h2>같은 검사 기회의 이득과 손실</h2><p>기존 동결 정책의 별도 역사적 비교입니다. 이번 새 판독기의 정책 성능으로 읽지 않습니다.</p><table><tr><th>정책</th><th>관측 불량 포착 / 505</th><th>상태 에피소드 검사 도달 / 15</th></tr><tr><td>FIFO</td><td>113</td><td>별도 지표 참조</td></tr><tr><td>품질 Q</td><td>105.4</td><td>1</td></tr><tr><td>품질+설비 GQ</td><td>102.2</td><td>8</td></tr></table><p>3,395행 · 공통 제공 기회677 · 품질 미관측516 · 보류409 · 종료잔량241. 품질 포착 개선은 입증되지 않았습니다.</p></html>')
    return '\n'.join(body)


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--html');p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));args=p.parse_args()
    targets=[Path(x) for x in [args.output,args.html] if x]
    if any(x.exists() for x in targets):raise FileExistsError('output already exists')
    result=ResearchReader(args.root).review(json.loads(Path(args.input).read_text(encoding='utf-8')))
    for x in targets:x.parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if args.html:Path(args.html).write_text(render_html(result),encoding='utf-8')
    print(f'processed {len(result["records"])} records; research only')


if __name__=='__main__':main()
