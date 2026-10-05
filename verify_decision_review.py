"""Verify all frozen adapters against saved predictions; never train or select models."""
from pathlib import Path
import argparse
import json
import shutil
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parent))
from castguard.decision_review import DecisionReviewer, PROCESS, QUALITY, GATE, SCHEMA, read_json, digest
from prepare_decision_review import packet, clean, write_new, ordered_run


def process_packet(row, timeline):
    run=ordered_run(timeline,row.run_id)
    seq=int(np.flatnonzero(run.row_id.to_numpy()==row.row_id)[0])
    key=f"historical-run-{int(row.run_id)}"
    return {"record_id":str(row.row_id),"observation":{"run_key":key,"sequence":seq},
        "measurements":{name:clean(row[name]) for name in PROCESS},
        "history":[{"run_key":key,"sequence":i,"Cycle_Time":clean(run.iloc[i].Cycle_Time)}
                   for i in range(max(0,seq-5),seq)]}


def verify(root,out,config=None,examples=None):
    root,out=Path(root).resolve(),Path(out).resolve()
    if out.exists():raise FileExistsError("Verification output must be a new path")
    out.mkdir(parents=True)
    cfg_path=Path(config) if config else root/"configs/decision_review.json"
    cfg=read_json(cfg_path)
    q=pd.read_parquet(root/"data/processed/joined.parquet",columns=list(dict.fromkeys(
        ["row_id","run_id","Shot","source_row"]+QUALITY)))
    m=pd.read_parquet(root/"data/processed/m41_timeline.parquet",columns=list(dict.fromkeys(
        ["row_id","run_id","Shot","source_row"]+GATE)))
    expected=pd.read_parquet(root/"reports/oct03_queue/candidate_predictions.parquet",
        columns=["row_id","fold","task","model","seed","stage","probability"])
    checks=[]
    equivalence_groups=[]
    def semantic_rows(result):
        return {r['record_id']:{k:v for k,v in r.items() if k!='record_index'} for r in result['records']}
    def no_tables(*args,**kwargs):raise AssertionError("Inference attempted to read a table")
    for checkpoint, profile in cfg["checkpoints"].items():
        reviewer=DecisionReviewer(root,checkpoint,config=cfg_path)
        for task,data in [("quality",q),("gate",m)]:
            d=profile[task]
            subset=expected[(expected.fold.astype(str)==d["fold"]) & expected.task.eq(task)
                & expected.model.eq(d["model"]) & expected.seed.eq(d["seed"])]
            merged=subset.merge(data,on="row_id",validate="one_to_one")
            complete=merged.dropna(subset=QUALITY if task=="quality" else PROCESS).sort_values("source_row").head(3)
            assert len(complete)==3,(checkpoint,task)
            packets=[]
            individual={}
            for _,row in complete.iterrows():
                rec=packet(row,m) if task=="quality" else process_packet(row,m)
                packets.append(rec)
                with patch.object(pd,"read_parquet",no_tables),patch.object(pd,"read_csv",no_tables):
                    result=reviewer.review({"schema_version":SCHEMA,"records":[rec]})["records"][0]
                individual[result['record_id']]={k:v for k,v in result.items() if k!='record_index'}
                stage=result["quality" if task=="quality" else "equipment_state"]
                assert stage["status"]=="scored",(checkpoint,task,stage)
                error=abs(stage["score"]-row.probability)
                assert error<=1e-6,(checkpoint,task,error)
                e=stage["explanation"]
                assert e["margin_error"]<=1e-6 and e["score_error"]<=1e-6
                checks.append({"checkpoint":checkpoint,"task":task,"row_id":row.row_id,
                    "saved_prediction_error":error,"margin_error":e["margin_error"],
                    "score_reconstruction_error":e["score_error"]})
            with patch.object(pd,"read_parquet",no_tables),patch.object(pd,"read_csv",no_tables):
                for subset in [packets,packets[::-1],packets[::2]]:
                    result=semantic_rows(reviewer.review({"schema_version":SCHEMA,"records":subset}))
                    assert result=={r['record_id']:individual[r['record_id']] for r in subset}
            equivalence_groups.append({'checkpoint':checkpoint,'task':task,'records':len(packets),'full_reverse_partial_vs_single_identical':True})
    # Actually run with no raw/processed/label tables in the runtime root.
    isolated=out/"label_free_runtime"
    (isolated/"configs").mkdir(parents=True)
    shutil.copyfile(cfg_path,isolated/"configs/decision_review.json")
    for d in cfg["checkpoints"]["queue-fold2-seed17"].values():
        dest=isolated/d["path"];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/d["path"],dest)
        assert digest(dest)==d["sha256"]
    inputs=read_json(examples or root/"examples/decision_review/shots.json")
    reviewer=DecisionReviewer(isolated)
    baseline=reviewer.review(inputs)
    label_file=isolated/"withheld_labels.json"
    variants=[[],[{"record_id":r["record_id"],"y_defect":0} for r in inputs["records"]],
                 [{"record_id":r["record_id"],"y_defect":1} for r in reversed(inputs["records"])]]
    for labels in variants:
        label_file.write_text(json.dumps(labels),encoding="utf-8")
        with patch.object(pd,"read_parquet",no_tables),patch.object(pd,"read_csv",no_tables):
            assert reviewer.review(inputs)==baseline
    assert not (isolated/"data").exists()
    summary={"scope":"functional replay of existing frozen models; not new generalization or performance evidence",
        "checkpoints":len(cfg["checkpoints"]),"saved_prediction_checks":len(checks),
        "max_saved_prediction_error":max(c["saved_prediction_error"] for c in checks),
        "max_margin_error":max(c["margin_error"] for c in checks),
        "max_score_reconstruction_error":max(c["score_reconstruction_error"] for c in checks),
        "inference_without_raw_processed_or_labels":True,"withheld_label_variants_invariant":len(variants)+1,
        "all_records_retained":len(baseline["records"]),
        "training_or_selection_performed":False,"checks":checks,
        "batch_single_equivalence_groups":equivalence_groups,
        "config_sha256":digest(cfg_path),"source_sha256":digest(Path(__file__).parent/"castguard/decision_review.py")}
    write_new(out/"verification.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='checks'},ensure_ascii=False,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parent)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--config",type=Path)
    p.add_argument("--examples",type=Path)
    a=p.parse_args();verify(a.root,a.output,a.config,a.examples)
