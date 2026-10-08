import numpy as np
import pytest
from castguard.oct08_fusion import TrainECDF


def test_ecdf_ties_missing_and_outside_training_range():
    t = TrainECDF().fit([[1, 10], [2, 20], [2, 30], [np.nan, 40]])
    before = t.sorted_.copy()
    np.testing.assert_allclose(t.transform([[2, 20], [np.nan, np.nan], [-10, 0], [10, 100]]),
                               [[.625, .375], [.625, .5], [0, 0], [1, 1]])
    np.testing.assert_array_equal(t.sorted_, before)


def test_ecdf_batch_and_individual_are_identical():
    t = TrainECDF().fit([[0], [1], [2]])
    x = np.array([[100], [-100], [1], [np.nan]])
    np.testing.assert_array_equal(t.transform(x), np.vstack([t.transform([row]) for row in x]))
    np.testing.assert_array_equal(t.transform(x[[2, 0, 3, 1]]), t.transform(x)[[2, 0, 3, 1]])


@pytest.mark.parametrize('x', [[[np.nan]], [[np.inf]], []])
def test_ecdf_rejects_unusable_training_values(x):
    with pytest.raises(ValueError):
        TrainECDF().fit(x)
