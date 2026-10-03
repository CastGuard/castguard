"""Evidence inventory for human review; standard library only, no external actions."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime
import json

REQUIREMENTS={
 'team_and_signatures':('submission','실제 팀정보·필요 서명 확인'),
 'survey_completion':('submission','실제 설문 완료화면 및 보고서 첨부 확인'),
 'portal_file_specifications':('not_required','사용자가 제공한 제출 요건 적용; 추가 포털 제한 확인은 요구하지 않음'),
 'blind_final_review':('submission','최종 PDF/PPTX/ZIP·메타데이터의 블라인드 검토'),
 'rubric_conflict_resolution':('advisory','과제35/15 대 보고서 양식40/10 충돌의 공식 확인'),
 'official_presentation_duration':('advisory','팀당 공식 발표·질의 시간 확인'),
 'source_guide_units':('future_evaluation','원본 AAS·가이드·단위·설비/제품 코드 의미'),
 'independent_future_cohort':('future_evaluation','기존 평가와 겹치지 않는 전체 미래 생산 기록'),
 'frozen_protocol_and_audit':('future_evaluation','라벨 열람 전 동결한 정책·지표·가드레일·독립 감사 계획'),
 'actual_clocks_and_resources':('future_evaluation','실제 입력/검사/정답 시각·검사 자원·대기/만료 한도'),
}


def template():
    return {'schema_version':1,'purpose':'Evidence pointers only; never fill unknown facts with guesses',
        'evidence':{key:{'path':None,'sha256':None,'reviewed_by':None,'reviewed_at':None,'finding':None} for key in REQUIREMENTS}}


def assess(root,record=None):
    root=Path(root).resolve();record=template() if record is None else record
    if not isinstance(record,dict) or record.get('schema_version')!=1 or not isinstance(record.get('evidence'),dict):
        raise ValueError('readiness record must have schema_version 1 and an evidence object')
    unknown=set(record['evidence'])-set(REQUIREMENTS)
    if unknown:raise ValueError('unknown readiness requirement: '+','.join(sorted(unknown)))
    results=[]
    for key,(scope,description) in REQUIREMENTS.items():
        item=record['evidence'].get(key);reason='missing evidence';status='missing'
        if scope=='not_required':
            results.append({'id':key,'scope':scope,'description':description,
                'status':'not_required_by_user_scope','reason':'User supplied submission requirements on 2026-10-03; this does not certify portal access or submission.'})
            continue
        if isinstance(item,dict) and item.get('path'):
            try:
                relative=Path(item['path']);path=(root/relative).resolve()
                if relative.is_absolute() or '..' in relative.parts or relative.drive or not path.is_relative_to(root):raise ValueError('evidence path must remain inside review folder')
                if not path.is_file():raise ValueError('evidence file missing')
                if sha256(path.read_bytes()).hexdigest()!=item.get('sha256'):raise ValueError('evidence hash mismatch')
                if any(not isinstance(item.get(k),str) or not item[k].strip() for k in ['reviewed_by','reviewed_at','finding']):raise ValueError('reviewer, aware timestamp and concrete finding are required')
                stamp=datetime.fromisoformat(item['reviewed_at'].replace('Z','+00:00'))
                if stamp.tzinfo is None:raise ValueError('review time requires timezone')
                status='documented_for_human_review';reason='local evidence matches declaration; authenticity and sufficiency not certified'
            except (OSError,ValueError,TypeError) as exc:status='invalid';reason=str(exc)
        results.append({'id':key,'scope':scope,'description':description,'status':status,'reason':reason})
    missing=lambda scope:[r['id'] for r in results if r['scope']==scope and r['status']!='documented_for_human_review']
    return {'status':'needs_external_evidence' if missing('submission') else 'evidence_inventory_complete_for_human_submission_review',
        'submission_missing':missing('submission'),'future_evaluation_missing':missing('future_evaluation'),
        'unresolved_advisories':missing('advisory'),'requirements':results,
        'scope':'final_submission_readiness_not_today_completion',
        'survey_owner':'user','additional_portal_restrictions_required':False,
        'actual_submission_completed':False,'external_evidence_authenticity_verified':False,
        'field_readiness_certified':False,'official_duration_invented':False}
