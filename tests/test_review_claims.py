"""Synthetic source-backed counterexamples; no saved artifact or model training dependency."""
from copy import deepcopy
import pandas as pd
import pytest

from oct03_queue import stream_queue, measure
from review_claims import summarize_actions, validate, validate_text, check_suffix_claims, source_facts, ACTION_SOURCE, QUALITY_SOURCE, STATE_SOURCE


def source_fixture():
    scores = pd.DataFrame({'row_id': [f'r{i}' for i in range(10)], 'source_row': range(10),
        'run_id': 0, 'Shot': range(1, 11), 'process_complete': [False] + [True] * 9,
        'gate_probability': [.1] * 5 + [.99] + [.1] * 4,
        'quality_probability': [float('nan')] + [i / 10 for i in range(1, 10)], 'ood_score': 0.})
    truth = scores[['row_id', 'run_id', 'Shot', 'source_row']].assign(
        Machine_Status=[1, 0, 0, 0, 0, 1, 0, 1, 0, 0],
        episode_id=['missing', None, None, None, None, 'observed_a', None, 'observed_b', None, None])
    quality = scores.iloc[1:][['run_id', 'Shot']].assign(y_defect=[0] * 8 + [1])
    panels, measured = [], {}
    for policy in ['Q', 'GQ']:
        actions = stream_queue(scores, policy, .8, False, None, .2)
        metrics, merged, episodes = measure(actions, truth, quality, .2)
        measured[policy] = (metrics, episodes)
        for seed in [17, 29]:
            panels.append(merged.assign(policy=policy, seed=seed, fold='f1', budget=.2))
    return pd.concat(panels, ignore_index=True), measured


@pytest.fixture
def facts():
    return summarize_actions(source_fixture()[0])


@pytest.fixture
def manuscript():
    # Deliberately unlike actual data (3/2 episodes, -20 cost): expected numeric
    # values come from synthetic actions, not a frozen production prose string.
    return '''관측 가능 2개 중 GQ 검사 도달은 1/2다. 전체와 관측 가능 도달은 다르다.

| 상태 에피소드 | 전체/관측 가능 | GQ 탐지 1/3·1/2, 도달 2/3·1/2. Q 도달 1/3·0/2. 탐지와 도달 합산 금지 |

접미사 _1/_2는 불량열 이름이다. 실제 cavity 대응은 확인되지 않았다.

관측 정답의 편익만 포함한 r=20, s=1, p=0 시나리오는 -20.00검사비 단위다. 미관측 추가 검사 0건의 품질 편익은 미측정이며 0으로 확정하지 않는다. 미관측 편익을 계산에 포함하지 않는 조건에서만 추가 도달 1개에 각각 20.00검사비 단위의 중복 없는 편익이 필요하다. 실제 손익분기점·ROI가 아니다.
'''


def test_existing_measure_is_correct_for_reached_unobservable_episode(facts):
    _, measured = source_fixture()
    metrics, episodes = measured['GQ']
    assert (metrics['episodes_total'], metrics['episodes_observable']) == (3, 2)
    assert metrics['episodes_inspection_reached'] == 2
    assert metrics['inspection_episode_reach_total'] == pytest.approx(2 / 3)
    assert sum(e['observable'] and e['inspection_reached'] for e in episodes) == 1
    assert facts['policies']['GQ']['reached_observable'] == 1
    assert measured['Q'][0]['episodes_inspection_reached'] == 1
    assert facts['policies']['Q']['reached_observable'] == 0


def test_valid_claims_use_source_counts_not_hardcoded_production_numbers(manuscript, facts):
    result = validate_text(manuscript, facts)
    assert result['cost']['observed_only_value'] == -20
    assert result['cost']['conditional_episode_offset'] == 20


@pytest.mark.parametrize('before,after,diagnostic', [
    ('도달 2/3·1/2', '도달 2/3·2/2', 'filter the numerator'),
    ('도달 1/3·0/2', '도달 1/3·1/2', 'Q 도달'),
    ('탐지 1/3·1/2', '탐지 1/2·1/3', 'GQ 탐지'),
    ('GQ 검사 도달은 1/2', 'GQ 검사 도달은 2/2', 'observed narrative reach'),
])
def test_historical_denominator_mixing_is_rejected(manuscript, facts, before, after, diagnostic):
    with pytest.raises(ValueError, match=diagnostic):
        validate_text(manuscript.replace(before, after), facts)


def test_changed_observability_invalidates_old_report(manuscript):
    actions, _ = source_fixture()
    actions.loc[actions.episode_id.eq('missing'), 'process_complete'] = True
    changed = summarize_actions(actions)
    assert changed['policies']['GQ']['observable'] == 3
    with pytest.raises(ValueError, match='filter the numerator'):
        validate_text(manuscript, changed)


def test_folds_are_pooled_before_ratio_and_episode_ids_are_fold_scoped():
    actions, _ = source_fixture()
    second = actions.loc[actions.row_id.ne('r7')].copy()
    second['fold'] = 'f2'
    facts = summarize_actions(pd.concat([actions, second]))
    assert facts['policies']['GQ']['total'] == 5
    assert facts['policies']['GQ']['observable'] == 3
    assert facts['policies']['GQ']['reached_all'] == 4
    assert facts['policies']['GQ']['reached_observable'] == 2


