import argparse
from pathlib import Path

from .data import validate


def main():
    parser = argparse.ArgumentParser(description="CastGuard reproducible experiment gate")
    parser.add_argument("command", choices=["validate", "verify", "run", "summarize", "rebuild-check", "all"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path("configs/oct02.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/oct02"))
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    config_path = args.config if args.config.is_absolute() else root / args.config
    output = args.output if args.output.is_absolute() else root / args.output
    if args.command == "validate":
        print(f"Data checks passed: {len(validate(root))}")
    if args.command == "verify":
        from .verify import verify_delivery
        print(verify_delivery(root, output))
    if args.command in ["rebuild-check", "all"]:
        from .rebuild import rebuild_check
        if args.command == "all":
            from .storage import tracked_stage
            with tracked_stage(output, "rebuilding"):
                rebuild_check(root, output)
        else:
            rebuild_check(root, output)
    if args.command in ["run", "all"]:
        from .experiment import run
        run(root, config_path, output, args.jobs)
    if args.command in ["summarize", "all"]:
        from .report import summarize
        summarize(root, output)


if __name__ == "__main__":
    main()
