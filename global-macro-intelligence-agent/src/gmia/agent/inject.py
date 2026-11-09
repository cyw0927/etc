"""Error injection: corrupt an accepted memo in known ways and measure what the verifiers catch.

Rule mutations must be caught by the code verifier. Meaning mutations (a direction word flipped) keep
every rule intact, so only the semantic judge can catch them.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime

from gmia.agent.memo import SLOT
from gmia.agent.sources import SERIES
from gmia.agent.tools import Evidence, EvidenceRegistry, format_value

RULE_EXPECTED = {
    "typed_wrong_number": "typed_number",
    "typed_true_number": "typed_number",
    "fabricated_id": "unknown_evidence",
    "future_evidence": "after_as_of",
    "dropped_citation": "uncited_claim",
    "slot_not_listed": "slot_not_cited",
}

FLIPS = [("상승", "하락"), ("하락", "상승"), ("올랐", "내렸"), ("내렸", "올랐"), ("높", "낮"), ("낮", "높"),
         ("증가", "감소"), ("감소", "증가"), ("강세", "약세"), ("약세", "강세"), ("웃돌", "밑돌"), ("밑돌", "웃돌")]


def _first_slot(text: str) -> re.Match | None:
    return next((m for m in SLOT.finditer(text) if m.group(1) == "ev"), None)


def _future_observation(registry: dict[str, Evidence], data: dict, as_of_utc: datetime) -> Evidence | None:
    for series_id in SERIES:
        later = [o for o in data.get(series_id, []) if o.available_utc > as_of_utc]
        if later:
            scratch = EvidenceRegistry()
            evidence_id = scratch.observation(later[0])
            return scratch.items[evidence_id]
    return None


def rule_mutants(memo: dict, registry: dict[str, Evidence], data: dict, as_of_utc: datetime):
    """Yield (mutation, sentence_index, memo, registry) for every applicable rule mutation."""
    future = _future_observation(registry, data, as_of_utc)
    for i, sentence in enumerate(memo["sentences"]):
        match = _first_slot(sentence["text"])
        if match is not None and match.group(2) in registry:
            item = registry[match.group(2)]
            start, end = match.span()
            for name, typed in (("typed_wrong_number", format_value(item.value * 1.1 + 1, item.unit)),
                                ("typed_true_number", format_value(item.value, item.unit))):
                m = copy.deepcopy(memo)
                m["sentences"][i]["text"] = sentence["text"][:start] + typed + sentence["text"][end:]
                yield name, i, m, registry
            m = copy.deepcopy(memo)
            fake = "obs:USDKRW:2099-01-01"
            m["sentences"][i]["text"] = sentence["text"][:start] + "{{ev:" + fake + "}}" + sentence["text"][end:]
            m["sentences"][i]["evidence_ids"] = [fake if e == match.group(2) else e for e in sentence["evidence_ids"]]
            yield "fabricated_id", i, m, registry
            if future is not None:
                m = copy.deepcopy(memo)
                m["sentences"][i]["text"] = (sentence["text"][:start] + "{{ev:" + future.evidence_id + "}}"
                                             + sentence["text"][end:])
                m["sentences"][i]["evidence_ids"] = [future.evidence_id if e == match.group(2) else e
                                                     for e in sentence["evidence_ids"]]
                yield "future_evidence", i, m, {**registry, future.evidence_id: future}
            if len(sentence["evidence_ids"]) > 0:
                m = copy.deepcopy(memo)
                m["sentences"][i]["evidence_ids"] = [e for e in sentence["evidence_ids"] if e != match.group(2)]
                yield "slot_not_listed", i, m, registry
        if sentence["kind"] in ("fact", "interpretation") and sentence["evidence_ids"]:
            m = copy.deepcopy(memo)
            m["sentences"][i]["evidence_ids"] = []
            m["sentences"][i]["text"] = SLOT.sub("", sentence["text"])
            yield "dropped_citation", i, m, registry


def meaning_mutants(memo: dict):
    """Yield (sentence_index, memo) with one direction word flipped in one cited sentence."""
    for i, sentence in enumerate(memo["sentences"]):
        if sentence["kind"] == "caveat" or not sentence["evidence_ids"]:
            continue
        for old, new in FLIPS:
            if old in sentence["text"]:
                m = copy.deepcopy(memo)
                m["sentences"][i]["text"] = sentence["text"].replace(old, new, 1)
                yield i, m
                break


def registry_from_json(raw: dict) -> dict[str, Evidence]:
    return {key: Evidence(**value) for key, value in raw.items()}
