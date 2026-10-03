"""Read-only replay of frozen evidence; optionally write a new receipt to an explicit path."""
from pathlib import Path
from datetime import datetime, timezone
import argparse,json
from report_evidence import sha
from build_report import build
ROOT=Path(__file__).resolve().parent

def check_hashes(base, hashes, historical=False):
    base=base.resolve()
    for name, expected in hashes.items():
        path=(base/name).resolve()
        if not path.is_relative_to(base): raise ValueError('Unsafe evidence path: '+name)
        if historical:
            from historical_sources import resolve_historical_source
            resolve_historical_source(base,name,expected)
        elif sha(path)!=expected: raise ValueError('Evidence hash mismatch: '+name)
    return len(hashes)

def replay(root=ROOT,full=False):
    root=root.resolve()
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'report':build(root,check=True),
        'new_training':False,'new_independent_test':False,'read_only_evidence':True}
    package=root/'PACKAGE_MANIFEST.json'
    if package.exists():
        result['package_files_verified']=check_hashes(root,json.loads(package.read_text(encoding='utf-8'))['files'])
    out=root/'reports/submission_draft'
    render=json.loads((out/'render_receipt.json').read_text(encoding='utf-8'))
    assert sha(out/'CastGuard_report_draft.md')==render['markdown_sha256']
    assert sha(out/'CastGuard_report_draft.pdf')==render['pdf_sha256']
    audit=root/'reports/oct03_evidence/final'
    receipt=json.loads((audit/'receipt.json').read_text(encoding='utf-8'))
    result['audit_inputs_verified']=check_hashes(root,receipt['input_hashes'],historical=True)
    result['audit_outputs_verified']=check_hashes(audit,receipt['output_hashes'])
    if full:
        # Each verifier validates manifests BEFORE loading any trusted saved model.
        from castguard.verify import verify_delivery
        from verify_oct03 import verify
        from verify_oct03_queue import check
        result['oct02']=verify_delivery(root,root/'reports/oct02')
        result['pilot']=verify(root,root/'reports/oct03_pilot_r2')
        result['queue']=check(root,root/'reports/oct03_queue')
    result['status']='passed'
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--full-evidence',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.output and a.output.exists(): raise FileExistsError('Use a new receipt path')
    result=replay(full=a.full_evidence)
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text,encoding='utf-8')
    print(text)
