"""Focused Korean report claim checks; not a general natural-language fact checker.

Recompute pooled episode counts and observed-only cost inputs from fixed actions.
Check the named KPI row, queue explanation, suffix paragraph and cost scenario.
No model selection, physical-label inference, field ROI, or archive mutation.
"""
from pathlib import Path
from hashlib import sha256
import argparse
import csv
import json
import math
import re
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent
ACTION_SOURCE = 'reports/oct03_queue/outer_actions.parquet'
QUALITY_SOURCE = 'data/raw/DieCasting_Quality_Raw_Data.csv'
STATE_SOURCE = 'data/raw/DieCasting_Raw_Data.csv'
NUMBER = r'[-+]?\d+(?:\.\d+)?'
FRACTION = rf'({NUMBER})\s*/\s*({NUMBER})'


def require(condition, message):
    if not condition:
        raise ValueError('Report claim: ' + message)


def compact(text):
    return re.sub(r'\s+', '', text)


def claim_text(text):
    """Ignore ordinary inline Markdown emphasis, not wording or numeric content."""
    text = text.replace('\r\n', '\n')
    text = re.sub(r'\*\*([^\n]+?)\*\*', r'\1', text)
    return re.sub(r'`([^`\n]+)`', r'\1', text)


def source_facts(root=ROOT):
    """Bind saved actions to raw quality/state keys; headers establish suffixes only."""
    root = Path(root)
    missing = [name for name in (ACTION_SOURCE, QUALITY_SOURCE, STATE_SOURCE)
               if not (root / name).is_file()]
    require(not missing, 'required local source evidence missing: ' + ', '.join(missing)
            + '. Restore the saved actions/raw sources; source-only tests do not validate report artifacts.')
    with (root / QUALITY_SOURCE).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.reader(stream)
        categories, names = next(reader), next(reader)
    require(len(categories) == len(names), 'raw category/name header lengths disagree')
    labels = [name.strip() for category, name in zip(categories, names)
              if category.strip() == 'Defects']
    require(labels and len(labels) == len(set(labels)), 'raw Defects headers missing/duplicated')
    suffixes = {re.sub(r'_[12]$', '', name) for name in labels}
    require(set(labels) == {f'{name}_{side}' for name in suffixes for side in (1, 2)},
            'raw defect suffix schema changed; review the physical-meaning caveat')
    quality = pd.read_csv(root / QUALITY_SOURCE, header=1)
    quality.columns = quality.columns.str.strip()
    quality['run_id'] = quality.Shot.diff().lt(0).cumsum()
    quality = quality.drop_duplicates(['run_id', 'Shot']).set_index(['run_id', 'Shot'])
    require(quality[labels].notna().all().all(), 'raw defect labels contain missing values')
    quality['y_defect'] = quality[labels].gt(0).any(axis=1).astype(int)
    state = pd.read_csv(root / STATE_SOURCE)
    state['run_id'] = state.Shot.diff().lt(0).cumsum()
    state = state.set_index(['run_id', 'Shot'])
    require(state.index.is_unique, 'raw state keys are duplicated')
    actions = pd.read_parquet(root / ACTION_SOURCE)
    actions = actions.loc[actions.budget.eq(.2)].copy()
    keys = pd.MultiIndex.from_frame(actions[['run_id', 'Shot']])
    require(keys.isin(state.index).all(), 'action keys absent from raw state data')
    for name, expected in [('y_defect', quality.y_defect.reindex(keys)),
                           ('Machine_Status', state.Machine_Status.reindex(keys))]:
        actual = actions[name].reset_index(drop=True)
        expected = expected.reset_index(drop=True)
        require((actual.eq(expected) | (actual.isna() & expected.isna())).fillna(False).all(),
                name + ' disagrees with raw source keys')
    facts = summarize_actions(actions)
    facts['suffix_schema'] = {'defect_columns': len(labels), 'paired_types': len(suffixes),
                              'physical_cavity_mapping': 'unverified'}
    facts['source_hashes'] = {name: sha256((root / name).read_bytes()).hexdigest()
                            for name in (ACTION_SOURCE, QUALITY_SOURCE, STATE_SOURCE)}
    return facts


