"""Source-bound comparisons, predeclared condition pair and research deployment profile."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import joblib
from threadpoolctl import threadpool_limits
from castguard.oct06_research import prepare_frames, write_json, metrics
from castguard.data import digest

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reports/oct06_research'
PAIR=['High_Velocity','Casting_Pressure']
CONTRASTS=[('H','P'),('SH','S'),('S_FB','S'),('SH_FB','S_FB')]


def main():
    cfg=json.loads((ROOT/'configs/oct06_research.json').read_text(encoding='utf-8'))
    state=json.loads((OUT/'run_state.json').read_text(encoding='utf-8'))
    if state['status']!='completed':raise RuntimeError('research not complete')
    selected=json.loads((OUT/'selection.json').read_text(encoding='utf-8'))
    val=pd.read_csv(OUT/'validation_candidates.csv',dtype={'fold':str})
    met=pd.read_csv(OUT/'selected_metrics.csv',dtype={'fold':str})
    pred=pd.read_parquet(OUT/'selected_predictions.parquet')
    frames,sets=prepare_frames(ROOT,cfg)
    summary=met.groupby(['scheme','fold','representation','model','role']).agg(
        n=('n','first'),positive=('positive','first'),prevalence=('prevalence','first'),
        ap=('ap','mean'),ap_seed_sd=('ap','std'),auc=('auc','mean'),brier=('brier','mean'),
        capture20=('capture20','mean'),caught20=('caught20','mean'),inspect20=('inspect20','first'),
        fpr=('fpr','mean'),fp=('fp','mean'),fn=('fn','mean')).reset_index()
    summary.to_csv(OUT/'summary.csv',index=False)
    comparisons=[];paired=[]
    for a,b in CONTRASTS:
        for (scheme,fold,role),g in met.groupby(['scheme','fold','role']):
            x=g[g.representation==a].set_index('seed');y=g[g.representation==b].set_index('seed')
            comparisons.append({'scheme':scheme,'fold':fold,'role':role,'added':a,'base':b,
                'ap_gain':float((x.ap-y.ap).mean()),'ap_gain_seed_sd':float((x.ap-y.ap).std()),
                'capture20_gain':float((x.capture20-y.capture20).mean()),
                'selected_models':f'{x.model.iloc[0]} vs {y.model.iloc[0]}'})
        for (scheme,fold,model),g in val.groupby(['scheme','fold','model']):
            x=g[g.representation==a].set_index('seed');y=g[g.representation==b].set_index('seed')
            paired.append({'scheme':scheme,'fold':fold,'model':model,'added':a,'base':b,
                'ap_gain':float((x.ap-y.ap).mean()),'capture20_gain':float((x.capture20-y.capture20).mean())})
    comp=pd.DataFrame(comparisons);comp.to_csv(OUT/'comparisons.csv',index=False)
    pd.DataFrame(paired).to_csv(OUT/'same_model_validation_ablation.csv',index=False)
    decisions=[]
    for a,b in CONTRASTS:
        g=comp[(comp.added==a)&(comp.base==b)&(comp.role=='validation')]
        within=g[g.scheme=='within_run'].iloc[0];forward=g[g.scheme=='forward_run']
        qualifies=(within.ap_gain>=.02 and within.capture20_gain>=.05 and len(forward)>=2
                   and (forward.ap_gain>=0).all() and (forward.capture20_gain>=0).all())
        decisions.append({'added':a,'base':b,'pass_registered_validation_gate':bool(qualifies),
                          'within_ap_gain':float(within.ap_gain),'within_capture_gain':float(within.capture20_gain),
                          'forward_nonnegative_ap_folds':int((forward.ap_gain>=0).sum()),
                          'forward_nonnegative_capture_folds':int((forward.capture20_gain>=0).sum()),'forward_folds':len(forward)})
    write_json(OUT/'adoption_decisions.json', decisions)
    # FB is a benchmark without current process covariates, not a full process reader.
    candidates=[x for x in selected['selections'] if x['scheme']=='within_run' and x['representation']!='FB']
    chosen=sorted(candidates,key=lambda x:(-x['validation_ap'],x['representation']))[0]
    write_json(OUT/'research_reader_selection.json',{'choice':chosen,'seed':17,
        'reason':'highest sealed within_run validation AP among current-process readers; seed17 fixed in original seed list',
        'deployment':'research_only','future_or_field_adoption':False})
    rep=chosen['representation'];name=chosen['model']
    errors=[];cells=[];interactions=[]
    for (scheme,fold),frame in frames.items():
        train=frame[frame.role=='train'];test=frame[frame.role=='test']
        edges={c:np.unique(train[c].dropna().quantile(cfg['condition_quantiles']).to_numpy()).tolist() for c in PAIR}
        for representation in ['S','SH','S_FB','SH_FB']:
            sl=next(s for s in selected['selections'] if (s['scheme'],s['fold'],s['representation'])==(scheme,fold,representation))
            ps=pred[(pred.scheme==scheme)&(pred.fold==fold)&(pred.representation==representation)&(pred.role=='test')]
            for seed in cfg['seeds']:
                payload=joblib.load(OUT/'models'/f'{scheme}__{fold}__{representation}__{sl["model"]}__{seed}'/'model.joblib')
                model,feat,threshold=[payload[k] for k in ['model','features','threshold']]
                for product in sorted(frame.Product_Type.unique()):
                    tr=train[train.Product_Type==product];te=test[test.Product_Type==product]
                    for i in range(len(edges[PAIR[0]])-1):
                        for j in range(len(edges[PAIR[1]])-1):
                            def subset(df):
                                mask=np.ones(len(df),bool)
                                for c,ind in zip(PAIR,[i,j]):
                                    e=edges[c];v=df[c]
                                    mask &= ((v>=e[ind]) if ind==0 else (v>e[ind])) & (v<=e[ind+1])
                                return df.loc[mask]
                            tc,ec=subset(tr),subset(te)
                            supported=len(tc)>=30 and len(ec)>=20
                            cell={'scheme':scheme,'fold':fold,'representation':representation,'seed':seed,
                                  'product':int(product),'x_bin':i,'y_bin':j,'train_n':len(tc),'test_n':len(ec),
                                  'test_positive':int(ec.y_defect.sum()),'supported':supported}
                            if len(ec):
                                pp=ps[ps.seed==seed].set_index('row_id').loc[ec.row_id]
                                cell.update({k:v for k,v in metrics(ec.y_defect,pp.probability,threshold,ec.row_id).items() if k in ['ap','auc','fp','fn','fpr']})
                            cells.append(cell)
                            if not supported:continue
                            base=tc.sort_values('row_id').iloc[:32][feat].copy()
                            bounds={c:tc[c].quantile([.25,.75]).tolist() for c in PAIR}
                            scores=[];logits=[]
                            with threadpool_limits(limits=1):
                                for u,v in [(0,0),(1,0),(0,1),(1,1)]:
                                    z=base.copy();z[PAIR[0]]=bounds[PAIR[0]][u];z[PAIR[1]]=bounds[PAIR[1]][v]
                                    pp=model.predict_proba(z)[:,1];scores.append(pp)
                                    logits.append(np.log(np.clip(pp,1e-9,1-1e-9)/(1-np.clip(pp,1e-9,1-1e-9))))
                            delta=scores[3]-scores[1]-scores[2]+scores[0]
                            dl=logits[3]-logits[1]-logits[2]+logits[0]
                            interactions.append({**cell,'model':sl['model'],'anchors':len(base),
                                'interaction_score_mean':float(delta.mean()),'interaction_score_abs_mean':float(abs(delta).mean()),
                                'interaction_logodds_mean':float(dl.mean()),'x_low':bounds[PAIR[0]][0],'x_high':bounds[PAIR[0]][1],
                                'y_low':bounds[PAIR[1]][0],'y_high':bounds[PAIR[1]][1]})
        for representation in cfg['representations']:
            ps=pred[(pred.scheme==scheme)&(pred.fold==fold)&(pred.representation==representation)&(pred.role=='test')]
            for seed, sp in ps.groupby('seed'):
                for dimension in ['run_id','Product_Type']:
                    for value,g in sp.groupby(dimension):
                        errors.append({'scheme':scheme,'fold':fold,'representation':representation,'seed':int(seed),
                            'dimension':dimension,'value':int(value),'product_seen_in_train':bool(g.Product_Type.isin(train.Product_Type).all()),
                            **metrics(g.y_defect,g.probability,float(g.threshold.iloc[0]),g.row_id)})
    pd.DataFrame(errors).to_csv(OUT/'condition_errors.csv',index=False)
    pd.DataFrame(cells).to_csv(OUT/'joint_support.csv',index=False)
    pd.DataFrame(interactions).to_csv(OUT/'pair_interactions.csv',index=False)
    # Post-hoc error examples: deterministic first row per TP/FP/FN/TN, no performance claim.
    p=pred[(pred.scheme=='within_run')&(pred.representation==rep)&(pred.role=='test')&(pred.seed==17)].copy()
    p['error_type']=np.where(p.y_defect==1,np.where(p.probability>=p.threshold,'TP','FN'),np.where(p.probability>=p.threshold,'FP','TN'))
    p.sort_values('row_id').groupby('error_type').head(1).to_csv(OUT/'diagnostic_examples.csv',index=False)
    # Development-only training reference for the reader's abstention logic.
    f=frames[('within_run','primary')];tr=f[f.role=='train'];features=sets[rep]
    model_path=OUT/'models'/f'within_run__primary__{rep}__{name}__17'/'model.joblib'
    profile={'selection':chosen,'model_path':model_path.relative_to(ROOT).as_posix(),'model_sha256':digest(model_path),
        'features':features,'seed':17,'products':sorted(tr.Product_Type.unique().tolist()),
        'ranges':{c:[float(tr[c].min()),float(tr[c].max())] for c in features},
        'medians':{c:float(tr[c].median()) for c in features},
        'pair':PAIR,'edges':{c:np.unique(tr[c].quantile(cfg['condition_quantiles'])).tolist() for c in PAIR},
        'cells':[], 'scope':'research_only; observed historical quality population; field latency unverified'}
    for product,g in tr.groupby('Product_Type'):
        xx=pd.cut(g[PAIR[0]],profile['edges'][PAIR[0]],labels=False,include_lowest=True)
        yy=pd.cut(g[PAIR[1]],profile['edges'][PAIR[1]],labels=False,include_lowest=True)
        for (i,j),n in pd.DataFrame({'x':xx,'y':yy}).value_counts().items():
            profile['cells'].append({'product':int(product),'x':int(i),'y':int(j),'n':int(n)})
    write_json(OUT/'reader_profile.json',profile)
    # Run-block paired intervals for the within-run selected reader vs S. Seed17 reader is explicit.
    b=pred[(pred.scheme=='within_run')&(pred.representation=='S')&(pred.role=='test')&(pred.seed==17)]
    joined=p.merge(b[['row_id','probability']],on='row_id',suffixes=('_new','_base'),validate='one_to_one')
    rng=np.random.default_rng(cfg['bootstrap_seed']);runs=sorted(joined.run_id.unique());deltas=[]
    for _ in range(cfg['bootstrap_repetitions']):
        z=pd.concat([joined[joined.run_id==r] for r in rng.choice(runs,len(runs),replace=True)],ignore_index=True)
        if z.y_defect.nunique()==2:
            deltas.append(average_precision(z.y_defect,z.probability_new)-average_precision(z.y_defect,z.probability_base))
    write_json(OUT/'reader_uncertainty.json',{'comparison':f'{rep} vs S','seed':17,'method':'whole_run_cluster_bootstrap',
        'runs':len(runs),'replicates':len(deltas),'ap_difference':float(average_precision(joined.y_defect,joined.probability_new)-average_precision(joined.y_defect,joined.probability_base)),
        'lower':float(np.quantile(deltas,.025)),'upper':float(np.quantile(deltas,.975)),
        'interpretation':'exploratory on reused test; model selection and field shifts not included'})
    # Cost uses actual threshold decisions, no post-hoc capacity guarantee.
    costs=[]
    for ratio in [1,2,5,10,20]:
        for label,col in [('reader','probability_new'),('S','probability_base')]:
            threshold=float(p.threshold.iloc[0]) if label=='reader' else float(b.threshold.iloc[0])
            yy=joined.y_defect.to_numpy();decision=joined[col].to_numpy()>=threshold
            costs.append({'policy':label,'miss_cost_per_inspection_cost':ratio,'n':len(joined),
                'inspections':int(decision.sum()),'misses':int(((yy==1)&~decision).sum()),
                'normalized_loss':float(decision.sum()+ratio*((yy==1)&~decision).sum()),
                'assumption':'perfect additional inspection; misses cost ratio; diagnostic scenario, no actual currency'})
    pd.DataFrame(costs).to_csv(OUT/'cost_scenarios.csv',index=False)
    print(summary[summary.scheme=='within_run'][['representation','model','role','ap','auc','capture20']].to_string(index=False))
    print(json.dumps(decisions,ensure_ascii=False));print('Reader:',chosen)


def average_precision(y,p):
    from sklearn.metrics import average_precision_score
    return average_precision_score(y,p)


if __name__=='__main__': main()
