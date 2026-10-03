"""New private review archive; preserve old versions and disclose metadata-only normalization."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,re,shutil,zipfile
from package_report import selected_files,safe_name
from castguard.data import digest
ROOT=Path(__file__).resolve().parent
EXTRA=['ROUND6_README.md','ROUND7_README.md','ROUND8_README.md','judge_baselines.py','verify_judge_baselines.py',
 'build_submission_round6.py','render_submission_round6.py','package_report_round6.py',
 'diagnose_round7.py','summarize_round7.py','verify_round7.py','build_round7_report.py',
 'future_evaluation.py','build_round8_report.py','render_submission_round8.py','verify_round8.py','package_round8.py',
 'docs/OCT03_JUDGE_REVIEW_PROTOCOL.md','docs/OCT03_ROUND7_DIAGNOSTIC_PROTOCOL.md',
 'docs/FUTURE_EVALUATION_CONTRACT.md','docs/DATA_REQUEST_ROUND8.md',
 'docs/TODAY_CLOSEOUT_2026-10-03.md','docs/TEAM_HANDOFF_2026-10-03.md']

def make(root,stage,dest):
    if stage.exists() or dest.exists():raise FileExistsError('Use new stage and archive paths')
    files=set(selected_files(root)+[root/p for p in EXTRA])
    for tree in ['reports/submission_round6','reports/oct03_round7','reports/submission_round8','templates/future_evaluation']:
        files.update(p for p in (root/tree).rglob('*') if p.is_file() and not {'baselines','checks'}.intersection(p.relative_to(root).parts))
    stage.mkdir(parents=True)
    for src in sorted(files):
        relative=src.relative_to(root).as_posix();assert safe_name(relative) and not src.is_symlink()
        dst=stage/relative;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    shutil.copy2(root/'ROUND8_README.md',stage/'README.md')
    # Keep the legacy archive's exclusion of checks/ paths and personal pytest XML.
    shutil.copy2(root/'reports/submission_round8/checks/validation.json',stage/'VALIDATION_SUMMARY.json')
    before={p.relative_to(stage).as_posix():digest(p) for p in stage.rglob('*') if p.is_file()}
    lineage=stage/'reports/oct03_evidence/final/lineage_audit.json';content=json.loads(lineage.read_text(encoding='utf-8'))
    previous={k:v for k,v in content.items() if k!='source'};content['source']='data/raw'
    lineage.write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
    assert {k:v for k,v in content.items() if k!='source'}==previous
    receipt=stage/'reports/oct03_evidence/final/receipt.json';value=json.loads(receipt.read_text(encoding='utf-8'))
    value['output_hashes']['lineage_audit.json']=digest(lineage);receipt.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    from build_report import build as build5
    from build_submission_round6 import build as build6
    from build_round8_report import build as build8
    build5(stage);build6(stage);build8(stage)
    changed={p:{'original_sha256':h,'export_sha256':digest(stage/p)} for p,h in before.items() if digest(stage/p)!=h}
    allowed={'reports/oct03_evidence/final/lineage_audit.json','reports/oct03_evidence/final/receipt.json',
       'reports/submission_draft/evidence_index.json','reports/submission_round6/report_evidence.json','reports/submission_round8/report_evidence.json'}
    assert set(changed)<=allowed,changed
    transforms={'reason':'Export-only personal path normalization and dependent evidence hashes. Originals, data, predictions, report text and PDFs are preserved.',
       'changed_files':changed,'historical_receipts':'Earlier receipts describe their creation-time originals; use this package manifest and replay for current export.',
       'entry_readme':'README.md is a copy of ROUND8_README.md; personal strategy/daily logs omitted.'}
    (stage/'EXPORT_TRANSFORMS.json').write_text(json.dumps(transforms,ensure_ascii=False,indent=2),encoding='utf-8')
    payload=sorted(p for p in stage.rglob('*') if p.is_file())
    for p in payload:
        raw=p.read_bytes()
        for encoding in ['utf-8','utf-16-le','utf-16-be']:
            assert not re.search(r'Users[\\/]+JH(?:[\\/]|\b)',raw.decode(encoding,errors='ignore'),re.I),p.relative_to(stage)
    from verify_round8 import verify
    verified=verify(stage)
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'purpose':'private current review; not submission-ready',
      'files':{p.relative_to(stage).as_posix():digest(p) for p in payload},'known_local_user_path_matches':0,
      'blind_submission_clearance':False,'native_hwpx_created':False,'fresh_environment_retraining_verified':False,
      'functional_fixtures_are_synthetic_only':True,'new_performance_evidence':False,'review_verification':verified}
    (stage/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    dest.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(stage).as_posix())
    return {'archive':dest.name,'bytes':dest.stat().st_size,'sha256':digest(dest),'file_hashes':len(payload),'entries':len(payload)+1,
      'metadata_only_transforms':len(changed),'new_performance_evidence':False,'known_local_user_path_matches':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    print(json.dumps(make(ROOT,a.stage.resolve(),a.output.resolve()),ensure_ascii=False,indent=2))
