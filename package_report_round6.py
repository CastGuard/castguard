"""Create a new private export with disclosed path-only metadata normalization."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, json, re, shutil, zipfile
from package_report import selected_files, safe_name, extract_verified
from report_evidence import sha
ROOT=Path(__file__).resolve().parent
EXTRA=['ROUND6_README.md','judge_baselines.py','verify_judge_baselines.py',
       'build_submission_round6.py','render_submission_round6.py','package_report_round6.py',
       'docs/OCT03_JUDGE_REVIEW_PROTOCOL.md']

def make(root, stage, destination):
    if stage.exists() or destination.exists(): raise FileExistsError('Use new export and archive paths')
    files=set(selected_files(root)+[root/x for x in EXTRA])
    files.update(p for p in (root/'reports/submission_round6').rglob('*')
                 if p.is_file() and not {'baselines','checks'}.intersection(p.relative_to(root).parts))
    stage.mkdir(parents=True)
    for src in sorted(files):
        rel=src.relative_to(root).as_posix()
        assert safe_name(rel) and not src.is_symlink()
        dst=stage/rel; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    lineage=stage/'reports/oct03_evidence/final/lineage_audit.json'
    before={p.relative_to(stage).as_posix():sha(p) for p in stage.rglob('*') if p.is_file()}
    content=json.loads(lineage.read_text(encoding='utf-8'))
    original_without_source={k:v for k,v in content.items() if k!='source'}
    content['source']='data/raw'
    lineage.write_text(json.dumps(content,ensure_ascii=False,indent=2),encoding='utf-8')
    assert {k:v for k,v in json.loads(lineage.read_text(encoding='utf-8')).items() if k!='source'}==original_without_source
    receipt=stage/'reports/oct03_evidence/final/receipt.json'
    payload=json.loads(receipt.read_text(encoding='utf-8'))
    payload['output_hashes']['lineage_audit.json']=sha(lineage)
    receipt.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    from build_report import build as build_old
    from build_submission_round6 import build as build_new
    build_old(stage); build_new(stage)
    changed={name:{'original_sha256':old,'export_sha256':sha(stage/name)} for name,old in before.items() if sha(stage/name)!=old}
    allowed={'reports/oct03_evidence/final/lineage_audit.json','reports/oct03_evidence/final/receipt.json',
             'reports/submission_draft/evidence_index.json','reports/submission_round6/report_evidence.json'}
    assert set(changed)<=allowed,changed
    # In particular, all data, predictions, models, report words and visual files remain byte-identical.
    transforms={'created_at':datetime.now(timezone.utc).isoformat(),
      'reason':'Export-only normalization of historical local user path to relative data/raw, and dependent hashes. Original project evidence is untouched.',
      'changed_files':changed,'data_predictions_report_text_unchanged':True,
      'historical_qa_receipts':'Round5 receipts describe the original archive at its creation; current PACKAGE_MANIFEST and replay apply to this export.'}
    (stage/'EXPORT_TRANSFORMS.json').write_text(json.dumps(transforms,ensure_ascii=False,indent=2),encoding='utf-8')
    all_files=sorted(p for p in stage.rglob('*') if p.is_file())
    findings=[]
    # Known local participant identifier only. This is not a general identity or legal clearance.
    for p in all_files:
        raw=p.read_bytes()
        texts=[raw.decode(enc,errors='ignore') for enc in ('utf-8','utf-16-le','utf-16-be')]
        if any(re.search(r'Users[\\/]+JH(?:[\\/]|\b)',t,re.I) for t in texts):
            findings.append(p.relative_to(stage).as_posix())
    if findings: raise ValueError('Known local path remains: '+str(findings))
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),
      'purpose':'private review; native HWPX, real fields and final blind clearance incomplete',
      'files':{p.relative_to(stage).as_posix():sha(p) for p in all_files},
      'known_local_user_path_scan':{'encodings':['utf-8','utf-16-le','utf-16-be'],'matches':0},
      'blind_submission_clearance':False,'native_hwpx_created':False,
      'fresh_environment_retraining_verified':False,
      'omitted':['initial correlated random diagnostic','caches','credentials','strategy/daily logs','installed fonts']}
    (stage/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in sorted(stage.rglob('*')):
            if p.is_file(): archive.write(p,p.relative_to(stage).as_posix())
    return {'archive':destination.name,'bytes':destination.stat().st_size,'sha256':sha(destination),
      'file_hashes':len(all_files),'entries':len(all_files)+1,'metadata_transforms':len(changed),
      'known_local_user_path_matches':0,'blind_submission_clearance':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(make(ROOT,args.stage.resolve(),args.output.resolve()),ensure_ascii=False,indent=2))
