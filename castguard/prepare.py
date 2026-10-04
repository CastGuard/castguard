"""원본 CSV 3종 → 분석 테이블 3종 + 고정 분할표 + 입력 계약 + 데이터 품질표.

JH 브랜치의 검증된 전처리(castguard/rebuild.py)를 기반으로 하며, 달라진 점은 하나다.
- #40: timestamp(날짜)+date(시각)를 합친 시각은 날짜 라벨 안에서 0시로 여러 번 되돌아가
  실제 순서와 맞지 않는다. 파일 순서(날짜 라벨 오름차순 + production_count +1)를 검증한 뒤
  그 순서(seq)로 시간순 분할한다.

원칙: 결측 대체·스케일링·변수선택·리샘플링은 여기서 하지 않는다(학습 fold 안에서만).
"""
import json

import numpy as np
import pandas as pd

from . import paths

PROCESS = ["Velocity_1", "Velocity_2", "Velocity_3", "High_Velocity", "Cylinder_Pressure", "Rapid_Rise_Time",
           "Biscuit_Thickness", "Clamping_Force", "Cycle_Time", "Pressure_Rise_Time", "Casting_Pressure",
           "Spray_Time", "Spray_1_Time", "Spray_2_Time"]
SENSOR = ["Melting_Furnace_Temp", "Air_Pressure", "Coolant_Temp", "Coolant_Pressure", "Factory_Temp", "Factory_Humidity"]
LIMITS = [f"{b}_{s}" for b in ["Air_Pressure", "Coolant_Temp", "Factory_Temp", "Factory_Humidity"] for s in ["Min", "Max"]]
MAIN4 = ["Short_Shot", "Bubble", "Exfoliation", "Blow_Hole"]
HISTORY = ["prev_cycle_time", "max_cycle_previous_5", "missing_process_previous_20", "missing_shots_before_current"]
P40_INPUTS = ["mold_temperature", "facility_CycleTime", "production_CycleTime", "mechanical_strength",
              "injection_pressure", "sleeve_temperature", "top_temp1", "top_temp2", "top_temp3",
              "bottom_temp1", "bottom_temp2", "bottom_temp3", "biscuit_thickness", "cooling_water_temp"]
TEMP_COLS = ["mold_temperature", "sleeve_temperature"] + [f"{s}_temp{i}" for s in ["top", "bottom"] for i in [1, 2, 3]]


