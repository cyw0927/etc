"""Fetch new immutable snapshots of the agent's official sources (U.S. Treasury, Federal Reserve H.10)."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gmia.agent.sources import fetch_h10_krw, fetch_treasury, load_observations  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-year", type=int, default=2003, help="first Treasury year (real yields start 2003)")
    args = parser.parse_args()
    print("treasury:", fetch_treasury(args.first_year, datetime.now(timezone.utc).year).name)
    print("h10_krw:", fetch_h10_krw().name)
    for key, rows in load_observations().items():
        print(f"{key}: {len(rows)} rows, {rows[0].obs_date} .. {rows[-1].obs_date}")


if __name__ == "__main__":
    main()
