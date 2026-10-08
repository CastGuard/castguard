"""Separate experimental ensemble reader. Never replaces the existing ResearchReader."""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .data import digest
from .model_search import predict
from .submission_reader import features_from_packet, FB, SCHEMA


class SearchReader:
    def __init__(self, root, experiment='reports/oct08_model_search'):
        self.root=Path(root).resolve()
        self.out=self.root/experiment
        self.seal=json.loads((self.out/'selection_seal.json').read_text())
        self.models=[]
        for identity,weight in self.seal['weights'].items():
            seeds=[17] if identity=='baseline' else [17,29,43]
            for seed in seeds:
                relative=Path('reports/oct08_model_search/candidates')/identity/str(seed)/'within_run__primary/model.joblib'
                p=(self.root/relative).resolve()
                if not p.is_relative_to(self.root):raise ValueError('invalid model path')
                # Registry path spelling follows Windows Path formatting.
                key=next((k for k in self.seal['model_hashes'] if Path(k)==relative),None)
                if key is None or digest(p)!=self.seal['model_hashes'][key]:raise ValueError('model hash mismatch')
                self.models.append((weight/len(seeds),joblib.load(p)))
        self.features=sorted({f for _,m in self.models for f in m['features']})
        self.threshold=self.seal['thresholds'][self.seal['winner']]['within_run__primary']

    def score(self, frame):
        if not len(frame):raise ValueError('empty frame')
        if not set(self.features).issubset(frame):raise ValueError('missing model inputs')
        return sum(w*predict(m,frame) for w,m in self.models)

    def review(self,envelope):
        if envelope.get('schema_version')!=SCHEMA or not isinstance(envelope.get('records'),list):
            raise ValueError('unsupported input schema')
        output=[]
        for record in envelope['records']:
            result={'record_id':record.get('record_id') if isinstance(record,dict) else None}
            try:
                values,_=features_from_packet(record,self.features)
                missing=[f for f in self.features if f not in FB and not np.isfinite(values.get(f,np.nan))]
                if missing:raise ValueError('missing inputs: '+', '.join(missing))
                score=float(self.score(pd.DataFrame([values]))[0])
                result.update(status='experimental_score',score=score,threshold=self.threshold,risk_flag=bool(score>=self.threshold))
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                result.update(status='invalid_or_incomplete_input',reason=str(exc))
            output.append(result)
        return dict(model=self.seal['winner'],weights=self.seal['weights'],validation_criteria_met=self.seal['qualifies'],
                    interpretation='uncalibrated offline research score; future/field adoption unverified',
                    automatic_control=False,records=output)


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();dest=Path(args.output)
    if dest.exists():raise FileExistsError('Refusing to overwrite output')
    result=SearchReader(Path.cwd()).review(json.loads(Path(args.input).read_text(encoding='utf-8-sig')))
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
