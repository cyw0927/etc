"""Download and clean all configured market, rate and macro series.

Usage: python scripts/fetch_data.py [--config configs/default.yaml]
"""

from __future__ import annotations

import argparse
import sys

from gmia.config import load_config
from gmia.data.collect import collect_all
from gmia.utils.env import load_dotenv


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    load_dotenv()
    summary = collect_all(load_config(args.config))
    ok = len(summary["market"]) + len(summary["rates"]) + len(summary["macro"])
    print(f"\nCollected {ok} series; {len(summary['failures'])} failure(s).")
    for f in summary["failures"]:
        print(f"  FAILED {f['source']}:{f['id']} -> {f['error']}")
    return 0 if summary["market"] else 1


if __name__ == "__main__":
    sys.exit(main())
