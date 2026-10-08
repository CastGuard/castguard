import numpy as np
import pandas as pd
from castguard import crossed_search as c
from castguard.model_search import inner_split


class Source:
    def predict_proba(self,x):
        p=np.asarray(x)[:,0]
        return np.column_stack([1-p,p])


def test_transfer_early_stop_ecdf_fits_inner_rows_only(monkeypatch):
    monkeypatch.setattr(c,'source',lambda: {'model':Source(),'mapping':{'x':'x'}})
    monkeypatch.setattr(c,'config',lambda: {'mapping':{'x':'x'}})
    f=pd.DataFrame({'run_id':[0]*100,'event_order':range(100),'x':np.arange(100,dtype=float),'y_defect':np.arange(100)%2})
    a,b,tx=c.transfer_inner(f)
    expected,_=inner_split(f)
    np.testing.assert_array_equal(tx.sorted_[:,0],np.sort(expected.x))
    changed=f.copy();changed.loc[b.index,'x']=10000
    aa,bb,tt=c.transfer_inner(changed)
    np.testing.assert_array_equal(tx.sorted_,tt.sorted_)
    np.testing.assert_array_equal(a.transfer_score,aa.transfer_score)
    assert (bb.transfer_score==1).all()


def test_full_factorial_has_identical_settings_per_input():
    cfg=c.config();settings={}
    for row in cfg['candidates']:
        settings.setdefault(row['setting_id'],[]).append(row)
    assert len(settings)==106
    for rows in settings.values():
        assert {r['representation'] for r in rows}==set(cfg['representations'])
        assert all(r['params']==rows[0]['params'] for r in rows)
    assert len(cfg['candidates'])==848


def test_ensembles_never_mix_dataset_conditions():
    from analyze_crossed_search import variants
    families=['logistic','random_forest','xgboost','lightgbm','catboost','mlp','tabm']
    v=variants('S_T',{f:f+'_setting__S_T' for f in families})
    assert len(v)==72
    for weights in v.values():
        assert all(i.endswith('__S_T') for i in weights)
        assert abs(sum(weights.values())-1)<1e-12


def test_crossed_test_predictions_require_seal(tmp_path,monkeypatch):
    import pytest
    import analyze_crossed_search as a
    monkeypatch.setattr(a,'OUT',tmp_path)
    with pytest.raises(ValueError,match='seal'):a.components('test')
