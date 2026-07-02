"""CLI: python -m ssa.triage"""

from __future__ import annotations

import argparse
import logging

from .engine import TriageError
from .runner import run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ssa Phase-2 triage (hosted Gemini, PAID)")
    parser.add_argument("--config", default="config.json", help="path to config.json")
    parser.add_argument("--limit", type=int, default=0,
                        help="triage at most N articles (0 = all untriaged)")
    parser.add_argument("--dry-run", action="store_true",
                        help="no API calls: report counts + estimated cost")
    parser.add_argument("--input", default=None,
                        help="override the articles glob (default: <output_dir>/articles_*.jsonl)")
    parser.add_argument("--quiet", action="store_true", help="warnings only")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        summary = run(
            config_path=args.config,
            limit=args.limit,
            dry_run=args.dry_run,
            input_glob=args.input,
        )
    except TriageError as exc:
        print(f"triage aborted: {exc}")
        return 2
    if summary["dry_run"]:
        return 0
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
