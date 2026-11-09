"""Ask the research agent one question at a fixed as-of time; writes memo.md and run.json.

A bare date as --as-of means 09:00 Korea time on that date. Uses the latest local snapshots
(scripts/agent_fetch.py) and ANTHROPIC_API_KEY from the environment or the git-ignored .env file.
"""
import argparse
import json
import sys
import uuid
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic  # noqa: E402

from gmia.agent.agent import MODEL, run  # noqa: E402
from gmia.agent.sources import PROJECT_ROOT, load_observations  # noqa: E402
from gmia.utils.env import load_dotenv  # noqa: E402

RUNS = PROJECT_ROOT / "data" / "agent" / "runs"


def parse_as_of(text: str | None) -> datetime:
    if not text:
        return datetime.now(timezone.utc)
    if len(text) == 10:
        day = datetime.strptime(text, "%Y-%m-%d").date()
        return datetime.combine(day, time(9, 0), ZoneInfo("Asia/Seoul")).astimezone(timezone.utc)
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise SystemExit("--as-of datetime needs a timezone, e.g. 2026-10-30T09:00+09:00")
    return value.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--as-of", dest="as_of")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--no-semantic", action="store_true", help="skip the semantic judge call")
    args = parser.parse_args()
    load_dotenv()
    as_of = parse_as_of(args.as_of)
    record = run(args.question, as_of, load_observations(), anthropic.Anthropic(), model=args.model,
                 effort=args.effort, semantic=not args.no_semantic)
    folder = RUNS / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if record.get("markdown"):
        (folder / "memo.md").write_text(record["markdown"], encoding="utf-8")
        print(record["markdown"])
    print(json.dumps({"run": folder.name, "status": record["status"], "seconds": record["seconds"],
                      "tool_calls": len(record["tool_calls"]), "repairs": record["verification"]["repairs"],
                      "violations": len(record["verification"]["violations"]),
                      "semantic": record["verification"].get("semantic_summary"),
                      "after_as_of": len(record["audit"]["after_as_of"]), "usage": record["usage_total"],
                      "models": sorted({c["model"] for c in record["calls"] if c.get("model")})},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
