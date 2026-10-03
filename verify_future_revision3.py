"""Read-only revision/migration/evidence checks; never generates model performance."""
from pathlib import Path
from hashlib import sha256
import json
import xml.etree.ElementTree as ET
import future_evaluation as public
import future_evaluation_v2 as compat
import future_evaluation_core as core
from historical_sources import ARCHIVED_SOURCES,resolve_historical_source

ROOT=Path(__file__).resolve().parent


def verify(root=ROOT):
    assert public.validate_bundle is compat.validate_bundle is core.validate_bundle
    assert public.main is compat.main is core.main
    assert core.validate_tables(None,{})['validator_revision']==3
    migration=json.loads((root/'reports/future_review_round10/migration_evidence.json').read_text(encoding='utf-8'))
    for name,h in migration['current_source_hashes'].items():
        assert sha256((root/name).read_bytes()).hexdigest()==h,name
    for name,item in migration['archived_sources'].items():
        assert sha256((root/item['path']).read_bytes()).hexdigest()==item['sha256'],name
        if name in ARCHIVED_SOURCES:assert resolve_historical_source(root,name,item['sha256'])==root/item['path']
    for name,h in migration['preserved_deliverables'].items():
        assert sha256((root/name).read_bytes()).hexdigest()==h,name
    checks={}
    for label,name,tests,failures in [
        ('before','reports/future_review_round10/before.xml',37,30),
        ('after_focused','reports/future_review_round10/after.xml',63,0),
        ('full',migration['full_regression_junit'],151,0)]:
        suite=ET.parse(root/name).getroot().find('testsuite')
        assert int(suite.attrib['tests'])==tests and int(suite.attrib['failures'])==failures
        assert int(suite.attrib['errors'])==0 and int(suite.attrib['skipped'])==0
        checks[label]={'tests':tests,'failures':failures,'errors':0,'skipped':0}
    contract=json.loads((root/'templates/future_evaluation/contract.json').read_text(encoding='utf-8'))
    assert contract==core.draft_contract()
    assert not core.validate_bundle(root/'templates/future_evaluation',root)['structural_checks_passed']
    return {'validator_revision':3,'public_entrypoints_share_core':True,'schema_version':1,
        'checks':checks,'archived_exact_sources':len(migration['archived_sources']),
        'historical_deliverables_preserved':len(migration['preserved_deliverables']),
        'empty_current_template_blocked':True,'new_training':False,'new_performance_evidence':False}


if __name__=='__main__':print(json.dumps(verify(),ensure_ascii=False))
