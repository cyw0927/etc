"""Memo contract, deterministic verifier and renderer.

The writer never types a number: it writes {{ev:<id>}} for a value and {{date:<id>}} for an observation
date, and the renderer fills them from the evidence registry. The verifier rejects typed numbers that did
not come from the question or the agent's own tool arguments, unknown or post-as-of evidence, and
claims without evidence.
"""

from __future__ import annotations

import re
from datetime import datetime

from gmia.agent.tools import Evidence, format_value

SLOT = re.compile(r"\{\{(ev|date):([^{}\s]+)\}\}")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
CITED_KINDS = ("fact", "interpretation")

MEMO_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["title", "sentences", "cannot_say"],
    "properties": {
        "title": {"type": "string"},
        "sentences": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "kind", "evidence_ids"],
            "properties": {"text": {"type": "string"},
                           "kind": {"type": "string", "enum": ["fact", "interpretation", "caveat"]},
                           "evidence_ids": {"type": "array", "items": {"type": "string"}}}}},
        "cannot_say": {"type": "array", "items": {"type": "string"}},
    },
}

SUBMIT_TOOL = {
    "name": "submit_memo", "strict": True,
    "description": "Submit the final research memo. Write every number as {{ev:<evidence_id>}} and every "
                   "observation date as {{date:<evidence_id>}}; list each sentence's evidence_ids. The memo "
                   "is checked automatically and returned with violations if it fails.",
    "input_schema": MEMO_SCHEMA,
}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUMBER.findall(text)}


def allowed_numbers(question: str, tool_inputs: list[dict]) -> set[str]:
    """Numbers the writer may type: those in the question and its own tool arguments (windows, horizons)."""
    allowed = _numbers(question)
    for args in tool_inputs:
        for value in args.values():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                allowed.add(f"{value:g}")
                allowed.add(str(int(value)) if float(value).is_integer() else f"{value:g}")
    return allowed


def verify(memo: dict, registry: dict[str, Evidence], as_of_utc: datetime, allowed: set[str]) -> list[dict]:
    violations = []

    def flag(code: str, where: str, detail: str) -> None:
        violations.append({"code": code, "where": where, "detail": detail})

    def check_text(text: str, where: str, cited: list[str] | None) -> None:
        for kind, evidence_id in SLOT.findall(text):
            if evidence_id not in registry:
                flag("unknown_evidence", where, evidence_id)
            elif kind == "date" and registry[evidence_id].kind != "observation":
                flag("date_slot_on_derived", where, evidence_id)
            if cited is not None and evidence_id not in cited:
                flag("slot_not_cited", where, evidence_id)
        rest = SLOT.sub(" ", text)
        if "{{" in rest or "}}" in rest:
            flag("malformed_slot", where, rest)
        for number in sorted(_numbers(rest) - allowed):
            flag("typed_number", where, number)

    check_text(memo.get("title", ""), "title", None)
    for i, sentence in enumerate(memo.get("sentences", [])):
        where = f"sentences[{i}]"
        cited = list(sentence.get("evidence_ids", []))
        check_text(sentence.get("text", ""), where, cited)
        if sentence.get("kind") in CITED_KINDS and not cited:
            flag("uncited_claim", where, sentence.get("text", "")[:80])
        for evidence_id in cited:
            item = registry.get(evidence_id)
            if item is None:
                flag("unknown_evidence", where, evidence_id)
            elif datetime.fromisoformat(item.available_utc) > as_of_utc:
                flag("after_as_of", where, f"{evidence_id} available {item.available_utc}")
    for i, text in enumerate(memo.get("cannot_say", [])):
        check_text(text, f"cannot_say[{i}]", None)
    if not memo.get("sentences"):
        flag("empty_memo", "sentences", "no sentences")
    return violations


def fill(text: str, registry: dict[str, Evidence]) -> str:
    def replace(match: re.Match) -> str:
        kind, evidence_id = match.groups()
        item = registry[evidence_id]
        return item.detail["obs_date"] if kind == "date" else format_value(item.value, item.unit)
    return SLOT.sub(replace, text)


def render(memo: dict, registry: dict[str, Evidence], as_of_utc: datetime, question: str,
           verification: dict) -> str:
    order: list[str] = []
    lines = [f"# {fill(memo['title'], registry)}", "",
             f"- 질문: {question}", f"- 기준 시각(as-of): {as_of_utc.isoformat()}",
             f"- 규칙 검증: {'통과' if not verification['violations'] else '위반 ' + str(len(verification['violations'])) + '건'}"
             f" · 의미 검증: {verification.get('semantic_summary', '실행 안 함')}", ""]
    for sentence in memo["sentences"]:
        marks = []
        for evidence_id in sentence["evidence_ids"]:
            if evidence_id not in order:
                order.append(evidence_id)
            marks.append(str(order.index(evidence_id) + 1))
        tag = {"fact": "", "interpretation": "(해석) ", "caveat": "(유의) "}[sentence["kind"]]
        suffix = f" [{', '.join(marks)}]" if marks else ""
        lines.append(f"- {tag}{fill(sentence['text'], registry)}{suffix}")
    if memo.get("cannot_say"):
        lines += ["", "## 이 기준 시각에 말할 수 없는 것", ""]
        lines += [f"- {fill(text, registry)}" for text in memo["cannot_say"]]
    lines += ["", "## 근거", "", "| # | 근거 | 값 | 출처 | 사용 가능 시각(UTC) | 원본 해시 |", "|---|---|---|---|---|---|"]
    for n, evidence_id in enumerate(order, 1):
        item = registry[evidence_id]
        sha = item.detail.get("file_sha256") or item.detail.get("target_snapshot_sha256", "")
        source = item.source
        if item.detail.get("page_url"):
            source = f"[{item.source}]({item.detail['page_url']})"
        lines.append(f"| {n} | {item.label} | {format_value(item.value, item.unit)} | {source} | "
                     f"{item.available_utc[:16]} | `{sha[:12]}` |")
    return "\n".join(lines) + "\n"
