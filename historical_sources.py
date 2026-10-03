"""Resolve exact historic source bytes after the default validator was repaired.

No old receipt, numeric result, report, slide or archive hash is changed. Only
these named source files can resolve to their byte-identical archived copies.
"""
from hashlib import sha256
from pathlib import Path

ARCHIVED_SOURCES = {
    **{name:'legacy/before_experiment_integrity/'+name for name in ['oct03_research.py','oct03_queue.py','verify_oct03.py','verify_oct03_queue.py','replay_report.py','historical_sources.py']},
    'future_evaluation.py':'legacy/future_evaluation_v1.py',
    'future_evaluation_v2.py':'legacy/future_evaluation_v2.py',
    'tests/test_future_evaluation_v2.py':'legacy/test_future_evaluation_v2_round9.py',
    **{f'docs/{name}':f'docs/archive/round10_legacy/{name}' for name in [
        'FUTURE_EVALUATION_CONTRACT.md','DATA_REQUEST_ROUND8.md',
        'FUTURE_EVALUATION_V2.md','FUTURE_STATISTICAL_PLAN_ROUND9.md']},
}


def resolve_historical_source(root, name, expected_sha256):
    root=Path(root).resolve();relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:raise AssertionError('unsafe historical source path')
    candidates=[relative]
    if name in ARCHIVED_SOURCES:candidates.append(Path(ARCHIVED_SOURCES[name]))
    for candidate in candidates:
        path=(root/candidate).resolve()
        if path.is_relative_to(root) and path.is_file() and sha256(path.read_bytes()).hexdigest()==expected_sha256:
            return path
    raise AssertionError('Historic source hash mismatch: '+name)
