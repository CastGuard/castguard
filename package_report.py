"""Create a private, allowlisted review package; never include caches or credentials."""
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
import argparse,json,zipfile,re
from report_evidence import sha
ROOT=Path(__file__).resolve().parent
ROOT_FILES=['requirements.txt','requirements-lock.txt','requirements-report.txt','pyproject.toml',
 'audit_oct03_evidence.py','diagnose_oct03.py','gate_uncertainty_oct03.py','oct03_research.py',
 'oct03_queue.py','verify_oct03.py','verify_oct03_queue.py','report_evidence.py','build_report.py',
 'render_report_pdf.py','replay_report.py','run_review_tests.py','package_report.py','PACKAGE_README.md']
TREES=['castguard','configs','data/raw','data/processed','tests','notebooks','docs/sources/oct03_round4',
 'reports/oct02','reports/oct03_pilot_r2','reports/oct03_review','reports/oct03_queue',
 'reports/oct03_queue_review','reports/oct03_evidence','reports/submission_draft']
DOCS=['EXPERIMENT_PROTOCOL.md','OCT03_PILOT_PROTOCOL.md','OCT03_QUEUE_PROTOCOL.md',
 'PREPROCESSING.md','EVIDENCE_AND_SUBMISSION_2026-10-03.md','REPORT_DRAFT_TEMPLATE.md']

def safe_name(name):
    p=PurePosixPath(name)
    return (not p.is_absolute() and '..' not in p.parts and '\\' not in name and ':' not in name
        and all(part not in ['.git','.venv','.env','__pycache__','.pytest_cache','artifacts','checks'] for part in p.parts))

def selected_files(root):
    files=[root/x for x in ROOT_FILES]+[root/'docs'/x for x in DOCS]
    for name in TREES:
        files.extend(p for p in (root/name).rglob('*') if p.is_file() and safe_name(p.relative_to(root).as_posix()) and p.suffix!='.pyc')
    files+=list((root/'docs').glob('*.hwpx'))
    result=sorted(set(files),key=lambda p:p.relative_to(root).as_posix())
    for p in result:
        assert safe_name(p.relative_to(root).as_posix()) and not p.is_symlink()
        assert p.is_file(),str(p)
    return result

def make_package(root,dest):
    from replay_report import replay
    replay(root)
    if dest.exists(): raise FileExistsError(dest)
    files=selected_files(root)
    privacy=[]
    for p in files:
        if p.suffix in ['.py','.json','.md','.txt','.html','.csv','.ipynb','.toml']:
            text=p.read_text(encoding='utf-8',errors='replace')
            if re.search(r'C:[/\\]+Users[/\\]|C:/Users|Desktop[/\\]+workspace',text,re.I):
                privacy.append(p.relative_to(root).as_posix())
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'purpose':'private review; not submission-ready',
      'files':{p.relative_to(root).as_posix():sha(p) for p in files},
      'omitted':['.git','.venv','artifacts caches','local fonts','personal strategy and daily logs'],
      'historical_local_path_files':privacy,'blind_submission_clearance':False,
      'fresh_environment_retraining_verified':False}
    dest.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in files: z.write(p,p.relative_to(root).as_posix())
        z.writestr('PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return {'archive':str(dest),'sha256':sha(dest),'files':len(files)+1,'bytes':dest.stat().st_size,
      'historical_local_path_files':privacy,'blind_submission_clearance':False}

def extract_verified(archive,dest):
    if dest.exists(): raise FileExistsError('Use a new directory')
    base=dest.resolve()
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)): raise ValueError('Duplicate archive paths')
        for name in names:
            if not safe_name(name) or not (base/name).resolve().is_relative_to(base): raise ValueError('Unsafe archive path')
        z.extractall(base)
    from replay_report import check_hashes
    manifest=json.loads((base/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    return check_hashes(base,manifest['files'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(make_package(ROOT,a.output),ensure_ascii=False,indent=2))
