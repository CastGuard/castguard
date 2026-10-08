import numpy as np
import pandas as pd
from castguard.model_search import Preprocessor, inner_split


def test_inner_tail_purges_twenty_process_events():
    f=pd.DataFrame({'run_id':np.repeat([0,1],100),'event_order':list(range(100))*2,
                    'y_defect':list(np.arange(100)%2)*2})
    fit,stop=inner_split(f)
    assert set(fit.index).isdisjoint(stop.index)
    for run in [0,1]:
        assert fit[fit.run_id==run].event_order.max() < stop[stop.run_id==run].event_order.min()-20
        assert stop[stop.run_id==run].event_order.min()==80


def test_transform_uses_train_statistics_and_handles_unknown_product():
    tr=pd.DataFrame({'a':[1.,2.,np.nan,4.], 'Product_Type':[1,1,2,2]})
    p=Preprocessor(['a','Product_Type'],'xgboost',17).fit(tr)
    v=pd.DataFrame({'a':[np.nan,1000.], 'Product_Type':[3,1]})
    out=p.transform(v)
    assert out[0,0]==2
    assert (out[0,1:]==0).all()
    np.testing.assert_array_equal(out[0],p.transform(v.iloc[:1])[0])
    assert p.imputer.statistics_[0]==2


def test_neural_transform_is_batch_invariant():
    tr=pd.DataFrame({'a':np.arange(100,dtype=float),'Product_Type':[1]*50+[2]*50})
    p=Preprocessor(['a','Product_Type'],'mlp',17).fit(tr)
    np.testing.assert_array_equal(p.transform(tr.iloc[[17]])[0],p.transform(tr)[17])


def test_catboost_preserves_categorical_type():
    tr=pd.DataFrame({'a':[1.,np.nan,3.],'Product_Type':[1,2,1]})
    out=Preprocessor(['a','Product_Type'],'catboost',17).fit(tr).transform(tr)
    assert out.Product_Type.tolist()==['1','2','1']
    assert out.a.tolist()==[1,2,3]


def test_selection_requires_capture_and_forward_consistency():
    from analyze_model_search import ranking
    base=pd.DataFrame({'scheme':['within_run']+['forward_run']*4,'fold':['primary','2','3','4','6'],
                       'ap':[.4]*5,'capture20':[.4]*5})
    candidate=base.copy();candidate['ap']=[.43,.41,.42,.3,.3]
    candidate['capture20']=[.46,.41,.4,.4,.4]
    assert ranking(candidate,base)['qualifies']
    candidate.loc[0,'capture20']=.44
    assert not ranking(candidate,base)['qualifies']


def test_blending_preserves_alignment_and_weights():
    import pytest
    from analyze_model_search import blended
    a=pd.DataFrame({'row_id':['a','b'],'y_defect':[0,1],'probability':[.2,.8]})
    b=a.copy();b['probability']=[.4,.6]
    cs={'a':{'k':a},'b':{'k':b}}
    np.testing.assert_allclose(blended(cs,{'a':.25,'b':.75},'k').probability,[.35,.65])
    cs['b']['k']=b.iloc[::-1].reset_index(drop=True)
    with pytest.raises(AssertionError):blended(cs,{'a':.5,'b':.5},'k')


def test_test_predictions_refused_before_validation_seal(tmp_path,monkeypatch):
    import pytest
    import analyze_model_search as a
    monkeypatch.setattr(a,'OUT',tmp_path)
    with pytest.raises(ValueError,match='sealed'):a.component_predictions('test')
