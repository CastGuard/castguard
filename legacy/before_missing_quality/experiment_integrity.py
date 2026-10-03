"""Input contracts for frozen experiment accounting, independent of model fitting."""
from fractions import Fraction
from numbers import Real, Integral
from itertools import product
import numpy as np
import pandas as pd


def budget_fraction(value, allow_zero=True):
    if isinstance(value,(bool,np.bool_)) or not isinstance(value,Real) or not np.isfinite(value):
        raise ValueError('Budget must be a finite numeric fraction, not a boolean')
    fraction=Fraction(str(value))
    if not (0<=fraction<=1) or (not allow_zero and fraction==0):
        raise ValueError('Budget outside allowed fraction range')
    return fraction


def capacity(n,budget):
    if isinstance(n,(bool,np.bool_)) or not isinstance(n,Integral) or n<0:
        raise ValueError('Population size must be a nonnegative integer')
    ratio=budget_fraction(budget)
    return int(n)*ratio.numerator//ratio.denominator


def binary_labels(series,name,allow_missing=False):
    valid=series.isin([0,1])
    if allow_missing:valid=valid|series.isna()
    if not valid.all():raise ValueError('Invalid binary labels: '+name)


def boolean_values(series,name):
    if not series.map(lambda x:isinstance(x,(bool,np.bool_))).all():
        raise ValueError('Expected explicit boolean values: '+name)


def identifiers(series,name):
    if series.isna().any() or series.astype(str).str.strip().eq('').any() or series.astype(str).duplicated().any():
        raise ValueError('Missing or duplicate identities: '+name)


def gate_inputs(timeline,scores):
    if timeline.empty:raise ValueError('Gate timeline must not be empty')
    identifiers(timeline.row_id,'timeline row_id');identifiers(scores.row_id,'score row_id')
    boolean_values(timeline.gate_eligible,'gate_eligible')
    binary_labels(timeline.Machine_Status,'Machine_Status',allow_missing=True)
    if timeline.loc[timeline.gate_eligible,'Machine_Status'].isna().any():
        raise ValueError('Eligible Gate rows require known state labels')
    if set(scores.row_id)!=set(timeline.loc[timeline.gate_eligible,'row_id']):
        raise ValueError('Gate score coverage must equal every eligible row')
    if not np.isfinite(scores.probability.to_numpy(dtype=float)).all():
        raise ValueError('Corrupt eligible Gate score cannot be treated as unavailable input')
    warm=timeline.loc[timeline.Machine_Status.eq(1)]
    if warm.episode_id.isna().any() or warm.episode_id.astype(str).str.strip().eq('').any():
        raise ValueError('Warm rows require episode identities')
    if warm.groupby('episode_id').run_id.nunique().gt(1).any():
        raise ValueError('Episode identity cannot combine different runs')


def candidate_matrix(frame,expected_models=None,expected_seeds=None,expected_budgets=None):
    """Reject partial candidate/seed grids instead of averaging only surviving rows."""
    if frame.empty:raise ValueError('Candidate comparison is empty')
    models=set(frame.model if expected_models is None else expected_models)
    if set(frame.model)!=models:raise ValueError('Candidate families missing or unexpected')
    if {'scheme','fold'}.issubset(frame) and len(frame[['scheme','fold']].drop_duplicates())!=1:
        raise ValueError('Candidate selection must use one registered fold')
    axes=['model'];values=[models]
    for name,expected in [('seed',expected_seeds),('budget',expected_budgets)]:
        if expected is not None and name not in frame:raise ValueError('Missing candidate axis: '+name)
        if name in frame:
            actual=set(frame[name]);wanted=actual if expected is None else set(expected)
            if actual!=wanted or frame[name].isna().any():raise ValueError('Incomplete candidate axis: '+name)
            axes.append(name);values.append(wanted)
    if frame.duplicated(axes).any() or set(map(tuple,frame[axes].to_numpy()))!=set(product(*values)):
        raise ValueError('Candidate comparison must contain exactly the same registered seed/budget grid')
    for name in ['n','positive','overall_positive','n_timeline','normal','episodes_observable']:
        if name in frame and frame[name].nunique(dropna=False)!=1:
            raise ValueError('Candidate population/denominator differs: '+name)


def missing_quality_contrast_bounds(known_positive,known_capture_difference,unknown_action_differences):
    """Exact identification envelope, not a CI or a prediction of missing labels.

    For each possible count k of missing positives, sorting the fixed action
    differences gives the smallest/largest numerator. Both policies share the
    same total-positive denominator. No missing label is filled in or saved.
    """
    if isinstance(known_positive,(bool,np.bool_)) or not isinstance(known_positive,Integral) or known_positive<=0:
        raise ValueError('At least one known positive is required')
    differences=np.asarray(unknown_action_differences,dtype=float)
    if differences.ndim!=1 or not np.isfinite(differences).all() or np.any(np.abs(differences)>1):
        raise ValueError('Action differences must be finite in [-1,1]')
    if not np.isfinite(known_capture_difference) or abs(known_capture_difference)>known_positive:
        raise ValueError('Known capture difference outside feasible bounds')
    ordered=np.sort(differences)
    counts=np.arange(len(ordered)+1)
    low=(known_capture_difference+np.r_[0.,ordered.cumsum()])/(known_positive+counts)
    high=(known_capture_difference+np.r_[0.,ordered[::-1].cumsum()])/(known_positive+counts)
    return {'lower':float(low.min()),'upper':float(high.max()),
        'unknown_positive_count_at_lower':int(low.argmin()),'unknown_positive_count_at_upper':int(high.argmax()),
        'unknown_quality_rows':len(ordered),'observed_only_contrast':known_capture_difference/known_positive,
        'interpretation':'all logically possible binary missing labels conditional on these rows being target units; not a confidence interval'}


def queue_accounting(actions,budget):
    """An evaluator must reject noncausal/tampered actions, even outside the simulator."""
    if actions.empty:raise ValueError('Queue evaluation requires production rows')
    ordered=actions.sort_values(['source_row','row_id']).reset_index(drop=True)
    if ordered.source_row.duplicated().any():raise ValueError('Ambiguous production order')
    if not np.array_equal(ordered.arrival_step.to_numpy(),np.arange(len(ordered))):
        raise ValueError('Arrival indices do not match production order')
    served=ordered.loc[ordered.inspected]
    steps=served.service_step.to_numpy(dtype=float)
    if not np.isfinite(steps).all() or not np.equal(steps,np.floor(steps)).all():
        raise ValueError('Service indices must be finite integers')
    steps=steps.astype(int)
    if np.any(steps<served.arrival_step) or np.any(steps>=len(ordered)) or len(set(steps))!=len(steps):
        raise ValueError('Service precedes arrival, exceeds stream, or reuses capacity')
    ratio=budget_fraction(budget)
    cumulative=np.bincount(steps,minlength=len(ordered)).cumsum()
    if any(int(value)>n*ratio.numerator//ratio.denominator for n,value in enumerate(cumulative,1)):
        raise ValueError('Actions exceed a prefix inspection budget')
    if not np.array_equal(served.wait_records.to_numpy(),steps-served.arrival_step.to_numpy()):
        raise ValueError('Recorded wait differs from causal service timing')
    if not np.array_equal(served.service_shot.to_numpy(),ordered.Shot.to_numpy()[steps]):
        raise ValueError('Service Shot is not the production record at service time')
