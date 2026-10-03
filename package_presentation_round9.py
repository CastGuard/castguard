"""Private presentation review kit, not a standalone research/training environment."""
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
import json,re,zipfile
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'reports/presentation_round9'
def make():
    files=['ROUND9_README.md','requirements-presentation.txt','build_presentation_round9.py',
     'export_presentation_round9.ps1','verify_presentation_round9.py','future_evaluation.py','future_evaluation_v2.py',
     'tests/test_future_evaluation.py','tests/test_future_evaluation_v2.py','docs/FUTURE_EVALUATION_V2.md',
     'docs/FUTURE_STATISTICAL_PLAN_ROUND9.md','docs/FUTURE_EVALUATION_CONTRACT.md','docs/DATA_REQUEST_ROUND8.md']
    files += [(OUT/p).relative_to(ROOT).as_posix() for p in ['CastGuard_presentation_draft.pptx','CastGuard_presentation_draft.pdf',
     'SPEAKER_NOTES.md','JUDGE_QA.md','COMPETITION_REVIEW.md','slide_evidence.json','layout_geometry.json',
     'checks/native_export.json','checks/artifact_verification.json','checks/visual_qa.json','checks/regression_summary.json']]
    files += [p.relative_to(ROOT).as_posix() for p in sorted((OUT/'rendered').glob('*.png'))]
    hashes={}
    for path in files:
        raw=(ROOT/path).read_bytes()
        for encoding in ['utf-8','utf-16-le','utf-16-be']:
            assert not re.search(r'Users[\\/]+JH(?:[\\/]|\b)',raw.decode(encoding,errors='ignore'),re.I),path
        hashes[path]=sha256(raw).hexdigest()
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'purpose':'private presentation review kit',
      'standalone_research_reproduction':False,'source_paths_refer_to_existing_project':True,
      'readme':'ROUND9_README.md','files':hashes,'known_personal_path_matches':0,
      'full_blind_submission_clearance':False,'new_performance_evidence':False}
    dest=ROOT/'deliverables/CastGuard_presentation_round9.zip';dest.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in files:archive.write(ROOT/path,path)
        archive.writestr('PRESENTATION_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    receipt={'archive':dest.name,'bytes':dest.stat().st_size,'sha256':sha256(dest.read_bytes()).hexdigest(),
      'entries':len(files)+1,'file_hashes':len(files),'standalone_training_environment':False}
    (OUT/'checks/package_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt
if __name__=='__main__':print(json.dumps(make(),ensure_ascii=False))
