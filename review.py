"""Start here: inspect a local review bundle, recompute evidence, or list prerequisites."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import argparse,importlib.metadata,json,os,subprocess,sys,uuid

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def verify_manifest(root=ROOT,required=False):
    path=root/'PACKAGE_MANIFEST.json'
    if not path.exists():
        if required:raise ValueError('PACKAGE_MANIFEST.json is required in an extracted review bundle')
        return {'present':False,'context':'working project; package integrity check unavailable'}
    data=json.loads(path.read_text(encoding='utf-8'));files=data['files']
    for name,h in files.items():
        relative=Path(name);p=(root/relative).resolve()
        if relative.is_absolute() or relative.drive or '..' in relative.parts or not p.is_relative_to(root.resolve()):raise ValueError('unsafe manifest path')
        if not p.is_file() or sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('package integrity mismatch: '+name)
    return {'present':True,'file_hashes_verified':len(files),'purpose':data['purpose']}


def environment():
    from review_environment import inspect
    return inspect(ROOT)


def check_document_bindings(root=ROOT):
    """Always check current evidence pointers, even without optional PDF/PPTX libraries."""
    root=Path(root).resolve()
    def hashed(name):
        relative=Path(name);path=(root/relative).resolve()
        if relative.is_absolute() or relative.drive or '..' in relative.parts or not path.is_relative_to(root):raise ValueError('document evidence path escapes review root')
        return sha256(path.read_bytes()).hexdigest()
    report=json.loads((root/'review/report_evidence.json').read_text(encoding='utf-8'))
    slides=json.loads((root/'review/slide_evidence.json').read_text(encoding='utf-8'))
    for collection in [report['metrics'],slides['numeric_metrics']]:
        for name,item in collection.items():
            if hashed(item['source'])!=item['sha256']:raise ValueError('document metric source mismatch: '+name)
    for name,h in slides['source_hashes'].items():
        if hashed(name)!=h:raise ValueError('presentation source mismatch: '+name)
    if hashed('review/CastGuard_report.md')!=report['report_sha256']:raise ValueError('current report text hash mismatch')
    if hashed('review/CastGuard_presentation.pptx')!=slides['pptx_sha256']:raise ValueError('current presentation hash mismatch')
    render=json.loads((root/'review/render_receipt.json').read_text(encoding='utf-8'))
    for name,key in [('CastGuard_report.md','markdown_sha256'),('CastGuard_report.html','html_sha256'),('CastGuard_report.pdf','pdf_sha256')]:
        if hashed('review/'+name)!=render[key]:raise ValueError('current report export mismatch: '+name)
    return {'report_metrics':len(report['metrics']),'slide_metrics':len(slides['numeric_metrics']),
        'source_and_export_hashes_match':True,'rendered_layout_checked_by_this_function':False}


def child_run(arguments,cwd=ROOT):
    env=dict(os.environ)
    env.pop('PYTHONPATH',None);env['PYTHONNOUSERSITE']='1';env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1';env['PYTHONIOENCODING']='utf-8'
    return subprocess.run([sys.executable,'-B']+arguments,cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')


def run_checks(root=ROOT,full=False,require_package=False):
    from review_environment import require
    runtime=require(root)
    from review_metrics import recompute,compare_saved
    from review_mutations import run as mutations
    from review_readiness import assess
    integrity=verify_manifest(root,require_package)
    document_bindings=check_document_bindings(root)
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    output=root/'verification_runs'/name;output.mkdir(parents=True,exist_ok=False)
    save=lambda name,item:(output/name).write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8')
    save('environment.json',runtime)
    metrics=recompute(root);compare_saved(metrics,root);save('independent_metrics.json',metrics)
    command=['-m','pytest','tests','-q','-p','no:cacheprovider','--tb=short','--basetemp',str(output/'pytest_temp'),'--junitxml',str(output/'tests.xml')]
    tests=child_run(command,root);(output/'tests.txt').write_text(tests.stdout+'\n'+tests.stderr,encoding='utf-8')
    if tests.returncode:raise RuntimeError('Regression failure; inspect '+(output/'tests.txt').relative_to(root).as_posix())
    mutation_result=mutations(root,output/'mutation_trials');save('mutation_summary.json',mutation_result)
    full_result=None
    if full:
        full_run=child_run(['replay_report.py','--full-evidence'],root)
        (output/'full_replay.txt').write_text(full_run.stdout+'\n'+full_run.stderr,encoding='utf-8')
        if full_run.returncode:raise RuntimeError('Historical replay failure; inspect full_replay.txt')
        full_result=json.loads(full_run.stdout)
    prerequisite=assess(root)
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'review_status':'passed_with_external_prerequisites',
        'receipt_directory':output.relative_to(root).as_posix(),'package_integrity':integrity,
        'current_document_bindings':document_bindings,
        'independent_core_metrics_match_saved_results':True,'test_returncode':tests.returncode,
        'important_mutations_detected':mutation_result['detected'],'important_mutations_tried':mutation_result['total'],
        'full_saved_evidence_replay':full_result,'external_prerequisites':prerequisite,
        'included_data_suffices_for_completed_checks':True,'private_originals_required_for_completed_checks':False,
        'dependency_pins_match':True,'installation_provenance_checked_by_this_command':False,'whole_model_retraining_performed':False,
        'new_performance_evidence':False,'actual_submission_completed':False}
    save('summary.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    check=sub.add_parser('check',help='verify the package, raw-data arithmetic, regression tests and eight mutation trials')
    check.add_argument('--full-replay',action='store_true');check.add_argument('--require-package',action='store_true')
    sub.add_parser('metrics',help='recompute selected core metrics from included raw defects and actions')
    envcheck=sub.add_parser('environment',help='inspect Python and exact dependency pins without installing anything')
    envcheck.add_argument('--documents',action='store_true')
    ready=sub.add_parser('ready',help='list missing external prerequisites; this never submits anything')
    ready.add_argument('--evidence',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='check':result=run_checks(full=args.full_replay,require_package=args.require_package)
        elif args.command=='metrics':
            from review_metrics import recompute,compare_saved
            result=recompute();compare_saved(result)
        elif args.command=='environment':
            from review_environment import inspect
            result=inspect(ROOT,documents=args.documents)
        else:
            from review_readiness import assess
            record=json.loads(args.evidence.read_text(encoding='utf-8')) if args.evidence else None
            result=assess(ROOT,record)
        displayed=result
        if args.command=='check':
            displayed={key:result[key] for key in ['review_status','receipt_directory','package_integrity','current_document_bindings',
                'independent_core_metrics_match_saved_results','test_returncode','important_mutations_detected','important_mutations_tried',
                'dependency_pins_match','installation_provenance_checked_by_this_command','new_performance_evidence']}
            displayed['full_saved_replay_passed']=result['full_saved_evidence_replay'] is not None
            displayed['submission_missing']=result['external_prerequisites']['submission_missing']
        print(json.dumps(displayed,ensure_ascii=False,indent=2))
        return 2 if (args.command=='ready' and result['submission_missing']) or (args.command=='environment' and result['status']!='passed') else 0
    except ModuleNotFoundError as exc:
        print(json.dumps({'status':'blocked','reason':str(exc),'action':'Install the listed requirements-lock.txt dependencies in Python 3.12; no automatic installation performed.'}));return 2
    except (OSError,ValueError,AssertionError,RuntimeError) as exc:
        print(json.dumps({'status':'blocked','reason':str(exc)},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
