from itertools import product
import numpy as np
import pandas as pd
import pytest
from audit_missing_quality import paired_panel,exact_vote_envelope
from experiment_integrity import missing_quality_contrast_bounds,queue_accounting


@pytest.mark.parametrize('left,right',[
    ([[1,1,0,0],[1,0,1,0]],[[1,1,0,0],[1,0,1,0]]),
    ([[1,1,1,0],[0,1,0,1]],[[0,1,0,1],[1,1,0,0]]),
    ([[1,0,0,0],[1,0,0,0]],[[0,1,1,1],[0,1,1,1]]),
    ([[0,1,1,1],[0,1,1,1]],[[1,0,0,0],[1,0,0,0]]),
])
def test_bounds_match_exhaustive_shared_labels_with_overlapping_seed_actions(left,right):
    # Row 0 is an observed positive. The same three unknown outcomes apply
    # to both policies and both seeds. No independent imputation per policy.
    left=np.asarray(left);right=np.asarray(right);values=[]
    for tail in product([0,1],repeat=3):
        y=np.array([1,*tail])
        values.append(float(((left@y)/y.sum()-(right@y)/y.sum()).mean()))
    known=int((left[:,0]-right[:,0]).sum());votes=(left[:,1:]-right[:,1:]).sum(axis=0)
    rational=exact_vote_envelope(1,known,votes,2)
    actual=missing_quality_contrast_bounds(1,known/2,votes/2)
    assert [float(x) for x in rational]==pytest.approx([min(values),max(values)])
    assert [actual['lower'],actual['upper']]==pytest.approx([min(values),max(values)])


def test_unknown_eligibility_without_requeue_is_equivalent_to_binary_positive_mass():
    # 0=ineligible,1=eligible negative,2=eligible positive. If actions stay
    # fixed, only category 2 enters a capture denominator or numerator.
    d=np.array([1.,-.5,.5]);values=[]
    for kinds in product([0,1,2],repeat=3):
        z=np.array(kinds)==2
        values.append((-.5+np.dot(d,z))/(2+z.sum()))
    actual=missing_quality_contrast_bounds(2,-.5,d)
    assert actual['lower']==pytest.approx(min(values))
    assert actual['upper']==pytest.approx(max(values))


def fixture():
    rows=[]
    for policy,seed,row in product(['Q','GQ'],[17,29],range(3)):
        rows.append(dict(fold='2',row_id='r'+str(row),run_id=1,Shot=row,source_row=row,
            y_defect=1 if row==0 else np.nan,process_complete=True,inspected=row==seed%3,
            policy=policy,seed=seed,budget=.2))
    actions=pd.DataFrame(rows)
    fifo=pd.DataFrame([dict(fold='2',row_id='r'+str(row),policy='FIFO',inspected=row==0) for row in range(3)])
    return actions,fifo


@pytest.mark.parametrize('change',['missing_seed','duplicate_action','inconsistent_label','inconsistent_availability',
    'repeated_shot_different_fold','missing_fifo','duplicate_fifo','non_boolean'])
def test_pairing_rejects_changes_that_would_distort_missing_quality_bounds(change):
    a,f=fixture()
    if change=='missing_seed':a=a.drop(index=0)
    elif change=='duplicate_action':a=pd.concat([a,a.iloc[[0]]],ignore_index=True)
    elif change=='inconsistent_label':a.loc[0,'y_defect']=0
    elif change=='inconsistent_availability':a.loc[0,'process_complete']=False
    elif change=='repeated_shot_different_fold':
        a=pd.concat([a,a.assign(fold='3')],ignore_index=True)
        f=pd.concat([f,f.assign(fold='3')],ignore_index=True)
    elif change=='missing_fifo':f=f.drop(index=0)
    elif change=='duplicate_fifo':f=pd.concat([f,f.iloc[[0]]],ignore_index=True)
    else:a['inspected']='False'
    with pytest.raises(ValueError):paired_panel(a,f,[17,29])


def test_pairing_retains_joint_seed_votes_and_missing_outcomes():
    a,f=fixture();panel=paired_panel(a,f,[17,29])
    assert len(panel)==3 and panel.y_defect.isna().sum()==2
    assert panel.Q_votes.tolist()==panel.GQ_votes.tolist()==[0,0,2]
    assert panel.FIFO_votes.tolist()==[2,0,0]


def test_no_service_on_a_non_slot_even_when_prefix_budget_and_waits_are_valid():
    n=10
    a=pd.DataFrame({'row_id':[str(i) for i in range(n)],'source_row':range(n),
        'arrival_step':range(n),'Shot':range(n),'inspected':[True,True]+[False]*8,
        'service_step':[5,9]+[-1]*8,'wait_records':[5.,8.]+[np.nan]*8,
        'service_shot':[5.,9.]+[np.nan]*8})
    # Step 5 is after the legal slot at step 4. Prefix sums alone permit this
    # banking of an unused slot; the registered queue does not.
    with pytest.raises(ValueError,match='service slot'):queue_accounting(a,.2)