def test_observability_belongs_to_whole_episode_not_only_inspected_rows():
    actions, _ = source_fixture()
    actions.loc[actions.episode_id.eq('missing'), 'episode_id'] = 'observed_a'
    facts = summarize_actions(actions)
    # Q inspects only the missing-input row of this partly observed episode.
    assert facts['policies']['Q']['total'] == facts['policies']['Q']['observable'] == 2
    assert facts['policies']['Q']['reached_observable'] == 1


@pytest.mark.parametrize('change,diagnostic', [
    ('duplicate', 'duplicate action identity'), ('drop_seed', 'unpaired policy seeds'),
    ('drop_row', 'identical source rows'), ('no_episode', 'no episode identifier'),
])
def test_incomplete_source_population_cannot_validate_a_report(change, diagnostic):
    actions, _ = source_fixture()
    if change == 'duplicate':
        actions = pd.concat([actions, actions.iloc[:1]])
    elif change == 'drop_seed':
        actions = actions.loc[~(actions.policy.eq('Q') & actions.seed.eq(29))]
    elif change == 'drop_row':
        actions = actions.drop(index=0)
    else:
        actions.loc[actions.Machine_Status.eq(1), 'episode_id'] = None
    with pytest.raises(ValueError, match=diagnostic):
        summarize_actions(actions)


@pytest.mark.parametrize('sentence', [
    '접미사 _1/_2는 불량열 이름이며 각각 cavity 1과 2를 뜻한다.',
    '접미사 _1/_2는 두 cavity의 불량열이다.',
])
def test_historical_cavity_assertion_has_no_primary_definition(sentence):
    with pytest.raises(ValueError, match='primary authority'):
        check_suffix_claims(sentence)


@pytest.mark.parametrize('sentence', [
    '접미사 _1/_2는 불량열 구분이다. 실제 cavity 대응은 미확인이다.',
    '접미사 _1/_2는 불량열이다. cavity로 가정한 집계는 물리 검증이 필요하다.',
    '접미사 _1/_2는 불량열이다. cavity 대응을 원문으로 확인해야 한다.',
])
def test_cavity_word_is_allowed_when_uncertain_or_conditional(sentence):
    assert check_suffix_claims(sentence)['physical_mapping'] == 'unverified'


@pytest.mark.parametrize('omitted,diagnostic', [
    ('관측 정답의 편익만 포함한 ', 'observed-only benefit scope'),
    ('미측정이며 ', 'unknown benefit remains unmeasured'),
    ('0으로 확정하지 않는다.', 'not established as zero'),
    ('미관측 편익을 계산에 포함하지 않는 조건에서만 ', 'excluded only'),
    ('중복 없는 ', 'must not double count'),
    ('실제 손익분기점·ROI가 아니다.', 'not measured field'),
])
def test_historical_cost_assumption_omissions_fail(manuscript, facts, omitted, diagnostic):
    with pytest.raises(ValueError, match=diagnostic):
        validate_text(manuscript.replace(omitted, ''), facts)


def test_cost_parameters_recompute_value_instead_of_checking_frozen_number(manuscript, facts):
    changed = manuscript.replace('r=20', 'r=10')
    with pytest.raises(ValueError, match='source calculation -10'):
        validate_text(changed, facts)
    assert validate_text(changed.replace('-20.00', '-10.00').replace('각각 20.00', '각각 10.00'), facts)['status'] == 'passed'


def test_equivalent_conditional_cost_wording_remains_allowed(manuscript, facts):
    changed = manuscript.replace('관측 정답의 편익만 포함', '관측 결과의 편익만 계산')
    changed = changed.replace('미측정이며', '측정되지 않았으며')
    changed = changed.replace('0으로 확정하지 않', '0이라고 단정하지 않')
    changed = changed.replace('계산에 포함하지 않는 조건', '계산에서 제외하는 가정')
    changed = changed.replace('중복 없는 편익', '중복 계상하지 않는 편익')
    changed = changed.replace('실제 손익분기점·ROI가 아니다', '실제 ROI를 뜻하지 않는다')
    assert validate_text(changed, facts)['status'] == 'passed'


def test_current_build_uses_canonical_and_rejects_bad_claim_before_output(tmp_path, monkeypatch, facts, manuscript):
    import build_review
    import review_claims
    (tmp_path / 'review').mkdir()
    canonical = tmp_path / 'review/CastGuard_report.md'
    canonical.write_text(manuscript, encoding='utf-8')
    historic = tmp_path / 'reports/submission_round8'
    historic.mkdir(parents=True)
    (historic / 'CastGuard_current_review.md').write_text('ARCHIVED OLD CLAIMS', encoding='utf-8')
    monkeypatch.setattr(review_claims, 'source_facts', lambda root: deepcopy(facts))
    prior, current, text, proof = build_review.checked_manuscript(tmp_path)
    assert prior == canonical and current and text == manuscript and proof['status'] == 'passed'
    canonical.write_text(manuscript.replace('도달 2/3·1/2', '도달 2/3·2/2'), encoding='utf-8')
    monkeypatch.setattr(build_review, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='filter the numerator'):
        build_review.build(tmp_path / 'invalid_export', report_only=True)
    assert not (tmp_path / 'invalid_export').exists()


