import numpy as np
import pandas as pd
import pytest
from judge_baselines import baseline_scores

def fixture():
    return pd.DataFrame({'source_row':[0,1,2,3],'Product_Type':[1,1,2,2],'y_defect':[0,1,1,1],'x':[10.,12.,14.,16.]})

def test_recent_prior_freezes_fit_window_and_unknown_product_fallback():
    fit=fixture();observed=pd.DataFrame({'Product_Type':[1,2,3],'x':[9.,20.,30.]})
    np.testing.assert_allclose(baseline_scores(fit,observed,'RECENT_PRODUCT_RATE',['x'],0,2),[1,1,1])
    np.testing.assert_allclose(baseline_scores(fit,observed,'RECENT_PRODUCT_RATE',['x'],0,4),[.5,1,.75])

def test_scoring_rejects_observed_outcomes():
    for label in ['y_defect','Machine_Status']:
        with pytest.raises(ValueError,match='Outcome leaked'):
            baseline_scores(fixture(),pd.DataFrame({label:[1]}),'FIFO',['x'],0,100)

def test_random_scoring_is_reproducible_and_process_rule_uses_fit_only():
    fit=fixture();a=pd.DataFrame({'Product_Type':[1,2],'x':[13.,19.]})
    np.testing.assert_array_equal(baseline_scores(fit,a,'RANDOM',['x'],1000,100),baseline_scores(fit,a,'RANDOM',['x'],1000,100))
    result=baseline_scores(fit,a,'PROCESS_DEVIATION',['x'],0,100)
    np.testing.assert_allclose(result,[0,2])
