"""Day 1 QC and Day 2/3 research commands. Holdout observations never rendered."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.error

from .access import HoldoutLocked, load_config, load_research, log_access
from .data import acquire, build, validate_processed, write_json
from .validation import ContractError
from .research import run_signals, run_backtest
from .validation_run import run_validation, run_oos, reproduce_or_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AlphaLab Sprint v1 — Day 1/2/3")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("data")
    data.add_argument("action", choices=["fetch", "import", "build"])
    data.add_argument("--from-dir", type=Path)
    commands.add_parser("validate")
    preview = commands.add_parser("preview", help="permitted-view coverage only; no signals")
    preview.add_argument("--start", default="1998-01")
    preview.add_argument("--end", default="2023-12")
    research = commands.add_parser("research", help="Research signals or backtest, through 2017 only")
    research.add_argument("--stage", choices=["signals", "backtest", "validation"], required=True)
    research.add_argument("--end")
    oos = commands.add_parser("oos")
    oos.add_argument("--authorization", type=Path)
    for name in ["reproduce", "report"]:
        command = commands.add_parser(name)
        command.add_argument("--stage", choices=["validation", "oos"], default="validation")
        command.add_argument("--authorization", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    qc_active = False
    try:
        config = load_config(root)
        if args.command == "research":
            end = args.end or ("2023-12" if args.stage == "validation" else "2017-12")
            result = {"signals": run_signals, "backtest": run_backtest, "validation": run_validation}[args.stage](root, end=end)
        elif args.command == "oos":
            result = run_oos(root, args.authorization)
        elif args.command in {"reproduce", "report"}:
            result = reproduce_or_report(root, args.stage, args.authorization, report=args.command == "report")
        elif args.command == "data" and args.action in {"fetch", "import"}:
            if args.action == "import" and args.from_dir is None:
                raise ContractError("manual_import_requires_from_dir")
            qc_active = True
            log_access(root, "structural_qc", "BEGIN")
            result = acquire(root, args.from_dir if args.action == "import" else None)
        elif args.command == "preview":
            industries, factors = load_research(root, args.start, args.end)
            result = {"status": "PASS", "range": [str(industries["month"].min()), str(industries["month"].max())],
                      "industry_rows": len(industries), "factor_rows": len(factors), "holdout_status": "LOCKED"}
        else:
            qc_active = True
            log_access(root, "structural_qc", "BEGIN")
            result = build(root, config) if args.command == "data" else validate_processed(root, config)
            write_json(root / "reports/day1_qc.json", result)
        if qc_active:
            log_access(root, "structural_qc", result["status"])
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except (ContractError, HoldoutLocked, OSError, ValueError, KeyError, urllib.error.URLError) as error:
        if qc_active:
            log_access(root, "structural_qc", "FAIL")
        # Only our controlled identifiers are printable; vendor errors may contain rows.
        rule = str(error) if isinstance(error, (ContractError, HoldoutLocked)) else type(error).__name__
        result = {"status": "FAIL", "rule": rule}
        if qc_active:
            write_json(root / "reports/day1_qc.json", result)
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