def summarize_actions(actions):
    """Pool folds within each seed before averaging; never average fold ratios."""
    require(not actions.empty, '20% saved action population is empty')
    require(actions.budget.eq(.2).all(), 'claim population must be the fixed 20% budget')
    identity = ['fold', 'row_id']
    require(not actions.duplicated(['policy', 'seed'] + identity).any(), 'duplicate action identity')
    for name in ['process_complete', 'alarm', 'inspected', 'hold']:
        require(actions[name].notna().all() and actions[name].isin([True, False]).all(),
                name + ' is not a complete boolean action')
    require(actions.loc[actions.Machine_Status.eq(1), 'episode_id'].notna().all(),
            'state-1 action has no episode identifier')
    require({'Q', 'GQ'}.issubset(set(actions.policy)), 'Q/GQ actions are required')
    panels = []
    reference = None
    seed_sets = []
    for policy, part in actions.groupby('policy'):
        seed_sets.append(set(part.seed))
        for seed, frame in part.groupby('seed'):
            ordered = frame.set_index(identity).sort_index()
            shared = ordered[['run_id', 'Shot', 'Machine_Status', 'episode_id',
                              'process_complete', 'y_defect']]
            if reference is None:
                reference = shared
            require(shared.equals(reference), 'policies/seeds must share identical source rows and truth')
            eps = frame.loc[frame.Machine_Status.eq(1)].groupby(['fold', 'episode_id']).agg(
                observable=('process_complete', 'any'), auto=('alarm', 'any'), reached=('inspected', 'any'))
            row = {'policy': policy, 'seed': seed, 'total': len(eps),
                   'observable': int(eps.observable.sum())}
            for name in ['auto', 'reached']:
                row[name + '_all'] = int(eps[name].sum())
                row[name + '_observable'] = int(eps.loc[eps.observable, name].sum())
            row.update(hits=int((frame.y_defect.eq(1) & frame.inspected).sum()),
                       inspected=int(frame.inspected.sum()),
                       unknown_inspected=int((frame.y_defect.isna() & frame.inspected).sum()),
                       backlog=int((frame.hold & ~frame.inspected).sum()))
            panels.append(row)
    require(all(seeds == seed_sets[0] for seeds in seed_sets), 'unpaired policy seeds')
    counts = pd.DataFrame(panels)
    means = counts.drop(columns='seed').groupby('policy').mean().to_dict('index')
    return {'budget': .2, 'seed_count': len(seed_sets[0]), 'policies': means,
            'aggregation': 'sum episodes across folds per seed, then mean across matched seeds',
            'episode_denominators': 'state 1; observable if any row has complete process input'}


def check_episode_claims(text, facts):
    rows = [line.strip() for line in text.splitlines() if re.match(r'^\s*\|\s*상태\s*에피소드\s*\|', line)]
    require(len(rows) == 1, 'one 상태 에피소드 KPI row is required with labeled all/observable fractions')
    # Parse policy and metric labels, not a snapshot of the surrounding prose.
    matches = re.findall(r'\b(GQ|Q|OOD05|OOD1)\s+(.+?)(?=\s+\b(?:GQ|Q|OOD05|OOD1)\s+|\|$)', rows[0])
    parsed = {}
    for policy, part in matches:
        for metric, expression in re.findall(r'(탐지|도달)\s+([^,|]+)', part):
            fractions = [(float(n), float(d)) for n, d in re.findall(FRACTION, expression)]
            if fractions:
                key = (policy, metric)
                require(key not in parsed, 'duplicate episode KPI claim: ' + str(key))
                parsed[key] = fractions
    required = {('GQ', '탐지'), ('GQ', '도달'), ('Q', '도달')}
    require(required.issubset(parsed), 'episode KPI must label GQ detection/reach and Q reach')
    for (policy, metric), actual in parsed.items():
        require(policy in facts['policies'], 'episode claim has no saved policy: ' + policy)
        row = facts['policies'][policy]
        name = 'auto' if metric == '탐지' else 'reached'
        expected = [(row[name + '_all'], row['total']),
                    (row[name + '_observable'], row['observable'])]
        require(actual == expected,
                f'{policy} {metric}: expected all/observable {expected}, found {actual}; '
                'filter the numerator together with the denominator')
    # Also bind the explanatory observed-reach fractions; a correct KPI row must
    # not hide the historical 8/14 error in the adjacent queue narrative.
    paragraphs = [re.sub(r'\s+', ' ', p).strip() for p in text.split('\n\n')]
    narrative = [p for p in paragraphs if not p.startswith('|')
                 and '관측 가능' in p and '검사 도달' in p and 'GQ' in p]
    require(len(narrative) == 1, 'queue explanation must distinguish observed inspection reach')
    for policy in ['GQ', 'OOD05']:
        if policy not in facts['policies']:
            continue
        hit = re.search(rf'\b{policy}(?:\s*검사\s*도달)?(?:은|는)?\s*{FRACTION}', narrative[0])
        require(hit is not None, policy + ' observed reach fraction missing in queue explanation')
        row = facts['policies'][policy]
        actual = tuple(float(x) for x in hit.groups())
        require(actual == (row['reached_observable'], row['observable']),
                f'{policy} observed narrative reach {actual} disagrees with source '
                f"{row['reached_observable']}/{row['observable']}")
    return {'kpi_claims': len(parsed), 'narrative_reach_checked': True}


