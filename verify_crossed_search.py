"""Audit input lineage, frozen selection, model replay and crossed-study metrics."""
import json
from datetime import datetime,timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score,roc_auc_score,brier_score_loss
from castguard import crossed_search as c
from castguard.data import digest,check_features
from castguard.crossed_reader import CrossedReader


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def measure(f,t):
    y=np.asarray(f.y_defect,int);p=np.asarray(f.probability,float);flag=p>=t
    order=np.lexsort((f.row_id.to_numpy().astype(str),-p));k=len(y)//5
    return dict(n=len(y),positive=int(y.sum()),ap=average_precision_score(y,p),auc=roc_auc_score(y,p),
        brier=brier_score_loss(y,p),tp=int(np.sum(flag&(y==1))),fp=int(np.sum(flag&(y==0))),
        fn=int(np.sum(~flag&(y==1))),tn=int(np.sum(~flag&(y==0))),caught20=int(y[order[:k]].sum()))


def verify():
    out=c.OUT;reg=read(out/'registration.json');seal=read(out/'selection_seal.json');short=read(out/'shortlist.json')
    for path,h in reg['hashes'].items():assert digest(path)==h,path
    for name,h in reg['submission_hashes'].items():assert digest(Path('submission')/name)==h,name
    for path,h in seal['model_hashes'].items():assert digest(path)==h,path
    assert digest(out/'source/model.joblib')==seal['source_sha256']
    assert digest('analyze_crossed_search.py')==seal['analysis_sha256']
    assert digest('castguard/crossed_reader.py')==seal['inference_sha256']
    assert digest('analyze_model_search.py')==seal['ranking_helper_sha256']
    assert digest(out/'ensemble_validation_ranking.csv')==seal['validation_ranking_sha256']
    assert (out/'combo_test.csv').stat().st_mtime>=datetime.fromisoformat(seal['at']).timestamp()
    prepared=read(out/'prepared.json')
    lineage=read(out/'feature_lineage.json')
    assert prepared['cache_inputs_equal'] and lineage['raw42_values_equal_for_all_rows']
    assert digest('data/raw/DieCasting_Quality_Raw_Data.csv')==lineage['raw42_sha256']
    for item in read('data/processed/manifest.json')['inputs']:assert digest(item['path'])==item['sha256']
    dev=c.development();test=joblib.load(out/'test.joblib');contract=read('data/processed/feature_contract.json')
    assert len(dev['sets']['S'])==21 and not set(dev['sets']['S']) & {'transfer_score','fb_rate20','fb_rate100','fb_ewm','fb_known_count','prev_cycle_time'}
    cache_count=0;receipts=list((out/'candidates').glob('*/*/complete.json'))
    for path in receipts:
        receipt=read(path)
        if 'cache_from' in receipt:
            cache_count+=1
            for p,h in receipt['cache_hashes'].items():assert digest(p)==h,p
            old=joblib.load(Path(receipt['cache_from'])/'within_run__primary/model.joblib')
            candidate=next(x for x in c.config()['candidates'] if x['id']==receipt['id'])
            assert old['candidate']['params']==candidate['params']
            assert old['features']==dev['sets'][candidate['representation']]
    components={};replay_error=0.;metric_error=0.;n_models=0
    component_table=pd.read_csv(out/'component_test_metrics.csv',dtype={'fold':str},float_precision='round_trip')
    for identity in short['refit_ids']:
        components[identity]={}
        for key in dev['frames']:
            ps=[]
            for seed in [17,29,43]:
                folder=c.directory(identity,seed)/('__'.join(key));payload=joblib.load(folder/'model.joblib')
                check_features(payload['features'],contract)
                train=dev['frames'][key]['train']
                if 'transfer_score' in payload['features']:
                    np.testing.assert_array_equal(payload['target_ecdf'].sorted_,dev['transforms'][key].sorted_)
                if 'preprocessor' in payload:
                    expected=np.nanmedian(train[payload['preprocessor'].numeric].to_numpy(),axis=0)
                    np.testing.assert_allclose(payload['preprocessor'].imputer.statistics_,np.nan_to_num(expected,nan=0),rtol=0,atol=0)
                saved=pd.read_parquet(folder/'test.parquet')
                np.testing.assert_array_equal(saved.row_id,test[key].row_id)
                computed=c.predict(payload,test[key]);error=float(np.max(np.abs(computed-saved.probability)))
                assert error<1e-6;replay_error=max(replay_error,error);n_models+=1;ps.append(saved)
            f=ps[0].copy();f['probability']=np.mean([p.probability.to_numpy() for p in ps],axis=0)
            components[identity][key]=f
            row=component_table[(component_table.id==identity)&(component_table.scheme==key[0])&(component_table.fold==key[1])].iloc[0]
            for k,v in measure(f,row.threshold).items():
                err=abs(v-row[k]);metric_error=max(metric_error,float(err));assert err<1e-12,(identity,k)
    combo=pd.read_csv(out/'combo_test.csv',dtype={'fold':str},float_precision='round_trip')
    combo_pred=pd.read_parquet(out/'combo_test_predictions.parquet')
    for row in combo.itertuples():
        f=combo_pred[(combo_pred.representation==row.representation)&(combo_pred.scheme==row.scheme)&(combo_pred.fold==row.fold)]
        for k,v in measure(f,row.threshold).items():
            err=abs(v-getattr(row,k));metric_error=max(metric_error,float(err));assert err<1e-12
        expected=sum(w*components[i][(row.scheme,row.fold)].probability.to_numpy() for i,w in seal['definitions'][row.id].items())
        np.testing.assert_allclose(f.probability,expected,rtol=0,atol=1e-12)
    # Both matrices must be exact projections of the audited component scores.
    for filename in ['model_matrix_test.csv','locked_settings_test.csv']:
        table=pd.read_csv(out/filename,dtype={'fold':str},float_precision='round_trip')
        merged=table.merge(component_table,on=['id','scheme','fold'],suffixes=('_matrix','_component'),validate='many_to_one')
        assert len(merged)==len(table)==280
        for column in ['ap','auc','caught20','fp','tp']:
            np.testing.assert_array_equal(merged[column+'_matrix'],merged[column+'_component'])
    max_batch=0.
    pure=CrossedReader(Path.cwd(),'S')
    assert pure.source is None and len(pure.features)==21
    only42=test[('within_run','primary')][pure.features]
    np.testing.assert_allclose(pure.score(only42),pure.score(test[('within_run','primary')]),rtol=0,atol=1e-7)
    for selection in ['primary','feedback']:
        reader=CrossedReader(Path.cwd(),selection);f=test[('within_run','primary')]
        p=reader.score(f)
        saved=combo_pred[(combo_pred.id==reader.identity)&(combo_pred.scheme=='within_run')]
        np.testing.assert_allclose(p,saved.probability,rtol=0,atol=1e-6)
        for i in [0,11,100]:max_batch=max(max_batch,float(abs(reader.score(f.iloc[[i]])[0]-p[i])))
        changed=f.copy();changed['y_defect']=1-changed.y_defect
        np.testing.assert_allclose(reader.score(changed),p,rtol=0,atol=1e-7)
    assert max_batch<1e-6
    result=dict(at=datetime.now(timezone.utc).isoformat(),passed=True,candidate_configurations=848,
        initial_completed=len(list((out/'candidates').glob('*/17/complete.json'))),
        complete_candidate_seed_receipts=len(receipts),reused_candidate_seed_receipts=cache_count,
        cached_outer_fits=cache_count*5,new_outer_fits=(len(receipts)-cache_count)*5,
        checkpoint_replays=n_models,replay_max_error=replay_error,metric_max_error=metric_error,
        component_metric_groups=len(component_table),combo_metric_groups=len(combo),
        model_matrix_groups=280,locked_matrix_groups=280,max_batch_single_difference=max_batch,
        pure42_lineage_verified=True,train_only_imputation_verified=True,registered_hashes_preserved=True,
        pure42_prediction_works_without_41_40_or_feedback_inputs=True,
        submission_unchanged=True,current_target_change_does_not_affect_score=True,
        caveat='Numerical verification only; past test exposure and exploratory selection remain')
    (out/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':verify()
