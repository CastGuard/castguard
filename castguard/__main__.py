"""실행: python -m castguard all   (단계별: env | prepare | train | analyze | report)"""
import argparse
import json
import time

from . import paths
from .config import load_config


def main():
    ap = argparse.ArgumentParser(description="CastGuard 재현 파이프라인")
    ap.add_argument("command", choices=["env", "prepare", "train", "analyze", "report", "all"])
    ap.add_argument("--jobs", type=int, default=None, help="병렬 작업 수 (기본: CPU 코어 수)")
    ap.add_argument("--quick", action="store_true", help="seed 1개로 빠른 점검 (보고용 아님)")
    ap.add_argument("--config", default=str(paths.CONFIG))
    a = ap.parse_args()
    cfg = load_config(a.config)
    if a.quick:
        cfg["seeds"] = cfg["seeds"][:1]
    t0 = time.time()
    if a.command in ("env", "all"):
        from .env import check
        print(json.dumps(check(), ensure_ascii=False, indent=2))
    if a.command in ("prepare", "all"):
        from .prepare import run
        r = run(cfg)
        print(f"[전처리] #42 {r['q42_raw_rows']}→{r['q42_rows']} Shot (중복 {r['q42_duplicates_removed']} 제거), "
              f"조인 {r['join_matched']}개·공정값 {r['join_equal_values']}/{r['join_total_values']} 일치, "
              f"#41 예열 {r['m41_warmup_rows']}행·{r['m41_warmup_episodes']}에피소드")
    if a.command in ("train", "all"):
        from .train import run
        run(cfg, a.jobs)
    if a.command in ("analyze", "all"):
        from .analysis import run
        run(cfg)
    if a.command in ("report", "all"):
        from .report import run
        run(cfg)
    print(f"완료 ({time.time() - t0:.0f}초)")


if __name__ == "__main__":
    main()