@pytest.mark.parametrize('corruption', [None, 'quality', 'nullable_missing_quality', 'state', 'key'])
def test_raw_source_keys_and_labels_bind_saved_actions(tmp_path, corruption):
    actions, _ = source_fixture()
    base = actions.loc[actions.policy.eq('Q') & actions.seed.eq(17)]
    for name in [ACTION_SOURCE, QUALITY_SOURCE, STATE_SOURCE]:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    base[['Shot', 'Machine_Status']].to_csv(tmp_path / STATE_SOURCE, index=False)
    quality = base.loc[base.y_defect.notna(), ['Shot']].copy()
    quality['Product_Type'] = 1
    quality['Short_Shot_1'] = base.loc[base.y_defect.notna(), 'y_defect'].astype(int)
    quality['Short_Shot_2'] = 0
    (tmp_path / QUALITY_SOURCE).write_text('Process,Process,Defects,Defects\n' + quality.to_csv(index=False), encoding='utf-8')
    if corruption == 'quality':
        actions.loc[actions.Shot.eq(10), 'y_defect'] = 0
    elif corruption == 'nullable_missing_quality':
        actions['y_defect'] = actions.y_defect.astype('Int64')
        actions.loc[actions.Shot.eq(10), 'y_defect'] = pd.NA
    elif corruption == 'state':
        actions.loc[actions.Shot.eq(10), 'Machine_Status'] = 1
    elif corruption == 'key':
        actions.loc[actions.Shot.eq(10), 'Shot'] = 999
    actions.to_parquet(tmp_path / ACTION_SOURCE)
    if corruption:
        with pytest.raises(ValueError, match='raw source keys|absent from raw state'):
            source_facts(tmp_path)
    else:
        result = source_facts(tmp_path)
        assert result['suffix_schema'] == {'defect_columns': 2, 'paired_types': 1, 'physical_cavity_mapping': 'unverified'}
        assert result['policies']['Q']['hits'] == 1
        assert len(result['source_hashes']) == 3


def test_unobserved_only_cannot_masquerade_as_observed_only(manuscript, facts):
    with pytest.raises(ValueError, match='observed-only benefit scope'):
        validate_text(manuscript.replace('관측 정답의 편익만 포함한', '미관측 정답의 편익만 포함한'), facts)


def test_historical_bootstrap_is_labeled_unreviewed(tmp_path):
    from build_review import checked_manuscript
    historic = tmp_path / 'reports/submission_round8'
    historic.mkdir(parents=True)
    (historic / 'CastGuard_current_review.md').write_text('ARCHIVED', encoding='utf-8')
    _, current, _, proof = checked_manuscript(tmp_path)
    assert not current and proof['status'] == 'not_checked_historical_bootstrap'


@pytest.mark.parametrize('style', ['soft_wrap', 'bold_policy', 'bold_kpi', 'indented_row'])
@pytest.mark.parametrize('wrong_numerator', [False, True])
def test_normal_markdown_formatting_preserves_claim_checks(manuscript, facts, style, wrong_numerator):
    if wrong_numerator:
        manuscript=manuscript.replace('도달 2/3·1/2', '도달 2/3·2/2')
    if style == 'soft_wrap':
        manuscript=manuscript.replace('관측 가능 2개 중 GQ 검사 도달은', '관측\n가능 2개 중 GQ 검사\n도달은')
    elif style == 'bold_policy':
        manuscript=manuscript.replace('GQ 탐지', '**GQ** 탐지')
    elif style == 'bold_kpi':
        manuscript=manuscript.replace('| 상태 에피소드 |', '| **상태 에피소드** |')
    else:
        manuscript=manuscript.replace('| 상태 에피소드 |', '  | 상태 에피소드 |')
    if wrong_numerator:
        with pytest.raises(ValueError,match='filter the numerator'):
            validate_text(manuscript,facts)
    else:
        assert validate_text(manuscript,facts)['status']=='passed'


@pytest.mark.parametrize('missing', [ACTION_SOURCE, QUALITY_SOURCE, STATE_SOURCE, 'review/CastGuard_report.md'])
def test_missing_artifact_is_actionable_failure_not_silent_guard_skip(tmp_path, missing):
    for name in [ACTION_SOURCE, QUALITY_SOURCE, STATE_SOURCE, 'review/CastGuard_report.md']:
        if name == missing:continue
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('placeholder; missing evidence must fail before parsing',encoding='utf-8')
    with pytest.raises(ValueError,match='missing:') as exc:
        validate(tmp_path)
    assert missing in str(exc.value) and 'source-only tests do not validate' in str(exc.value)
