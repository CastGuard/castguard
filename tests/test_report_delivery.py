from pathlib import Path
import pytest
from report_evidence import fill,collect
from replay_report import check_hashes
from package_report import safe_name
ROOT=Path(__file__).resolve().parents[1]

def test_unbound_claim_stops_report_generation():
    with pytest.raises(ValueError,match='Unbound'):fill('gain {{UNKNOWN_GAIN}}',{})

def test_modified_source_is_rejected_before_model_loading(tmp_path):
    from hashlib import sha256
    (tmp_path/'evidence.csv').write_text('forged')
    with pytest.raises(ValueError,match='hash mismatch'):
        check_hashes(tmp_path,{'evidence.csv':sha256(b'original').hexdigest()})

def test_report_keeps_seen_population_and_negative_pooled_effect():
    f=collect(ROOT)
    assert f['QUEUE_POS']['value']==505 and f['QUEUE_LABELLED']['value']==2879
    assert f['GATE_NORMAL']['value']==4613 and f['QUEUE_NORMAL']['value']==3191
    assert f['GAIN_POOLED']['value']<0<f['GAIN_MACRO']['value']
    assert f['VALUE_DELTA']['value']<0 and f['WARM_Q']['value']==0

def test_archive_rejects_escape_credentials_and_caches():
    for name in ['../escape','C:/Users/private','a\\b','/root/a','.git/config','.env','artifacts/cache/model','tests/__pycache__/x.pyc']:
        assert not safe_name(name)
    assert safe_name('reports/oct03_queue/models/trusted.joblib')
