"""Inspect actual training data, frozen partitions and test predictions inside a local ZIP."""
from pathlib import Path
from io import BytesIO
from hashlib import sha256
from datetime import datetime, timezone
import argparse, json, zipfile
import pandas as pd

RAW = ['data/raw/DieCasting_Quality_Raw_Data.csv', 'data/raw/DieCasting_Raw_Data.csv',
       'data/raw/Investment_Casting.csv']
TABLES = {'q42':'data/processed/joined.parquet', 'm41':'data/processed/m41_timeline.parquet',
          'p40':'data/processed/d40_clean.parquet'}


def inspect(archive, project=None):
    archive=Path(archive)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate ZIP names')
        required=RAW+list(TABLES.values())+['data/processed/folds.csv','reports/oct02/predictions.parquet',
            'requirements.txt','requirements-lock.txt','README.md','castguard/data.py','castguard/experiment.py']
        missing=set(required)-set(names)
        if missing:raise ValueError('Required actual payload missing: '+', '.join(sorted(missing)))
        manifest=json.loads(z.read('PACKAGE_MANIFEST.json'))['files']
        evidence={}
        for name in required:
            raw=z.read(name);digest=sha256(raw).hexdigest()
            if not raw or manifest.get(name)!=digest:raise ValueError('Empty or unbound payload: '+name)
            if project is not None and name.startswith(('data/','reports/')):
                if sha256((Path(project)/name).read_bytes()).hexdigest()!=digest:
                    raise ValueError('Scientific payload differs from project: '+name)
            evidence[name]={'bytes':len(raw),'sha256':digest}
        folds=pd.read_csv(BytesIO(z.read('data/processed/folds.csv')),low_memory=False)
        pred=pd.read_parquet(BytesIO(z.read('reports/oct02/predictions.parquet')))
        keys=['dataset','scheme','fold','row_id','role']
        if folds[keys].isna().any().any() or pred[keys].isna().any().any():raise ValueError('Missing partition keys')
        for frame in [folds,pred]:
            for key in keys:frame[key]=frame[key].astype(str)
        if folds.duplicated(keys).any():raise ValueError('Duplicated frozen partition keys')
        if pred.role.isin(['train','excluded']).any() or set(pred.role)!={'test','validation'}:
            raise ValueError('Unexpected prediction role')
        if pred.row_id.str.contains('SYNTHETIC|FIXTURE',case=False,regex=True).any():
            raise ValueError('Fixture identifier in real predictions')
        # Every prediction must have the exact frozen dataset/scheme/fold/row/role.
        joined=pred[keys].merge(folds[keys],how='left',on=keys,indicator=True,validate='many_to_one')
        if not joined['_merge'].eq('both').all():raise ValueError('Prediction outside frozen partition')
        if pred[['probability','prediction','y','threshold']].isna().any().any():raise ValueError('Missing predictions')
        if not pred.probability.between(0,1).all() or not pred.y.isin([0,1]).all():raise ValueError('Invalid prediction values')
        rows={}
        for dataset,name in TABLES.items():
            source=pd.read_parquet(BytesIO(z.read(name)))
            ids=source.row_id.astype(str)
            if ids.duplicated().any():raise ValueError('Duplicate source row ID')
            training=folds.loc[(folds.dataset==dataset)&(folds.role=='train')]
            pp=pred.loc[pred.dataset==dataset]
            if training.empty or not training.row_id.isin(ids).all() or not pp.row_id.isin(ids).all():
                raise ValueError('Actual training/prediction source rows unavailable: '+dataset)
            rows[dataset]={'processed_rows':len(source),'train_partition_rows':len(training),
                'unique_training_row_ids':int(training.row_id.nunique()),'test_prediction_rows':int(pp.role.eq('test').sum()),
                'validation_prediction_rows':int(pp.role.eq('validation').sum())}
        return {'checked_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
            'archive_name':archive.name,'archive_sha256':sha256(archive.read_bytes()).hexdigest(),
            'zip_entries':len(names),'required_payload':evidence,'datasets':rows,
            'prediction_rows':len(pred),'test_prediction_rows':int(pred.role.eq('test').sum()),
            'validation_prediction_rows':int(pred.role.eq('validation').sum()),
            'train_partition_rows':int(folds.role.eq('train').sum()),
            'all_prediction_keys_match_frozen_partition':True,
            'all_training_rows_available_in_included_data':True,
            'fixture_files_counted_as_training_or_test_predictions':False,
            'scientific_payload_matches_project':project is not None,
            'new_model_training_or_selection':False,'final_submission_certified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--project',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=inspect(args.archive,args.project)
    if args.output.exists():raise FileExistsError('Preserve prior evidence; use a fresh output path')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ['status','zip_entries','prediction_rows','test_prediction_rows','train_partition_rows']},ensure_ascii=False))
