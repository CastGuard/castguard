"""Independent arithmetic checks must catch result corruption as well as agree."""
from copy import deepcopy
from pathlib import Path
import pandas as pd
import pytest
from review_metrics import raw_truth,recompute,compare_saved

ROOT=Path(__file__).resolve().parents[1]


def test_independent_raw_truth_and_saved_actions_agree():
    result=recompute(ROOT)
    assert compare_saved(result,ROOT)
    assert result['raw_quality']['duplicate_rows']==2918
    assert result['FIFO_history_same_inspections_and_service_steps']
    assert result['policies']['FIFO']['quality_mean_wait_records']>result['policies']['Q']['quality_mean_wait_records']


def test_corrupted_denominator_is_detected():
    result=recompute(ROOT);result['observed_positives']+=1
    with pytest.raises(AssertionError):compare_saved(result,ROOT)


def test_corrupted_saved_action_label_is_detected_independently():
    actions=pd.read_parquet(ROOT/'reports/oct03_queue/outer_actions.parquet')
    index=actions.index[actions.policy.eq('Q')&actions.budget.eq(.2)&actions.y_defect.notna()][0]
    actions.loc[index,'y_defect']=1-actions.loc[index,'y_defect']
    with pytest.raises(AssertionError):recompute(ROOT,actions_override=actions)
