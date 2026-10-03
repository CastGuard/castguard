"""Targeted mutation trials in disposable copies; never mutate production files."""
from pathlib import Path
from hashlib import sha256
import json,shutil,subprocess,sys,xml.etree.ElementTree as ET

MUTATIONS=[
 ('future_feature', '&ft.available_at.le(at)', '', 'test_future_evaluation.py::test_future_feature_cannot_be_used_or_silently_filtered'),
 ('evaluation_label', 'if row.label_event_id in eval_identifiers:', 'if False:', 'test_future_evaluation.py::test_training_cannot_use_future_or_evaluation_labels'),
 ('equal_inspection_clock', "at>=quality.loc[e,'inspection_started_at']", "at>quality.loc[e,'inspection_started_at']", 'test_future_evaluation_adversarial.py::test_equal_prediction_inspection_time_cannot_establish_precedence'),
 ('completion_expiry', 'expires[e]>=slot.complete_at', 'expires[e]>=slot.start_at', 'test_future_evaluation.py::test_expiry_is_checked_at_completion_not_only_inspection_start'),
 ('waiting_capacity', 'elif len(pending)>=limit:', 'elif False:', 'test_future_evaluation.py::test_bounded_waiting_room_drop_new_applies_equally'),
 ('independent_sampling_draw', 'if bool(row.selected)!=expected:', 'if False:', 'test_future_evaluation.py::test_audit_selection_is_recomputed_from_frozen_draw'),
 ('source_hash', "if h!=source.get('sha256'):", 'if False:', 'test_future_evaluation_adversarial.py::test_policy_source_hash_and_path_checks[hash]'),
 ('expiry_equality', 'if expires[e]<=at:', 'if expires[e]<at:', 'test_future_evaluation_adversarial.py::test_expiry_at_same_clock_releases_capacity_before_new_arrival'),
]


def run(root,output):
    root=Path(root).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    assert output.is_relative_to(root)
    code=(root/'future_evaluation_core.py').read_text(encoding='utf-8');original_hash=sha256((root/'future_evaluation_core.py').read_bytes()).hexdigest()
    records=[]
    for name,old,new,test in MUTATIONS:
        assert code.count(old)==1,(name,'mutation anchor changed; review this trial')
        dest=output/name;dest.mkdir();(dest/'tests').mkdir();(dest/'legacy').mkdir()
        for filename in ['future_evaluation.py','future_evaluation_v2.py','historical_sources.py']:
            shutil.copyfile(root/filename,dest/filename)
        shutil.copyfile(root/'legacy/future_evaluation_v1.py',dest/'legacy/future_evaluation_v1.py')
        for filename in ['test_future_evaluation.py','test_future_evaluation_v2.py','test_future_evaluation_adversarial.py']:
            shutil.copyfile(root/'tests'/filename,dest/'tests'/filename)
        (dest/'pytest.ini').write_text('[pytest]\npythonpath = .\n',encoding='utf-8')
        case='tests/'+test
        def trial(variant,source):
            (dest/'future_evaluation_core.py').write_text(source,encoding='utf-8')
            junit=dest/(variant+'.xml')
            cmd=[sys.executable,'-B','-m','pytest',case,'-q','-p','no:cacheprovider','--tb=short','--basetemp',str(dest/(variant+'_temp')),'--junitxml',str(junit)]
            process=subprocess.run(cmd,cwd=dest,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
            (dest/(variant+'.txt')).write_text(process.stdout+'\n'+process.stderr,encoding='utf-8')
            suite=ET.parse(junit).getroot().find('testsuite')
            return {'returncode':process.returncode,'tests':int(suite.attrib['tests']),'failures':int(suite.attrib['failures']),'errors':int(suite.attrib['errors'])}
        baseline=trial('baseline',code);mutant=trial('mutant',code.replace(old,new))
        killed=baseline=={'returncode':0,'tests':1,'failures':0,'errors':0} and mutant=={'returncode':1,'tests':1,'failures':1,'errors':0}
        records.append({'mutation':name,'test':case,'baseline':baseline,'mutant':mutant,'detected_by_assertion_failure':killed})
    assert sha256((root/'future_evaluation_core.py').read_bytes()).hexdigest()==original_hash
    result={'mutation_trials':records,'detected':sum(r['detected_by_assertion_failure'] for r in records),'total':len(records),
        'production_core_unchanged':True,'scope':'eight selected regressions, not exhaustive mutation coverage','new_performance_evidence':False}
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if result['detected']!=result['total']:raise AssertionError('An important mutation survived or the trial errored; inspect summary.json')
    return result
