"""Readiness records are evidence inventories, never external authentication."""
from hashlib import sha256
import pytest
from review_readiness import assess,template,REQUIREMENTS


def test_default_readiness_preserves_missing_external_requirements(tmp_path):
    result=assess(tmp_path)
    assert result['status']=='needs_external_evidence' and set(result['submission_missing'])=={'team_and_signatures','survey_completion','blind_final_review'}
    assert len(result['future_evaluation_missing'])==4 and len(result['unresolved_advisories'])==2
    assert not result['actual_submission_completed'] and not result['field_readiness_certified']
    portal=next(r for r in result['requirements'] if r['id']=='portal_file_specifications')
    assert portal['status']=='not_required_by_user_scope'
    assert result['scope']=='final_submission_readiness_not_today_completion'
    assert result['survey_owner']=='user' and not result['additional_portal_restrictions_required']


@pytest.mark.parametrize('kind',['hash','path','reviewer','clock'])
def test_readiness_rejects_incomplete_or_invalid_evidence(tmp_path,kind):
    (tmp_path/'proof.txt').write_text('EXPLICIT TEST FIXTURE, NOT REAL EVIDENCE')
    record=template();item={'path':'proof.txt','sha256':sha256((tmp_path/'proof.txt').read_bytes()).hexdigest(),
        'reviewed_by':'FIXTURE','reviewed_at':'2030-01-01T00:00:00Z','finding':'TEST ONLY'}
    if kind=='hash':item['sha256']='0'*64
    if kind=='path':item['path']='../outside.txt'
    if kind=='reviewer':item['reviewed_by']=''
    if kind=='clock':item['reviewed_at']='2030-01-01T00:00:00'
    record['evidence']['survey_completion']=item
    result=assess(tmp_path,record)
    assert next(r for r in result['requirements'] if r['id']=='survey_completion')['status']=='invalid'
    assert 'survey_completion' in result['submission_missing']


def test_complete_fake_inventory_never_certifies_truth_or_submission(tmp_path):
    path=tmp_path/'fixture.txt';path.write_text('TEST ONLY')
    item={'path':path.name,'sha256':sha256(path.read_bytes()).hexdigest(),'reviewed_by':'FIXTURE',
          'reviewed_at':'2030-01-01T00:00:00Z','finding':'FAKE TEST ONLY'}
    record=template();record['evidence']={key:dict(item) for key in REQUIREMENTS}
    result=assess(tmp_path,record)
    assert result['status']=='evidence_inventory_complete_for_human_submission_review'
    assert not result['external_evidence_authenticity_verified'] and not result['actual_submission_completed']


def test_unknown_readiness_key_cannot_silently_hide_a_requirement(tmp_path):
    record=template();record['evidence']['survery_completion']={}
    with pytest.raises(ValueError):assess(tmp_path,record)
