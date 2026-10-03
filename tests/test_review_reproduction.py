"""Guard against false reproduction success or silently drifting dependency versions."""
import importlib.metadata
import pandas as pd
import pytest
import review_environment
from review_retrain import compare_metrics, compare_predictions


def test_environment_reports_missing_and_mismatched_pins(tmp_path, monkeypatch):
    (tmp_path/'requirements-lock.txt').write_text('numpy==2.3.5\npandas==3.0.1\n', encoding='utf-8')
    def version(name):
        if name == 'pandas':
            raise importlib.metadata.PackageNotFoundError(name)
        return '2.0.0'
    monkeypatch.setattr(importlib.metadata, 'version', version)
    result = review_environment.inspect(tmp_path)
    assert result['status'] == 'blocked'
    assert result['missing'] == ['pandas'] and result['mismatches'] == ['numpy']
    with pytest.raises(ValueError, match='Environment mismatch'):
        review_environment.require(tmp_path)


def test_conflicting_and_unpinned_requirement_rejected(tmp_path):
    p = tmp_path/'requirements-lock.txt'
    p.write_text('numpy==2.3.5\nnumpy==2.0.0\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Conflicting pin'):
        review_environment.pins(p, tmp_path)
    p.write_text('numpy>=2\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Unpinned'):
        review_environment.pins(p, tmp_path)


def test_prediction_comparison_rejects_relabel_and_probability_drift():
    expected = pd.DataFrame(dict(row_id=['a','b'], role=['validation','test'], y=[1,0],
                                 prediction=[True,False], probability=[.8,.1], threshold=[.5,.5]))
    assert compare_predictions(expected.copy(),expected)['rows'] == 2
    for column, value in [('row_id','other'), ('y',0), ('probability',.7)]:
        actual = expected.copy(); actual.loc[0,column] = value
        with pytest.raises(ValueError):
            compare_predictions(actual,expected)
    with pytest.raises(ValueError, match='duplicate'):
        compare_predictions(pd.concat([expected,expected]), expected)


def test_metric_comparison_requires_both_roles_and_rejects_drift():
    expected = pd.DataFrame(dict(role=['validation','test'], n=[647,1387], average_precision=[.3,.2]))
    assert compare_metrics(expected, expected)['numeric_values_compared'] == 4
    actual=expected.copy();actual.loc[0,'average_precision']=.4
    with pytest.raises(ValueError, match='metric mismatch'):
        compare_metrics(actual,expected)
    with pytest.raises(ValueError, match='cardinality'):
        compare_metrics(expected.iloc[:1],expected)
