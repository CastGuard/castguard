"""누수·계보·분할 검사.  실행: python -m pytest -q tests"""
import json

import numpy as np
import pandas as pd
import pytest

from castguard import paths
from castguard.features import add_feedback, feedback_columns, is_forbidden, quality_feature_sets
from castguard.prepare import PROCESS, add_history


def _fake_quality(n=120, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"run_id": np.r_[np.zeros(60, int), np.ones(n - 60, int)],
                         "source_row": np.arange(n), "y_defect": (rng.random(n) < 0.3).astype(int)})


@pytest.mark.parametrize("k", [10, 59, 75])
def test_feedback_uses_only_labels_older_than_delay(k):
    delay = 20
    base = _fake_quality()
    changed = base.copy()
    changed.loc[k:, "y_defect"] = 1 - changed.loc[k:, "y_defect"]
    cols = feedback_columns()
    a = add_feedback(base, delay)[cols]
    b = add_feedback(changed, delay)[cols]
    safe = base.index < k + delay                       # k 이후 라벨은 k+delay 이전 예측에 영향을 주면 안 됨
    pd.testing.assert_frame_equal(a[safe], b[safe])


def test_feedback_resets_each_run():
    f = add_feedback(_fake_quality(), 20)
    assert f.loc[60:79, "fb_rate20"].isna().all()       # 새 구간 첫 20 Shot은 알려진 검사결과 없음


def test_history_does_not_look_ahead():
    rng = np.random.default_rng(1)
    n = 40
    m = pd.DataFrame({c: rng.random(n) for c in PROCESS})
    m["Shot"] = np.r_[np.arange(1, 21), np.arange(1, 21)]
    m["run_id"] = np.r_[np.zeros(20, int), np.ones(20, int)]
    m["Machine_Status"] = 0.0
    m.loc[[5, 6, 25], "Machine_Status"] = 1.0
    from castguard.prepare import REL
    cols = ["prev_cycle_time", "max_cycle_previous_5", "missing_process_previous_20", "missing_shots_before_current"] + REL
    a = add_history(m)[cols]
    m2 = m.copy()
    m2.loc[12:, "Cycle_Time"] = 999.0
    b = add_history(m2)[cols]
    pd.testing.assert_frame_equal(a.loc[:11], b.loc[:11])        # 12행부터 바뀐 값은 12행 이전에 영향 없음


needs_data = pytest.mark.skipif(not paths.FOLDS.exists(), reason="python -m castguard prepare 먼저 실행")


@needs_data
def test_feature_sets_have_no_labels_or_ids():
    contract = json.loads(paths.CONTRACT.read_text(encoding="utf-8"))
    for name, feats in quality_feature_sets(contract, (20, 50, 100)).items():
        assert not [f for f in feats if is_forbidden(f, contract)], name


@needs_data
def test_join_is_one_to_one_and_complete():
    j = pd.read_parquet(paths.JOINED)
    assert len(j) == 4617 and not j.duplicated(["run_id", "Shot"]).any()
    assert j.Machine_Status.eq(0).all() and j.source_row_m41.notna().all()


@needs_data
def test_within_run_split_is_chronological_and_disjoint():
    f = pd.read_csv(paths.FOLDS, dtype={"fold": str, "episode_id": str, "order": str})
    q = f[(f.dataset == "q42") & (f.scheme == "within_run")]
    assert q.row_id.is_unique
    code = q.role.map({"train": 0, "validation": 1, "test": 2})
    for _, g in q[q.role != "excluded"].assign(code=code, o=q.order.astype(int)).groupby("run_id"):
        assert g.sort_values("o").code.is_monotonic_increasing


@needs_data
def test_warmup_episode_never_split_across_roles():
    f = pd.read_csv(paths.FOLDS, dtype={"fold": str, "episode_id": str, "order": str})
    m = f[(f.dataset == "m41") & (f.role != "excluded") & f.episode_id.notna()]
    assert (m.groupby(["scheme", "fold", "episode_id"]).role.nunique() == 1).all()


def test_slot_queue_capacity_priority_and_no_banking():
    import pandas as pd
    from castguard.analysis import stream_queue, queue_capacity
    n = 20
    rows = pd.DataFrame({"row_id": [f"r{i}" for i in range(n)], "source_row": range(n), "Shot": range(1, n + 1),
                         "process_missing": [False] * n, "gate_alarm": [False] * n, "gate_p": [0.0] * n,
                         "quality_p": [0.1] * n})
    rows.loc[3, "quality_p"] = 0.9
    rows.loc[4, "process_missing"] = True
    rows.loc[5, ["gate_alarm", "gate_p"]] = [True, 0.8]
    for policy in ["FIFO", "Q", "GQ"]:
        a = stream_queue(rows, policy, 0.2)
        assert a.inspected.sum() <= queue_capacity(n, 0.2) == 4
        assert (a.wait_records.dropna() >= 0).all()          # 도착 전에 검사하지 않는다
        assert a.loc[4, "inspected"]                         # 결측 보류는 모든 정책에서 최우선
    assert stream_queue(rows, "Q", 0.2).loc[3, "inspected"]
    assert stream_queue(rows, "GQ", 0.2).loc[5, "inspected"]
    # 슬롯은 이월되지 않는다: 앞쪽이 비어 있으면 그 슬롯은 사라진다
    empty = rows.assign(quality_p=float("nan"), process_missing=False, gate_alarm=False)
    empty.loc[n - 1, "quality_p"] = 0.5
    assert stream_queue(empty, "Q", 0.2).inspected.sum() == 1
