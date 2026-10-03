"""Run tests with a fresh package-local temp directory, preserving all existing paths."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,os,subprocess,sys,json,uuid
ROOT=Path(__file__).resolve().parent

# Explicit dependency boundary, not an automatic skip on failure. The default
# full suite is unchanged; omitted source-check tests remain runnable by name.
ARTIFACT_TESTS={
    'tests/test_experiments.py::test_frozen_data_hashes_joins_and_folds':
        'Original byte-exact raw CSVs; inherited Git blobs use LF while the original manifest records CRLF bytes.',
    'tests/test_oct03_evidence.py::test_official_attachments_retain_rubric_disagreement':
        'External HWPX source copies excluded from the source publication.',
    'tests/test_oct03_evidence.py::test_real_comparison_uses_same_population_not_macro_quality_rates':
        'Saved queue metric tables excluded from the source publication.',
    'tests/test_report_delivery.py::test_report_keeps_seen_population_and_negative_pooled_effect':
        'Saved evidence and report result tables excluded from the source publication.',
    'tests/test_review_metrics.py::test_independent_raw_truth_and_saved_actions_agree':
        'Saved row-level queue and baseline actions excluded from the source publication.',
    'tests/test_review_metrics.py::test_corrupted_denominator_is_detected':
        'Saved row-level queue and baseline actions excluded from the source publication.',
    'tests/test_review_metrics.py::test_corrupted_saved_action_label_is_detected_independently':
        'Saved row-level queue and baseline actions excluded from the source publication.',
}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only',action='store_true',help='Run source/fixture and inherited-data tests; report seven explicitly excluded artifact/byte-provenance checks.')
    args=parser.parse_args()
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    base=(ROOT/'reports/reproduction'/('tests_'+run_id)).resolve()
    assert base.is_relative_to(ROOT.resolve()) and not base.exists()
    base.mkdir(parents=True)
    temp=base/'temp'
    assert not temp.exists()  # pytest may clear its basetemp; always supply a new child.
    command=[sys.executable,'-B','-m','pytest','tests','-q','-p','no:cacheprovider','--tb=short','--basetemp',str(temp),'--junitxml',str(base/'tests.xml')]
    if args.source_only:
        command.extend('--deselect='+name for name in ARTIFACT_TESTS)
    env=dict(os.environ);env.pop('PYTHONPATH',None)
    env['PYTHONNOUSERSITE']='1';env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1';env['PYTHONIOENCODING']='utf-8'
    result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (base/'stdout.txt').write_text(result.stdout,encoding='utf-8')
    (base/'stderr.txt').write_text(result.stderr,encoding='utf-8')
    receipt={'run_at':datetime.now(timezone.utc).isoformat(),'returncode':result.returncode,'fresh_local_temp':True,
        'junit_path':(base/'tests.xml').relative_to(ROOT).as_posix(),
        'scope':'source_and_fixtures_with_inherited_data' if args.source_only else 'full_review',
        'excluded_tests':ARTIFACT_TESTS if args.source_only else {},
        'full_historical_replay_performed':False,
        'command':'python -I -B run_review_tests.py'+(' --source-only' if args.source_only else '')}
    (base/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(result.stdout);print(json.dumps(receipt));sys.exit(result.returncode)
