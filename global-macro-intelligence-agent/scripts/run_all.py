"""Full pipeline: (optionally) fetch data, evaluate all models walk-forward, write forecasts and report.

Usage:
  python scripts/run_all.py              # fetch fresh data, then evaluate and forecast
  python scripts/run_all.py --no-fetch   # reuse data already in data/raw
"""

from __future__ import annotations

import argparse
import sys
import warnings

from gmia.config import load_config
from gmia.data.collect import collect_all
from gmia.pipeline import run
from gmia.report import console_summary
from gmia.utils.env import load_dotenv


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--no-fetch", action="store_true", help="reuse stored data")
    args = ap.parse_args()
    warnings.filterwarnings("ignore", category=UserWarning)
    load_dotenv()
    cfg = load_config(args.config)
    if not args.no_fetch:
        summary = collect_all(cfg)
        if summary["failures"]:
            print(f"WARNING: {len(summary['failures'])} source(s) failed; continuing with available data only.")
    result = run(cfg)
    print("\n" + console_summary(result["forecasts"]))
    print(f"\nReport: {result['out_dir'] / 'report.md'}")
    print(result["run_meta"]["disclaimer"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
