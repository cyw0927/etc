"""Agent loop: Claude plans and calls tools; the harness fixes as-of, runs tools, checks and judges the memo.

Roles in this prototype: the analyst (Claude with tools) decomposes the question and writes the memo; the
rule verifier (code) rejects typed numbers, unknown or post-as-of evidence and uncited claims and sends
the memo back at most `max_repairs` times; the semantic judge (a second Claude call) checks that each
claim says what its evidence says.
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from gmia.agent.memo import SUBMIT_TOOL, allowed_numbers, fill, render, verify
from gmia.agent.tools import HANDLERS, TOOL_SCHEMAS, ToolContext, ToolError

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = """You are a macro research analyst for an institutional investor. You answer one question
as of a fixed time (as-of) using only the tools provided. The tools see only data that was available at
as-of; you have no other data, and your own memory of later events must not be used.

How to work:
- Start with list_series. Break the question into what must be measured, then call tools for it.
- Compare any historical pattern with its all-days baseline before saying it means anything.
- If evidence is missing, too thin, or the question needs data the tools do not have, say so in
  cannot_say instead of guessing. Historical associations are not causal effects; say "historically".
- Finish by calling submit_memo. Write the memo in Korean.

Number rule (checked by code): never type a number from data. Write {{ev:<evidence_id>}} where a value
belongs and {{date:<evidence_id>}} where an observation date belongs, and list every id you use in that
sentence's evidence_ids. Numbers from the question and from your own tool arguments (windows, horizons,
thresholds) may be typed. kind is "fact" for what evidence shows, "interpretation" for your reading of
it, "caveat" for limits. fact and interpretation sentences need evidence_ids.
Keep the memo short: 5 to 9 sentences."""

JUDGE_SYSTEM = """You check a research memo against its evidence. For each numbered sentence you get the
rendered text and the evidence it cites (label = value). Return "supported" only if every claim in the
sentence (direction, comparison, size words like "large" or "most", time references) follows from the
cited evidence alone. An interpretation is supported if it is a reasonable, hedged reading and does not
state causation as fact. Return "unsupported" if any claim contradicts or goes beyond the evidence, and
"unclear" if the evidence cannot decide. Give a one-sentence reason in Korean."""

JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["results"],
    "properties": {"results": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["index", "verdict", "reason"],
        "properties": {"index": {"type": "integer"},
                       "verdict": {"type": "string", "enum": ["supported", "unsupported", "unclear"]},
                       "reason": {"type": "string"}}}}},
}


def _call(client, *, model: str, effort: str, output_format: dict | None = None, **kwargs):
    output_config = {"effort": effort}
    if output_format is not None:
        output_config["format"] = output_format
    return client.beta.messages.create(model=model, max_tokens=16000, thinking={"type": "adaptive"},
                                       betas=[FALLBACK_BETA], fallbacks="default",
                                       output_config=output_config, **kwargs)


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    return {"model": getattr(response, "model", None), "stop_reason": getattr(response, "stop_reason", None),
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0}


def _ids(value) -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "evidence_id" and isinstance(item, str):
                found.append(item)
            else:
                found += _ids(item)
    elif isinstance(value, list):
        for item in value:
            found += _ids(item)
    return found


def judge(client, memo: dict, registry: dict, *, model: str = MODEL) -> tuple[list[dict], dict]:
    items = []
    for i, sentence in enumerate(memo["sentences"]):
        if sentence["kind"] == "caveat" or not sentence["evidence_ids"]:
            continue
        evidence = [registry[e].describe() for e in sentence["evidence_ids"] if e in registry]
        items.append(f"[{i}] ({sentence['kind']}) {fill(sentence['text'], registry)}\n    근거: " + " | ".join(evidence))
    if not items:
        return [], {}
    response = _call(client, model=model, effort="medium",
                     output_format={"type": "json_schema", "schema": JUDGE_SCHEMA},
                     system=JUDGE_SYSTEM, messages=[{"role": "user", "content": "\n".join(items)}])
    if response.stop_reason == "refusal":
        return [{"index": -1, "verdict": "unclear", "reason": "judge refused"}], _usage(response)
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)["results"], _usage(response)


def run(question: str, as_of_utc: datetime, data: dict, client, *, model: str = MODEL, effort: str = "high",
        max_turns: int = 16, max_repairs: int = 2, semantic: bool = True) -> dict:
    ctx = ToolContext(as_of_utc, data)
    tools = TOOL_SCHEMAS + [SUBMIT_TOOL]
    messages = [{"role": "user", "content": f"기준 시각(as-of, UTC): {as_of_utc.isoformat()}\n질문: {question}"}]
    record = {"question": question, "as_of_utc": as_of_utc.isoformat(), "model": model, "status": "incomplete",
              "calls": [], "tool_calls": [], "submissions": [], "memo": None}
    tool_inputs: list[dict] = []
    repairs = nudges = 0
    started = time.monotonic()
    for _ in range(max_turns):
        response = _call(client, model=model, effort=effort, system=SYSTEM, tools=tools, messages=messages)
        record["calls"].append(_usage(response))
        if response.stop_reason == "refusal":
            record["status"] = "refused"
            break
        messages.append({"role": "assistant", "content": response.content})
        uses = [block for block in response.content if block.type == "tool_use"]
        if not uses:
            if response.stop_reason == "pause_turn":
                continue
            if nudges >= 2:
                record["status"] = "no_memo"
                break
            nudges += 1
            messages.append({"role": "user", "content": "submit_memo 도구로 최종 메모를 제출하세요."})
            continue
        results = []
        for block in uses:
            args = dict(block.input)
            if block.name == "submit_memo":
                violations = verify(args, ctx.registry.items, as_of_utc, allowed_numbers(question, tool_inputs))
                record["submissions"].append({"memo": args, "violations": violations})
                if violations and repairs < max_repairs:
                    repairs += 1
                    results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                    "content": "메모가 자동 검증에 실패했습니다. 고쳐서 다시 제출하세요:\n"
                                               + json.dumps(violations, ensure_ascii=False)})
                else:
                    record["memo"] = args
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": "accepted" if not violations else "recorded with violations"})
                continue
            handler = HANDLERS.get(block.name)
            entry = {"name": block.name, "input": args}
            try:
                if handler is None:
                    raise ToolError(f"unknown tool {block.name}")
                output = handler(ctx, **args)
                tool_inputs.append(args)
                entry.update(ok=True, evidence_ids=sorted(set(_ids(output))))
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(output, ensure_ascii=False, default=str)})
            except (ToolError, TypeError, ValueError) as exc:
                entry.update(ok=False, error=str(exc))
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                "content": str(exc)})
            record["tool_calls"].append(entry)
        messages.append({"role": "user", "content": results})
        if record["memo"] is not None:
            record["status"] = "accepted"
            break
    registry = ctx.registry.items
    final = record["submissions"][-1]["violations"] if record["submissions"] else []
    verification = {"violations": final, "repairs": repairs}
    if record["memo"] is not None and semantic:
        results, usage = judge(client, record["memo"], registry, model=model)
        verification["semantic"] = results
        if usage:
            record["calls"].append({**usage, "role": "judge"})
        bad = [r for r in results if r["verdict"] != "supported"]
        verification["semantic_summary"] = (f"{len(results)}문장 중 {len(results) - len(bad)}문장 근거 일치"
                                            + (f", {len(bad)}문장 확인 필요" if bad else ""))
    record["verification"] = verification
    record["audit"] = {"evidence_items": len(registry),
                       "after_as_of": [k for k, v in registry.items()
                                       if datetime.fromisoformat(v.available_utc) > as_of_utc]}
    record["seconds"] = round(time.monotonic() - started, 1)
    record["usage_total"] = {key: sum(c.get(key, 0) for c in record["calls"])
                             for key in ("input_tokens", "output_tokens", "cache_read_input_tokens")}
    record["registry"] = ctx.registry.to_json()
    if record["memo"] is not None:
        record["markdown"] = render(record["memo"], registry, as_of_utc, question, verification)
    return record
