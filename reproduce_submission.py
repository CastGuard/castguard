"""Recreate the registered experiment in a NEW folder; never overwrite evidence."""
from pathlib import Path
import argparse
from datetime import datetime,timezone
import json
import numpy as np
import pandas as pd
from castguard.data import digest
from castguard.oct06_research import run,write_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--jobs',type=int,default=4);a=p.parse_args()
    root=Path(__file__).resolve().parent;out=(root/a.output).resolve()
    if not out.is_relative_to(root) or out==root or out.exists():raise ValueError('new folder inside package required')
    out.mkdir(parents=True)
    inputs=list((root/'data/raw').glob('*.csv'))+list((root/'data/processed').glob('*'))+[root/'configs/oct06_research.json',root/'docs/OCT06_RESEARCH_PROTOCOL.md']
    write_json(out/'registration.json',{'created_at':datetime.now(timezone.utc).isoformat(),'status':'registered_reproduction',
        'hashes':{f.relative_to(root).as_posix():digest(f) for f in inputs if f.is_file()},'original_selection_sha256':digest(root/'reports/oct06_research/selection.json')})
    run(root,out,a.jobs)
    reference=pd.read_csv(root/'reports/oct06_research/selected_metrics.csv',dtype={'fold':str})
    actual=pd.read_csv(out/'selected_metrics.csv',dtype={'fold':str})
    keys=['scheme','fold','representation','model','seed','role'];cols=['ap','auc','brier','threshold','tp','fp','fn','tn','capture20']
    left=reference.set_index(keys).sort_index();right=actual.set_index(keys).sort_index()
    if not left.index.equals(right.index):raise AssertionError('selection identities differ')
    assert np.allclose(left[cols],right[cols],rtol=1e-8,atol=1e-10,equal_nan=True),'metric mismatch'
    receipt={'passed':True,'rows':len(left),'columns':cols,'max_absolute_difference':float(np.nanmax(abs(left[cols]-right[cols]))),
             'status':'same-data computational reproduction, not independent performance validation',
             'completed_at':datetime.now(timezone.utc).isoformat()}
    write_json(out/'reproduction_check.json',receipt);print(json.dumps(receipt))


if __name__=='__main__':main()
