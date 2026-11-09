"""Error-injection evaluation over saved agent runs.

Rule mutations (typed numbers, fabricated or post-as-of evidence, missing citations) are checked by the
code verifier at no API cost. With --semantic, direction-flipped sentences are sent to the semantic judge
(one Claude call per mutant) and the original memo is judged too, so false alarms are counted.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gmia.agent.inject import RULE_EXPECTED, meaning_mutants, registry_from_json, rule_mutants  # noqa: E402
from gmia.agent.memo import allowed_numbers, verify  # noqa: E402
from gmia.agent.sources import PROJECT_ROOT, load_observations  # noqa: E402
from gmia.utils.env import load_dotenv  # noqa: E402

RUNS = PROJECT_ROOT / "data" / "agent" / "runs"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="*", help="run folder names (default: all accepted runs)")
    parser.add_argument("--semantic", action="store_true", help="also run the semantic judge (uses the API)")
    args = parser.parse_args()
    folders = [RUNS / name for name in args.runs] if args.runs else sorted(p for p in RUNS.glob("*") if p.is_dir())
    data = load_observations()
    total, caught, by_code = Counter(), Counter(), {}
    semantic = Counter()
    client = None
    if args.semantic:
        import anthropic
        from gmia.agent.agent import judge
        load_dotenv()
        client = anthropic.Anthropic()
    for folder in folders:
        record = json.loads((folder / "run.json").read_text(encoding="utf-8"))
        if record.get("status") != "accepted":
            continue
        memo, registry = record["memo"], registry_from_json(record["registry"])
        as_of = datetime.fromisoformat(record["as_of_utc"])
        allowed = allowed_numbers(record["question"], [c["input"] for c in record["tool_calls"] if c.get("ok")])
        baseline = verify(memo, registry, as_of, allowed)
        if baseline:
            print(f"{folder.name}: original memo already has violations; skipped")
            continue
        for name, _, mutant, reg in rule_mutants(memo, registry, data, as_of):
            codes = {v["code"] for v in verify(mutant, reg, as_of, allowed)}
            total[name] += 1
            caught[name] += RULE_EXPECTED[name] in codes
            by_code.setdefault(name, Counter()).update(codes)
        if client is not None:
            results, _ = judge(client, memo, registry)
            semantic["original_sentences"] += len(results)
            semantic["false_alarms"] += sum(r["verdict"] != "supported" for r in results)
            for index, mutant in meaning_mutants(memo):
                results, _ = judge(client, mutant, registry)
                verdict = next((r["verdict"] for r in results if r["index"] == index), "missing")
                semantic["flips"] += 1
                semantic["flips_caught"] += verdict != "supported"
    print("rule mutations (code verifier):")
    for name in RULE_EXPECTED:
        if total[name]:
            print(f"  {name}: {caught[name]}/{total[name]} caught")
    all_total, all_caught = sum(total.values()), sum(caught.values())
    if all_total:
        print(f"  overall: {all_caught}/{all_total} = {all_caught / all_total:.1%}")
    if client is not None:
        print("meaning mutations (semantic judge):", dict(semantic))


if __name__ == "__main__":
    main()
