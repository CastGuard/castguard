"""Read-only checks for the latest review, evidence bindings and empty future-data template."""
from pathlib import Path
from historical_sources import resolve_historical_source
import json,re
import pandas as pd
from castguard.data import digest
from future_evaluation import SCHEMAS,validate_bundle
from verify_round7 import verify as verify_prior
ROOT=Path(__file__).resolve().parent

def verify(root=ROOT):
    verify_prior(root);out=root/'reports/submission_round8'
    index=json.loads((out/'report_evidence.json').read_text(encoding='utf-8'))
    render=json.loads((out/'render_receipt.json').read_text(encoding='utf-8'))
    md=(out/'CastGuard_current_review.md').read_text(encoding='utf-8')
    page=(out/'CastGuard_current_review.html').read_text(encoding='utf-8')
    assert digest(out/'CastGuard_current_review.md')==index['report_sha256']==render['markdown_sha256']
    assert digest(out/'CastGuard_current_review.pdf')==render['pdf_sha256']
    assert digest(out/'CastGuard_current_review.html')==render['html_sha256']
    for key,value in index['metrics'].items():
        assert digest(root/value['source'])==value['sha256'],key
        assert value['display'] in md,key
    resolved_sources={path:resolve_historical_source(root,path,value).relative_to(root).as_posix() for path,value in index['source_hashes'].items()}
    assert len(index['metrics'])==108
    for marker in ['FIFO와 동일 행동','어느 정책의 현장 우위도 입증하지 못했다','정당한 미노출 holdout이 없다',
                   '합성 fixture는 기능 시험에만','D07 reports/oct03_round7/DIAGNOSTIC.md','F08 future_evaluation.py']:
        assert marker in md.replace('`','') and marker in page,marker
    assert not index['new_policy_selection'] and not index['synthetic_fixtures_in_performance_tables']
    assert not index['native_hwpx_created'] and not render['native_hwpx_layout_verified']
    for i in range(1,7):assert f'제{i}장.' in md and f'제{i}장.' in page
    assert not re.search(r'Users[\\/]+JH(?:[\\/]|\b)',md+page,re.I)
    blank=root/'templates/future_evaluation'
    assert all(pd.read_csv(blank/(name+'.csv')).empty for name in SCHEMAS)
    draft=validate_bundle(blank,root)
    assert draft['status']=='blocked' and not draft['performance_evidence_created']
    assert any(x['code']=='CONTRACT_INCOMPLETE' for x in draft['errors'])
    return {'resolved_historical_sources':resolved_sources,'latest_metric_bindings':108,'metric_source_files':len({x['source'] for x in index['metrics'].values()}),
      'report_hashes_verified':True,'round7_diagnosis_verified':True,'empty_csv_templates':len(SCHEMAS),
      'unconfigured_draft_correctly_blocked':True,'new_performance_evidence':False,'native_hwpx_created':False}

if __name__=='__main__':print(json.dumps(verify()))
