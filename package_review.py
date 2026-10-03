"""Create one current local review archive from a verified historic export plus current files."""
from pathlib import Path,PurePosixPath
from hashlib import sha256
from datetime import datetime,timezone
import argparse,json,re,shutil,stat,sys,zipfile

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
BASE_SHA='42da528b13734c2f78dd4488ac73171496a1d805e505864f363f42264ffde4f1'
CURRENT_FILES=['CURRENT_REVIEW.md','review.py','review_metrics.py','review_readiness.py','review_mutations.py',
 'experiment_integrity.py','oct03_research.py','oct03_queue.py','verify_oct03.py','verify_oct03_queue.py','replay_report.py',
 'audit_queue_opportunity.py','reports/today_closeout/checks/queue_budget_tests.json','reports/today_closeout/checks/queue_budget_full_audit.json',
 'audit_missing_quality.py','reports/today_closeout/checks/missing_quality_tests.json','reports/today_closeout/checks/missing_quality_full_audit.json',
 'audit_today_experiments.py','reports/today_closeout/checks/experiment_regressions.json','reports/today_closeout/EXPERIMENT_REVIEW.md','reports/today_closeout/experiment_integrity_final.json',
 'audit_package_contents.py','docs/USER_SCOPE_2026-10-03.md','docs/ROADMAP.md','docs/TODAY_CLOSEOUT_2026-10-03.md',
 'docs/DAILY_REVIEW.md',
 'docs/STRATEGY.md','docs/SUBMISSION.md','docs/EXPERIMENTS_NEXT.md','docs/TEAM_HANDOFF_2026-10-03.md',
 'docs/archive/before_today_closeout/docs/SUBMISSION_EVIDENCE_STATUS.md',
 'review_environment.py','review_retrain.py','requirements-review-lock.txt','requirements-review-win-py312.lock',
 'docs/CLEAN_REPRODUCTION_PROTOCOL.md','docs/CLEAN_REPRODUCTION_RESULT.md',
 'docs/SUBMISSION_EVIDENCE_STATUS.md','docs/sources/oct03_submission_review/fetch_receipt.json',
 'build_review.py','verify_review_documents.py','package_review.py','export_review_presentation.ps1',
 'requirements-report.txt','requirements-presentation.txt','future_evaluation.py','future_evaluation_v2.py','future_evaluation_core.py',
 'historical_sources.py','verify_round8.py',
 'docs/FUTURE_EVALUATION_CONTRACT.md','docs/FUTURE_EVALUATION_V2.md','docs/FUTURE_STATISTICAL_PLAN_ROUND9.md',
 'docs/DATA_REQUEST_ROUND8.md','docs/FUTURE_VALIDATION_REVIEW_ROUND10.md','docs/COMPETITION_READINESS_ROUND10.md',
 'reports/presentation_round9/CastGuard_presentation_draft.pptx','reports/presentation_round9/slide_evidence.json',
 'reports/presentation_round9/JUDGE_QA.md']