def check_suffix_claims(text):
    paragraphs = [p for p in text.split('\n\n') if '_1/_2' in p or ('접미사' in p and '_1' in p and '_2' in p)]
    require(len(paragraphs) == 1, 'one _1/_2 suffix interpretation paragraph is required')
    paragraph = compact(paragraphs[0])
    require('불량열' in paragraph, 'suffixes must be identified as raw defect columns')
    statements = [s for s in re.split(r'[.!?。\n]', paragraphs[0]) if re.search(r'cavity|캐비티', s, re.I)]
    require(statements, 'suffix physical meaning must be explicitly qualified as unverified')
    qualifier = r'확인되지않|확정되지않|미확인|미검증|확정할수없|단정할수없|가정|확인해야|검증해야'
    for statement in statements:
        require(re.search(qualifier, compact(statement)),
                '_1/_2 cavity mapping lacks primary authority: keep an unverified/conditional '
                'qualification in the same statement, or review new source evidence')
    return {'physical_mapping': 'unverified', 'qualified_statements': len(statements)}


def check_cost_claims(text, facts):
    paragraphs = [p for p in text.split('\n\n') if re.search(r'\br\s*=\s*' + NUMBER + r'\s*,\s*s\s*=', p)]
    require(len(paragraphs) == 1, 'one explicit r, s, p cost scenario paragraph is required')
    paragraph = paragraphs[0]
    value = compact(paragraph)
    checks = {
        'observed-only benefit scope': r'(?<!미)관측(?:정답|품질|결과|양성).*?편익만(?:포함|계산|계상)',
        'unknown benefit remains unmeasured': r'미관측.*?편익.*?(?:미측정|알수없|측정되지않|확인되지않)',
        'unknown benefit is not established as zero': r'0(?:으로(?:확정|간주|대체)하지않|이라고단정하지않)',
        'unknown benefit excluded only for this calculation': r'미관측편익.*?(?:계산에포함하지않|계산에서제외)',
        'episode benefit must not double count': r'중복(?:없는|계상하지않는)편익',
        'not measured field breakeven/ROI': r'(?:실제손익분기점|ROI).*?(?:아니|뜻하지않|의미하지않)',
    }
    for label, pattern in checks.items():
        require(re.search(pattern, value), 'cost assumption missing: ' + label)
    params = {}
    for name in ['r', 's', 'p']:
        match = re.search(rf'\b{name}\s*=\s*({NUMBER})', paragraph)
        require(match is not None, 'cost scenario parameter missing: ' + name)
        params[name] = float(match.group(1))
    require(params['r'] >= 0 and 0 <= params['s'] <= 1 and params['p'] >= 0,
            'cost scenario parameters outside declared domain')
    left, right = (facts['policies'][p] for p in ['GQ', 'Q'])
    delta = {name: left[name] - right[name]
             for name in ['hits', 'inspected', 'unknown_inspected', 'backlog', 'reached_all']}
    benefit = params['r'] * params['s'] * delta['hits'] - delta['inspected'] - params['p'] * delta['backlog']
    require(delta['reached_all'] > 0, 'per-extra-episode cost claim has no positive extra reach')
    offset = max(0., -benefit) / delta['reached_all']
    for pattern, expected, label in [
        (rf'시나리오는\s*({NUMBER})\s*검사비', benefit, 'observed-only scenario value'),
        (rf'각각\s*({NUMBER})\s*검사비', offset, 'per-extra-episode conditional offset'),
        (rf'미관측\s*추가\s*검사\s*({NUMBER})\s*건', delta['unknown_inspected'], 'unknown inspection delta'),
        (rf'추가\s*도달\s*({NUMBER})\s*개', delta['reached_all'], 'extra reached episodes'),
    ]:
        match = re.search(pattern, paragraph)
        require(match is not None, 'cost numeric claim missing: ' + label)
        require(math.isclose(float(match.group(1)), expected, abs_tol=.005, rel_tol=0),
                f'{label}: source calculation {expected:g}, report {match.group(1)}')
    return {'parameters': params, 'observed_only_value': benefit, 'conditional_episode_offset': offset,
            'unknown_quality_benefit': 'unmeasured; excluded from scenario, not established as zero'}


def validate_text(text, facts):
    text = claim_text(text)
    return {'schema_version': 1, 'status': 'passed',
            'episodes': check_episode_claims(text, facts),
            'suffixes': check_suffix_claims(text), 'cost': check_cost_claims(text, facts),
            'facts': facts, 'scope': 'named episode KPI/narrative, suffix paragraph, cost scenario; '
            'not exhaustive prose or primary physical/field validation'}


def validate(root=ROOT, text=None):
    root = Path(root)
    if text is None:
        manuscript = root / 'review/CastGuard_report.md'
        require(manuscript.is_file(), 'current manuscript missing: review/CastGuard_report.md. '
                'This command needs local report artifacts; source-only tests do not validate the report.')
        text = manuscript.read_text(encoding='utf-8')
    return validate_text(text, source_facts(root))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.root), ensure_ascii=False, indent=2))
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
