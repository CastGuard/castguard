"""Research-only inference for a sealed model/data combination; no automatic deployment."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from .data import digest
from .model_search import predict
from .submission_reader import features_from_packet,FB,SCHEMA


class CrossedReader:
    def __init__(self,root,selection='primary'):
        self.root=Path(root).resolve();self.out=self.root/'reports/oct08_crossed_search'
        self.seal=json.loads((self.out/'selection_seal.json').read_text(encoding='utf-8'))
        if selection=='primary':self.identity=self.seal['primary_winner']
        elif selection=='feedback':self.identity=self.seal['feedback_winner']
        else:self.identity=self.seal['winners'][selection]
        self.representation=self.identity.split('::')[0]
        self.weights=self.seal['definitions'][self.identity];self.models=[]
        for identity,weight in self.weights.items():
            for seed in [17,29,43]:
                path=Path('reports/oct08_crossed_search/candidates')/identity/str(seed)/'within_run__primary/model.joblib'
                full=(self.root/path).resolve()
                if not full.is_relative_to(self.root):raise ValueError('invalid model path')
                k=next((k for k in self.seal['model_hashes'] if Path(k)==path),None)
                if k is None or digest(full)!=self.seal['model_hashes'][k]:raise ValueError('changed checkpoint')
                self.models.append((weight/3,joblib.load(full)))
        self.source=None
        if any('transfer_score' in m['features'] for _,m in self.models):
            if digest(self.out/'source/model.joblib')!=self.seal['source_sha256']:raise ValueError('changed source model')
            self.source=joblib.load(self.out/'source/model.joblib')
        self.features=sorted({f for _,m in self.models for f in m['features'] if f!='transfer_score'})
        self.threshold=self.seal['thresholds'][self.identity]['within_run__primary']

    def score(self,frame):
        if not len(frame) or not set(self.features).issubset(frame):raise ValueError('empty/missing model inputs')
        out=np.zeros(len(frame),float)
        for weight,payload in self.models:
            part=frame
            if 'transfer_score' in payload['features']:
                part=frame.copy()
                x=payload['target_ecdf'].transform(part[list(self.source['mapping'].values())])
                part['transfer_score']=self.source['model'].predict_proba(x)[:,1]
            out+=weight*predict(payload,part)
        return out

    def review(self,envelope):
        if envelope.get('schema_version')!=SCHEMA or not isinstance(envelope.get('records'),list):raise ValueError('unsupported schema')
        records=[]
        for record in envelope['records']:
            row=dict(record_id=record.get('record_id') if isinstance(record,dict) else None)
            try:
                values,_=features_from_packet(record,self.features)
                missing=[f for f in self.features if f not in FB and not np.isfinite(values.get(f,np.nan))]
                if missing:raise ValueError('missing input: '+', '.join(missing))
                score=float(self.score(pd.DataFrame([values]))[0])
                row.update(status='experimental_score',score=score,threshold=self.threshold,risk_flag=score>=self.threshold)
            except (ValueError,TypeError,KeyError,OverflowError) as exc:row.update(status='invalid_or_incomplete_input',reason=str(exc))
            records.append(row)
        return dict(selection=self.identity,representation=self.representation,weights=self.weights,
            uses_past_quality_feedback=self.representation.endswith('_FB'),
            interpretation='uncalibrated offline research score; no validated field benefit or actuation',records=records)


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--selection',default='primary')
    a=p.parse_args();dest=Path(a.output)
    if dest.exists():raise FileExistsError('output exists')
    result=CrossedReader(Path.cwd(),a.selection).review(json.loads(Path(a.input).read_text(encoding='utf-8-sig')))
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
