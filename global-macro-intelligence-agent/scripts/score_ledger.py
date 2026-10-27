"""Score previously issued forecasts ONLY after their target h-bar outcome has matured.

Usage:
  python scripts/score_ledger.py
  python scripts/score_ledger.py --config configs/default.yaml

Refresh market data first (python scripts/fetch_data.py). This command never downloads
data itself, changes predictions, or retrospectively inserts historical predictions.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from gmia.config import asset_specs, load_config
from gmia.data.market import load_asset
from gmia.evaluation.forward import (
    ASSETS, forward_significance, ledger_path, read_scores, score_pending,
)
from gmia.utils.env import load_dotenv


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    load_dotenv()
    cfg = load_config(args.config)
    path = ledger_path(cfg)
    if not path.exists():
        print(f"No forward-test ledger at {path}. Run scripts/run_all.py first.")
        return 1

    prices, metas = {}, {}
    specs = asset_specs(cfg)
    for asset in ASSETS:
        if asset not in specs:
            continue
        loaded = load_asset(cfg["data"]["raw_dir"], asset)
        if loaded is not None:
            prices[asset], metas[asset] = loaded

    results = score_pending(path, cfg, prices, metas, now_utc=datetime.now(timezone.utc))
    scored = read_scores(path)
    significance = forward_significance(scored)
    csv_path = path.parent / "forward_significance.csv"
    significance.to_csv(csv_path, index=False)

    print("GMIA v0.4 point-in-time forward-test ledger")
    for key, value in results.items():
        print(f"  {key}: {value}")
    print(f"  scored observations (all past runs): {len(scored)}")
    print(f"  eligible comparisons: {int(significance['enough_data'].sum())} / {len(significance)}")
    print(f"  supported candidates: {int(significance['supported'].sum())}")
    print(f"  statistical summary: {csv_path}")
    if not significance["enough_data"].any():
        print("표본 부족 — 사전 등록 기준(쌍 500개, 540일)을 충족하는 후보가 아직 없습니다.")
    print("Historical holdout results do NOT count as new forward observations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