# ───────────────────────── #42 · #41 ─────────────────────────
def with_run(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """Shot이 감소하는 지점마다 run_id +1. 원본 행 위치와 행 ID를 붙인다."""
    frame = frame.copy()
    frame["run_id"] = frame.Shot.diff().lt(0).cumsum().astype(int)
    frame["source_row"] = np.arange(len(frame))
    frame["row_id"] = prefix + "_r" + frame.run_id.astype(str) + "_s" + frame.Shot.astype(str)
    return frame


def build_quality(raw_path=paths.RAW_Q42) -> tuple[pd.DataFrame, dict]:
    frame = pd.read_csv(raw_path, header=1)                      # 2단 헤더 중 두 번째 줄
    frame.columns = frame.columns.str.strip()
    original = list(frame.columns)
    frame = with_run(frame, "q42")
    n_raw = len(frame)
    frame = frame.drop_duplicates(["run_id"] + [c for c in original if c != "id"]).copy()   # 구간 내 완전 중복
    if frame.duplicated(["run_id", "Shot"]).any():
        raise ValueError("같은 (run_id, Shot)에 서로 다른 측정값이 있음")
    frame = frame.drop(columns=LIMITS)
    types = [c[:-2] for c in original if c.endswith("_1") and c not in PROCESS]
    targets = [f"{k}_{cav}" for cav in [1, 2] for k in types]
    frame["y_defect"] = frame[targets].gt(0).any(axis=1).astype("int8")
    for cav in [1, 2]:
        frame[f"y_cavity_{cav}"] = frame[[f"{k}_{cav}" for k in types]].gt(0).any(axis=1).astype("int8")
    for k in types:
        frame[f"y_type_{k}"] = frame[[f"{k}_1", f"{k}_2"]].gt(0).any(axis=1).astype("int8")
    frame["defect_type_count"] = frame[[f"y_type_{k}" for k in types]].sum(axis=1)
    other = [k for k in types if k not in MAIN4]
    frame["y_type_Etc"] = frame[[f"y_type_{k}" for k in other]].any(axis=1).astype("int8")
    frame["shot_position"] = frame.groupby("run_id").cumcount()
    info = {"q42_raw_rows": n_raw, "q42_duplicates_removed": n_raw - len(frame), "defect_types": types,
            "target_columns": targets}
    return frame.reset_index(drop=True), info


def add_history(frame: pd.DataFrame) -> pd.DataFrame:
    """#41 타임라인의 과거 이력. 모든 값은 현재 행을 제외한 과거 행만 사용하고 구간마다 초기화한다."""
    frame = frame.copy()
    frame["process_missing"] = frame[PROCESS].isna().any(axis=1)
    frame["gate_eligible"] = frame.Machine_Status.notna() & ~frame.process_missing
    frame["episode_id"] = pd.Series(pd.NA, index=frame.index, dtype="string")
    for run, group in frame.groupby("run_id", sort=False):
        warm = group.Machine_Status.eq(1)
        starts = warm & ~warm.shift(fill_value=False)
        episode = starts.cumsum()
        frame.loc[group.index[warm], "episode_id"] = "r" + str(run) + "_e" + episode[warm].astype(str)
        frame.loc[group.index, "prev_cycle_time"] = group.Cycle_Time.shift()
        frame.loc[group.index, "max_cycle_previous_5"] = group.Cycle_Time.shift().rolling(5, min_periods=1).max()
        frame.loc[group.index, "missing_process_previous_20"] = group.process_missing.astype(float).shift().rolling(20, min_periods=1).sum()
        frame.loc[group.index, "missing_shots_before_current"] = (group.Shot.diff() - 1).clip(lower=0)
        # oracle_*: 설비상태 '정답'을 쓴 참고 열. 기본 입력 금지(분석·오류분석용).
        frame.loc[group.index, "oracle_shots_since_warm"] = group.Shot - group.Shot.where(warm).ffill().shift()
        frame.loc[group.index, "oracle_prior_episodes"] = episode.shift(fill_value=0).astype(float)
    return frame


def build_timeline(raw_path=paths.RAW_M41) -> pd.DataFrame:
    m = add_history(with_run(pd.read_csv(raw_path), "m41"))
    if m.duplicated(["run_id", "Shot"]).any():
        raise ValueError("#41에 중복 (run_id, Shot)")
    return m


def join_quality_timeline(q: pd.DataFrame, m: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """#42 기준 (run_id, Shot) 1:1 조인. 공정 14개는 중복 입력하지 않고 일치만 검증한다."""
    additions = ["Machine_Status", "source_row", "episode_id"] + HISTORY + ["oracle_shots_since_warm", "oracle_prior_episodes"]
    check = q[["run_id", "Shot"] + PROCESS].merge(m[["run_id", "Shot"] + PROCESS], on=["run_id", "Shot"],
                                                   suffixes=("_q", "_m"), validate="one_to_one")
    equal = sum(int(np.isclose(check[f"{c}_q"], check[f"{c}_m"], rtol=0, atol=1e-9, equal_nan=True).sum()) for c in PROCESS)
    joined = q.merge(m[["run_id", "Shot"] + additions], on=["run_id", "Shot"], how="left",
                     suffixes=("", "_m41"), validate="one_to_one")
    if joined.source_row_m41.isna().any():
        raise ValueError("#41에 짝이 없는 #42 Shot")
    if not joined.Machine_Status.eq(0).all():
        raise ValueError("#42 Shot의 짝이 정상(0)이 아님")
    info = {"join_matched": len(check), "join_equal_values": equal, "join_total_values": len(check) * len(PROCESS)}
    if equal != info["join_total_values"]:
        raise ValueError(f"공정값 불일치: {info}")
    return joined, info


# ───────────────────────── #40 ─────────────────────────
def build_process40(raw_path=paths.RAW_D40, pressure_threshold: float = 615) -> tuple[pd.DataFrame, dict]:
    frame = pd.read_csv(raw_path)
    if not frame.timestamp.is_monotonic_increasing:
        raise ValueError("#40 날짜 라벨이 파일 안에서 오름차순이 아님")
    step = frame.groupby("timestamp", sort=False).production_count.diff().dropna()
    if not step.eq(1).all():
        raise ValueError("#40 날짜 라벨 안에서 production_count가 1씩 증가하지 않음")
    frame["source_row"] = np.arange(len(frame))
    frame["seq"] = frame["source_row"]                             # 검증된 파일 순서 = 시간 순서
    frame["row_id"] = "p40_" + frame.source_row.astype(str)
    naive = pd.to_datetime(frame.timestamp + " " + frame.date, format="%Y-%m-%d %H:%M:%S")
    moved = int((naive.sort_values(kind="stable").index.to_numpy() != np.arange(len(frame))).sum())
    frame["date_label"] = pd.to_datetime(frame.timestamp, format="%Y-%m-%d")
    frame = frame.drop(columns=["line_unit", "production", "top_temp4", "bottom_temp4", "molten_capacity"])
    for name in TEMP_COLS:
        frame[name + "_raw"] = frame[name]
        frame[name + "_suspect_high"] = frame[name].gt(1500)
        frame[name] = frame[name].astype(float).where(frame[name].gt(0))     # 0 이하 = 미기록으로 간주
    frame["label_available"] = frame.PassOrFail.notna()
    frame["normal_pressure"] = frame.injection_pressure.gt(pressure_threshold).astype("boolean").where(frame.injection_pressure.notna())
    frame["y_defect"] = frame.PassOrFail.astype("Int8")
    info = {"p40_rows": len(frame), "p40_rows_moved_if_naive_datetime_sort": moved,
            "p40_suspect_high_cells": int(sum(frame[c + "_suspect_high"].sum() for c in TEMP_COLS))}
    return frame, info


# ───────────────────────── 고정 분할 ─────────────────────────
def build_folds(q: pd.DataFrame, m: pd.DataFrame, p: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """데이터셋 × 검증방식 × fold별 역할(train/validation/test/excluded) 배정표.

    within_run : 구간마다 앞 70% 개발(그중 80% train, 20% validation), 뒤 30% test  ← 최종 성능
    run_holdout: 구간 하나를 test, 나머지 중 가장 뒤 구간을 validation           ← 구간 이동
    forward_run: 앞선 구간으로만 학습, 다음 구간 test                         ← 새 미래 구간 (실패 조건)
    m41은 q42와 같은 Shot 경계를 쓴다. p40은 seq 순서로 시간순 분할.
    """
    valid_runs = sorted(q.groupby("run_id").size().loc[lambda x: x >= cfg["min_run_size"]].index)
    cuts = {}
    for run in valid_runs:
        group = q.loc[q.run_id == run]
        dev = int(np.floor(len(group) * cfg["within_run_dev_ratio"]))
        train = int(np.floor(dev * cfg["within_run_train_ratio_of_dev"]))
        cuts[run] = (group.Shot.iloc[train - 1], group.Shot.iloc[dev - 1])
    parts = []
    for dataset, frame in [("q42", q), ("m41", m)]:
        schemes = ([("within_run", "primary")] + [("run_holdout", str(r)) for r in valid_runs]
                   + [("forward_run", str(r)) for r in valid_runs[2:]])
        for scheme, fold in schemes:
            roles = pd.Series("excluded", index=frame.index)
            if scheme == "within_run":
                for run, (train_end, val_end) in cuts.items():
                    mask = frame.run_id == run
                    roles.loc[mask] = np.select([frame.loc[mask, "Shot"] <= train_end, frame.loc[mask, "Shot"] <= val_end],
                                                ["train", "validation"], default="test")
            else:
                test_run = int(fold)
                other = [r for r in valid_runs if r != test_run and (scheme != "forward_run" or r < test_run)]
                val_run = max(other)
                roles.loc[frame.run_id.isin([r for r in other if r != val_run])] = "train"
                roles.loc[frame.run_id == val_run] = "validation"
                roles.loc[frame.run_id == test_run] = "test"
            if dataset == "m41":
                roles.loc[~frame.gate_eligible] = "excluded"
            parts.append(pd.DataFrame({"dataset": dataset, "scheme": scheme, "fold": fold, "row_id": frame.row_id,
                                       "role": roles, "run_id": frame.run_id, "order": frame.source_row.astype(str),
                                       "episode_id": (frame.episode_id if dataset == "m41"
                                                      else pd.Series(pd.NA, index=frame.index, dtype="string"))}))
    n = len(p)
    dev = int(np.floor(n * cfg["p40_dev_ratio"]))
    train = int(np.floor(dev * cfg["p40_train_ratio_of_dev"]))
    roles = np.select([p.seq < train, p.seq < dev], ["train", "validation"], default="test")
    roles = pd.Series(roles, index=p.index).where(p.label_available, "excluded")
    parts.append(pd.DataFrame({"dataset": "p40", "scheme": "chronological", "fold": "primary", "row_id": p.row_id,
                               "role": roles, "run_id": -1, "order": p.seq.astype(str),
                               "episode_id": pd.Series(pd.NA, index=p.index, dtype="string")}))
    return pd.concat(parts, ignore_index=True)


# ───────────────────────── 계약 · 품질표 ─────────────────────────
def feature_contract(target_columns: list[str]) -> dict:
    a = PROCESS + SENSOR + ["Product_Type", "shot_position"]
    return {
        "prediction_time": "현재 Shot 생산 완료 후, 최종검사 전",
        "q42_A0": PROCESS, "q42_A": a, "q42_B": a + HISTORY,
        "m41_gate": PROCESS + ["prev_cycle_time", "max_cycle_previous_5"],
        "p40_full": P40_INPUTS,
        "feedback_note": "fb_* 열은 학습 단계에서 label_delay_shots만큼 지연된 '과거 검사결과'로 계산한다.",
        "target_columns": target_columns + ["Machine_Status", "PassOrFail", "y_defect", "y_type_*", "y_cavity_*"],
        "forbidden": ["id", "_id", "run_id", "row_id", "source_row", "source_row_m41", "episode_id",
                      "defect_type_count", "oracle_*"],
    }


def quality_row(df, dataset, stage, cols, key=None, invalid=None, consistency=None):
    cols = [c for c in cols if c in df.columns]
    sub = df[cols]
    return {"dataset": dataset, "stage": stage, "rows": len(df), "cols": len(cols),
            "completeness": round(1 - float(sub.isna().mean().mean()), 4),
            "uniqueness": round(1 - float((df.duplicated(key) if key else sub.duplicated()).mean()), 4),
            "validity": round(1 - float(invalid.mean()), 4) if invalid is not None else None,
            "consistency": consistency, "accuracy": "미측정(외부 정답 없음)", "timeliness": "미측정(수집 SLA 없음)"}


def run(cfg: dict) -> dict:
    paths.ensure_dirs()
    q, qi = build_quality()
    m = build_timeline()
    joined, ji = join_quality_timeline(q, m)
    p, pi = build_process40(pressure_threshold=cfg["p40_normal_pressure_threshold"])
    folds = build_folds(q, m, p, cfg)

    joined.to_parquet(paths.JOINED, index=False)
    m.to_parquet(paths.M41, index=False)
    p.to_parquet(paths.P40, index=False)
    folds.to_csv(paths.FOLDS, index=False)
    contract = feature_contract(qi["target_columns"])
    paths.CONTRACT.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")

    q_raw = pd.read_csv(paths.RAW_Q42, header=1)
    q_raw.columns = q_raw.columns.str.strip()
    q_raw = with_run(q_raw, "q42")
    q_cols = [c for c in pd.read_csv(paths.RAW_Q42, header=1, nrows=0).columns.str.strip() if c != "id"]
    m_raw = with_run(pd.read_csv(paths.RAW_M41), "m41")
    p_raw = pd.read_csv(paths.RAW_D40)
    hv0 = lambda d: d.High_Velocity.eq(0) | d.Biscuit_Thickness.eq(0)
    dq = pd.DataFrame([
        quality_row(q_raw, "q42", "raw", ["run_id"] + q_cols, invalid=hv0(q_raw)),
        quality_row(joined, "q42", "processed", ["run_id"] + [c for c in q_cols if c not in LIMITS], invalid=hv0(joined),
                    consistency=ji["join_equal_values"] / ji["join_total_values"]),
        quality_row(m_raw, "m41", "raw", list(pd.read_csv(paths.RAW_M41, nrows=0).columns), key=["run_id", "Shot"], invalid=hv0(m_raw)),
        quality_row(m, "m41", "processed", PROCESS + ["Machine_Status"], key=["run_id", "Shot"], invalid=hv0(m)),
        quality_row(p_raw, "p40", "raw", list(p_raw.columns), invalid=p_raw.mold_temperature.le(0)),
        quality_row(p, "p40", "processed", P40_INPUTS + ["PassOrFail"], key=["row_id"],
                    invalid=p[[c + "_suspect_high" for c in TEMP_COLS]].any(axis=1)),
    ])
    dq.to_csv(paths.TABLES / "data_quality.csv", index=False, encoding="utf-8-sig")

    warm = m.Machine_Status.eq(1)
    report = {**qi, **ji, **pi,
              "q42_rows": len(joined), "q42_defect_rate": round(float(joined.y_defect.mean()), 4),
              "q42_cavity1_rate": round(float(joined.y_cavity_1.mean()), 4),
              "q42_cavity2_rate": round(float(joined.y_cavity_2.mean()), 4),
              "q42_multi_type_shots": int((joined.defect_type_count >= 2).sum()),
              "m41_rows": len(m), "m41_warmup_rows": int(warm.sum()),
              "m41_warmup_episodes": int(m.episode_id.dropna().nunique()),
              "m41_gate_eligible": int(m.gate_eligible.sum()),
              "m41_observable_warmup_rows": int((warm & m.gate_eligible).sum()),
              "m41_observable_episodes": int(m.loc[warm & m.gate_eligible, "episode_id"].nunique()),
              "runs": {int(r): {"q42": int((joined.run_id == r).sum()), "m41": int((m.run_id == r).sum()),
                                "defect_rate": round(float(joined.loc[joined.run_id == r, "y_defect"].mean()), 4),
                                "product_type": int(joined.loc[joined.run_id == r, "Product_Type"].iloc[0])}
                       for r in sorted(joined.run_id.unique())},
              "p40_fail_rate": round(float(p.y_defect.mean()), 4)}
    report.pop("target_columns")
    (paths.TABLES / "prepare_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
