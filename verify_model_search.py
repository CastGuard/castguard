"""Independent receipts, train-only transforms, ensemble reconstruction and metrics audit."""
from datetime import datetime,timezone
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
from castguard.data import digest,check_features
from castguard.model_search import OUT,inner_split,predict
from castguard.search_reader import SearchReader


def run():
    seal=json.loads((OUT/'selection_seal.json').read_text(encoding='utf-8'))
    for name in ['registration.json','refinement_registration.json']:
        receipt=json.loads((OUT/name).read_text(encoding='utf-8'))
        for p,h in receipt['hashes'].items():assert digest(p)==h,p
    reg=json.loads((OUT/'registration.json').read_text(encoding='utf-8'))
    for name,h in reg['submission_hashes'].items():assert digest(Path('submission')/name)==h,name
    for p,h in seal['model_hashes'].items():assert digest(p)==h,p
    assert digest(OUT/'ensemble_validation_ranking.csv')==seal['ranking_sha256']
    assert digest('analyze_model_search.py')==seal['analysis_sha256']
    assert (OUT/'test_metrics.csv').stat().st_mtime>=datetime.fromisoformat(seal['at']).timestamp()
    data=joblib.load(OUT/'development.joblib');test=joblib.load(OUT/'test.joblib')
    contract=json.loads(Path('data/processed/feature_contract.json').read_text())
    stored=pd.read_parquet(OUT/'test_predictions.parquet')
    table=pd.read_csv(OUT/'test_metrics.csv',dtype={'fold':str},float_precision='round_trip')
    metric_error=0.
    for row in table.itertuples():
        p=stored[(stored.id==row.id)&(stored.scheme==row.scheme)&(stored.fold==row.fold)]
        assert len(p)==row.n and int(p.y_defect.sum())==row.positive
        y=p.y_defect.to_numpy();scores=p.probability.to_numpy();flag=scores>=row.threshold
        for key,value in dict(ap=average_precision_score(y,scores),auc=roc_auc_score(y,scores),brier=brier_score_loss(y,scores)).items():
            metric_error=max(metric_error,abs(value-getattr(row,key)))
            assert abs(value-getattr(row,key))<1e-12
        tp=int(np.sum(flag&(y==1)));fp=int(np.sum(flag&(y==0)))
        assert tp==row.tp and fp==row.fp and int(np.sum(~flag&(y==1)))==row.fn and int(np.sum(~flag&(y==0)))==row.tn
        order=np.lexsort((p.row_id.to_numpy().astype(str),-scores))
        assert int(y[order[:len(y)//5]].sum())==row.caught20
    maximum_replay_error=0.;n_models=0
    for identity in ['baseline',*json.loads((OUT/'shortlist.json').read_text())['ids']]:
        for seed in ([17] if identity=='baseline' else [17,29,43]):
            for key,parts in data['frames'].items():
                folder=OUT/'candidates'/identity/str(seed)/('__'.join(key))
                payload=joblib.load(folder/'model.joblib');check_features(payload['features'],contract)
                if identity!='baseline':
                    pre=payload['preprocessor']
                    expected=np.nanmedian(parts['train'][pre.numeric].to_numpy(),axis=0)
                    expected=np.nan_to_num(expected,nan=0)
                    np.testing.assert_allclose(pre.imputer.statistics_,expected,rtol=0,atol=0)
                p=predict(payload,test[key]);saved=pd.read_parquet(folder/'test.parquet')
                np.testing.assert_array_equal(saved.row_id.to_numpy(),test[key].row_id.to_numpy())
                error=float(np.max(np.abs(p-saved.probability.to_numpy())));maximum_replay_error=max(maximum_replay_error,error)
                assert error<1e-6;n_models+=1
    frame=data['frames'][('within_run','primary')]['validation']
    old=joblib.load('reports/oct06_research/models/within_run__primary__S_FB__logistic__17/model.joblib')
    current=joblib.load(OUT/'candidates/baseline/17/within_run__primary/model.joblib')
    delta=float(np.max(np.abs(old['model'].predict_proba(frame[old['features']])[:,1]-predict(current,frame))))
    assert delta==0
    reader=SearchReader(Path.cwd())
    key=('within_run','primary');p=reader.score(test[key])
    saved=stored[(stored.id==seal['winner'])&(stored.scheme=='within_run')].probability.to_numpy()
    np.testing.assert_allclose(p,saved,rtol=0,atol=1e-6)
    single=np.array([reader.score(test[key].iloc[[i]])[0] for i in [0,11,100]])
    batch_error=float(np.max(np.abs(single-p[[0,11,100]])))
    assert batch_error<1e-6
    flipped=test[key].copy();flipped['y_defect']=1-flipped.y_defect
    np.testing.assert_allclose(reader.score(flipped),p,rtol=0,atol=1e-7)
    receipt=dict(at=datetime.now(timezone.utc).isoformat(),passed=True,test_metric_groups=len(table),metric_max_error=metric_error,
        checkpoints_replayed=n_models,checkpoint_max_error=maximum_replay_error,baseline_validation_max_difference=delta,
        selected_reader_batch_single_max_error=batch_error,changed_current_target_does_not_change_prediction=True,
        train_only_imputation_verified=True,registered_hashes_preserved=True,submission_unchanged=True,
        caveat='Computational audit, not independent performance evidence')
    (OUT/'verification.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':run()