def digest(p):return sha256(p.read_bytes()).hexdigest()
def safe(name):
    p=PurePosixPath(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name


def extract(archive,destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len({name.casefold() for name in names}):raise ValueError('duplicate/case-colliding archive entry')
        for item in z.infolist():
            if not safe(item.filename) or stat.S_ISLNK(item.external_attr>>16) or not (destination/item.filename).resolve().is_relative_to(destination):raise ValueError('unsafe archive entry')
        z.extractall(destination)
    manifest=json.loads((destination/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for name,h in manifest['files'].items():
        if not safe(name) or digest(destination/name)!=h:raise ValueError('archive hash mismatch: '+name)
    return manifest


def make(base_archive,stage,destination):
    base_archive,stage,destination=Path(base_archive),Path(stage),Path(destination)
    if stage.exists() or destination.exists():raise FileExistsError('Use fresh stage and archive paths')
    if digest(base_archive)!=BASE_SHA:raise ValueError('Historic base archive differs from the verified round8 export')
    old=extract(base_archive,stage)
    files=set(CURRENT_FILES)
    for folder in ['reports/today_closeout/queue_opportunity','reports/today_closeout/missing_quality','tests','legacy','docs/archive/round10_legacy','templates/future_evaluation','review']:
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and path.suffix.lower()!='.png' and '__pycache__' not in path.parts and not {'rendered','pdf_rendered'}.intersection(path.parts):
                files.add(path.relative_to(ROOT).as_posix())
    for name in sorted(files):
        src=ROOT/name;dst=stage/name
        if not safe(name) or src.is_symlink():raise ValueError('unsafe current file')
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    shutil.copyfile(ROOT/'CURRENT_REVIEW.md',stage/'README.md')
    # Repository-only navigation is explicit in the portable export. Never add
    # seven nested historical ZIPs or claim the archive includes repository history.
    portable_replacements={
        'docs/SUBMISSION.md':{'[현재 ZIP](../deliverables/CastGuard_latest_review.zip)':'현재 압축해제한 검토 ZIP'},
        'docs/TODAY_CLOSEOUT_2026-10-03.md':{'[일지](daily/2026-10-03.md)':'프로젝트의 `docs/daily/2026-10-03.md` 일지'},
    }
    for name,replacements in portable_replacements.items():
        path=stage/name;content=path.read_text(encoding='utf-8')
        for old_link,new_text in replacements.items():content=content.replace(old_link,new_text)
        path.write_text(content,encoding='utf-8')
    # The verified base had already normalized one private source-directory field;
    # its metric/data bytes and dependent evidence hashes are retained verbatim.
    evidence=stage/'review/evidence';evidence.mkdir(exist_ok=True)
    (evidence/'historic_base_manifest.json').write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
    metadata={'created_at':datetime.now(timezone.utc).isoformat(),'base_archive_sha256':BASE_SHA,
        'base_export':'round8 metadata-normalized export; historic project originals unchanged',
        'overlaid_current_files':sorted(files),'entrypoint':'CURRENT_REVIEW.md and review.py',
        'prior_presentation_is_build_source_only':'reports/presentation_round9/CastGuard_presentation_draft.pptx',
        'current_presentation':'review/CastGuard_presentation.pptx','current_report':'review/CastGuard_report.pdf'}
    (evidence/'package_build.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    # Verify scientific data are byte-identical to the working project.
    for folder in ['data/raw','data/processed']:
        for path in (ROOT/folder).glob('*'):
            if path.is_file():assert digest(path)==digest(stage/path.relative_to(ROOT)),path.name
    from review import check_document_bindings
    check_document_bindings(stage)
    clean=json.loads((stage/'review/checks/clean_environment.json').read_text(encoding='utf-8'))
    if clean['status']!='passed' or clean['hash_locked_install']['packages']!=36:raise ValueError('Clean-install evidence is incomplete')
    current_doc=json.loads((stage/'review/checks/current_rehearsal_verification.json').read_text(encoding='utf-8'))
    if current_doc['status']!='passed':raise ValueError('Current document reproduction is incomplete')
    for name,h in current_doc['current_source_hashes'].items():
        if digest(stage/name)!=h:
            # The document rendering is unchanged. Preserve the old readiness
            # note exactly; the user's newer scope supersedes only this note.
            previous=stage/'docs/archive/before_today_closeout/docs/SUBMISSION_EVIDENCE_STATUS.md'
            if name!='docs/SUBMISSION_EVIDENCE_STATUS.md' or digest(previous)!=h:
                raise ValueError('Current document source changed: '+name)
    for name,h in clean['reproduction_source_hashes'].items():
        if digest(stage/name)!=h:
            # The old clean-install run is historical evidence. Only its document
            # generator may be superseded, with its exact old bytes retained and
            # current rendering separately verified. Scientific bindings stay strict.
            if name!='build_review.py' or digest(stage/'legacy/review_round12/build_review.py')!=h:
                raise ValueError('Clean reproduction source changed: '+name)
    payload=[p for p in stage.rglob('*') if p.is_file() and p.relative_to(stage).as_posix()!='PACKAGE_MANIFEST.json']
    for path in payload:
        raw=path.read_bytes()
        for encoding in ['utf-8','utf-16-le','utf-16-be']:
            if re.search(r'Users[\\/]+JH(?:[\\/]|\b)',raw.decode(encoding,errors='ignore'),re.I):raise ValueError('known personal path in export: '+path.relative_to(stage).as_posix())
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'purpose':'latest private research/review bundle; not final submission',
        'entrypoint':'CURRENT_REVIEW.md','validator_revision':3,
        'files':{p.relative_to(stage).as_posix():digest(p) for p in sorted(payload)},
        'scientific_data_included':True,'private_originals_required_for_included_checks':False,
        'python_runtime_and_wheels_included':False,'fresh_dependency_install_verified':True,
        'fresh_dependency_install_scope':'Windows x64 / CPython 3.12.14 / 36 exact official PyPI wheel hashes; see review/checks/clean_environment.json',
        'current_document_rebuild_evidence':'review/checks/current_rehearsal_verification.json',
        'prior_document_generator_retained':'legacy/review_round12/build_review.py',
        'native_powerpoint_and_system_fonts_required_only_for_rerender':True,
        'known_personal_path_matches':0,'full_blind_submission_clearance':False,
        'new_performance_evidence':False,'actual_submission_completed':False}
    (stage/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(stage.rglob('*')):
            if path.is_file():archive.write(path,path.relative_to(stage).as_posix())
    return {'archive':destination.name,'bytes':destination.stat().st_size,'sha256':digest(destination),
        'entries':len(payload)+1,'file_hashes':len(payload),'known_personal_path_matches':0,
        'current_default_validator_revision':3,'fresh_dependency_install_verified':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',type=Path,default=ROOT/'deliverables/archive/CastGuard_review_round8.zip')
    parser.add_argument('--stage',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(make(args.base,args.stage,args.output),ensure_ascii=False,indent=2))
