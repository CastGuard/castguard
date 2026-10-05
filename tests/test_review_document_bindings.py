"""Export metadata regressions discovered by fresh extraction."""
from pathlib import Path
from hashlib import sha256
import json
import pytest
from review import check_document_bindings


def fixture(tmp_path):
    folder=tmp_path/'review';folder.mkdir()
    hashes={}
    for name in ['CastGuard_report.md','CastGuard_report.html','CastGuard_report.pdf','CastGuard_presentation.pptx','proof.json']:
        path=folder/name;path.write_text('SYNTHETIC METADATA FIXTURE '+name);hashes[name]=sha256(path.read_bytes()).hexdigest()
    metric={'source':'review/proof.json','sha256':hashes['proof.json']}
    report={'metrics':{'VALUE':dict(metric)},'report_sha256':hashes['CastGuard_report.md']}
    slides={'numeric_metrics':{'VALUE':dict(metric)},'source_hashes':{'review/proof.json':hashes['proof.json']},'pptx_sha256':hashes['CastGuard_presentation.pptx']}
    render={key:hashes[name] for name,key in [('CastGuard_report.md','markdown_sha256'),('CastGuard_report.html','html_sha256'),('CastGuard_report.pdf','pdf_sha256')]}
    for name,value in [('report_evidence.json',report),('slide_evidence.json',slides),('render_receipt.json',render)]:
        (folder/name).write_text(json.dumps(value),encoding='utf-8')
    return folder


def test_consistent_local_document_bindings_pass(tmp_path):
    fixture(tmp_path)
    assert check_document_bindings(tmp_path)['source_and_export_hashes_match']


def test_exported_source_change_without_rebinding_is_caught(tmp_path):
    folder=fixture(tmp_path);(folder/'proof.json').write_text('different normalized bytes')
    with pytest.raises(ValueError,match='metric source mismatch'):check_document_bindings(tmp_path)


def test_document_metric_path_cannot_escape_bundle(tmp_path):
    folder=fixture(tmp_path);path=folder/'report_evidence.json';value=json.loads(path.read_text())
    value['metrics']['VALUE']['source']='../outside.json';path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='escapes'):check_document_bindings(tmp_path)


@pytest.mark.parametrize('saved_check', [False, True])
def test_current_report_recomputes_claims_even_without_or_with_stale_pass_receipt(tmp_path, monkeypatch, saved_check):
    import review_claims
    folder=fixture(tmp_path);path=folder/'report_evidence.json'
    value=json.loads(path.read_text());value['claims_reviewed_on']='2026-10-04'
    if saved_check:value['claim_checks']={'status':'passed'}
    path.write_text(json.dumps(value))
    def invalid_claim(root):
        assert root==tmp_path
        raise ValueError('Report claim: GQ observed numerator mismatch')
    monkeypatch.setattr(review_claims,'validate',invalid_claim)
    with pytest.raises(ValueError,match='observed numerator mismatch'):
        check_document_bindings(tmp_path)
