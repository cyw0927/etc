"""Deterministic tools for the research agent; every returned number is an evidence record.

The as-of time is set by the harness, never by the model. A tool can only see observations whose
available time is at or before as-of, and a historical outcome counts only if its end was available too.
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime

from gmia.agent.sources import SERIES, Observation


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: str  # "observation" or "derived"
    label: str
    value: float
    unit: str
    available_utc: str
    source: str
    detail: dict

    def describe(self) -> str:
        return f"{self.label} = {format_value(self.value, self.unit)}"


def format_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "pp":
        return f"{value:+.2f}%p"
    if unit == "pct":
        return f"{value:+.2f}%"
    if unit == "원":
        return f"{value:,.2f}원"
    if unit == "share":
        return f"{value * 100:.0f}%"
    if unit == "count":
        return f"{int(value)}건"
    return f"{value:g}{unit}"


@dataclass
class EvidenceRegistry:
    items: dict[str, Evidence] = field(default_factory=dict)
    _derived: int = 0

    def observation(self, obs: Observation) -> str:
        spec = SERIES[obs.series_id]
        evidence_id = f"obs:{obs.series_id}:{obs.obs_date.isoformat()}"
        if evidence_id not in self.items:
            self.items[evidence_id] = Evidence(
                evidence_id, "observation", f"{spec.label}, {obs.obs_date.isoformat()}", obs.value, spec.unit,
                obs.available_utc.isoformat(), spec.source,
                {"series_id": obs.series_id, "obs_date": obs.obs_date.isoformat(), "page_url": spec.page_url,
                 "availability_rule": spec.availability_rule, "file_sha256": obs.file_sha256,
                 "snapshot": obs.snapshot})
        return evidence_id

    def derived(self, label: str, value: float, unit: str, available: datetime, detail: dict) -> str:
        self._derived += 1
        evidence_id = f"calc:{self._derived}"
        self.items[evidence_id] = Evidence(evidence_id, "derived", label, float(value), unit,
                                           available.isoformat(), "GMIA 계산", detail)
        return evidence_id

    def to_json(self) -> dict:
        return {key: asdict(value) for key, value in self.items.items()}


class ToolError(ValueError):
    """Shown to the model as an error tool result; never a silent fallback."""


@dataclass
class ToolContext:
    as_of_utc: datetime
    data: dict[str, list[Observation]]
    registry: EvidenceRegistry = field(default_factory=EvidenceRegistry)

    def visible(self, series_id: str) -> list[Observation]:
        if series_id not in self.data:
            raise ToolError(f"unknown series_id {series_id!r}; call list_series")
        return [o for o in self.data[series_id] if o.available_utc <= self.as_of_utc]


def _change(spec_unit: str, start: float, end: float) -> float:
    return end - start if spec_unit == "pp" else (end / start - 1.0) * 100.0


def list_series(ctx: ToolContext) -> dict:
    out = []
    for spec in SERIES.values():
        rows = ctx.visible(spec.series_id)
        out.append({"series_id": spec.series_id, "label": spec.label, "unit": spec.unit,
                    "change_unit": "%p" if spec.change_unit == "pp" else "%", "source": spec.source,
                    "availability_rule": spec.availability_rule,
                    "first_date": rows[0].obs_date.isoformat() if rows else None,
                    "latest_available_date": rows[-1].obs_date.isoformat() if rows else None})
    return {"as_of_utc": ctx.as_of_utc.isoformat(), "series": out}


def get_latest(ctx: ToolContext, series_id: str, count: int) -> dict:
    rows = ctx.visible(series_id)
    if not rows:
        raise ToolError(f"no {series_id} value was available at {ctx.as_of_utc.isoformat()}")
    count = max(1, min(int(count), 30))
    hidden = [o for o in ctx.data[series_id] if o.available_utc > ctx.as_of_utc]
    return {"series_id": series_id,
            "observations": [{"evidence_id": ctx.registry.observation(o), "date": o.obs_date.isoformat(),
                              "value": o.value, "unit": SERIES[series_id].unit} for o in rows[-count:]],
            "note": (f"{len(hidden)} later observations exist in the snapshot but were not yet available "
                     "at as-of; they are withheld") if hidden else "no withheld observations"}


def get_change(ctx: ToolContext, series_id: str, window: int) -> dict:
    rows = ctx.visible(series_id)
    window = int(window)
    if window < 1 or len(rows) <= window:
        raise ToolError("window must be >= 1 and shorter than the available history")
    spec = SERIES[series_id]
    start, end = rows[-1 - window], rows[-1]
    unit = "pp" if spec.change_unit == "pp" else "pct"
    value = _change(spec.change_unit, start.value, end.value)
    evidence_id = ctx.registry.derived(
        f"{spec.label} {window}개 관측 변화({start.obs_date}→{end.obs_date})", value, unit,
        max(start.available_utc, end.available_utc),
        {"inputs": [ctx.registry.observation(start), ctx.registry.observation(end)], "window_obs": window})
    return {"evidence_id": evidence_id, "series_id": series_id, "window_obs": window,
            "start": {"evidence_id": ctx.registry.observation(start), "date": start.obs_date.isoformat()},
            "end": {"evidence_id": ctx.registry.observation(end), "date": end.obs_date.isoformat()},
            "change": value, "unit": "%p" if unit == "pp" else "%"}


def conditional_outcomes(ctx: ToolContext, condition_series: str, window: int, direction: str,
                         threshold: float, target_series: str, horizon: int) -> dict:
    """Past episodes where the condition series moved by at least threshold over window observations,
    and what the target did over the next horizon observations, against all comparable days.

    Episodes are spaced at least horizon target observations apart so outcomes do not overlap.
    Only episodes whose outcome end was available by as-of are counted.
    """
    if direction not in ("rise", "fall"):
        raise ToolError("direction must be 'rise' or 'fall'")
    window, horizon = int(window), int(horizon)
    if window < 1 or horizon < 1 or threshold < 0:
        raise ToolError("window and horizon must be >= 1 and threshold >= 0")
    cond, target = ctx.visible(condition_series), ctx.visible(target_series)
    c_spec, t_spec = SERIES[condition_series], SERIES[target_series]
    target_index = {o.obs_date: i for i, o in enumerate(target)}
    target_dates = sorted(target_index)

    def outcome_at(day) -> tuple[float, Observation] | None:
        # Last target observation on or before the condition date; strictly no later value as the start.
        pos = bisect.bisect_right(target_dates, day) - 1
        if pos < 0 or pos + horizon >= len(target):
            return None
        start, end = target[pos], target[pos + horizon]
        return _change(t_spec.change_unit, start.value, end.value), end

    episodes, baseline, last_used, last_base = [], [], None, None
    for i in range(window, len(cond)):
        result = outcome_at(cond[i].obs_date)
        if result is None:
            continue
        outcome, end_obs = result
        pos = target_index[end_obs.obs_date] - horizon
        if last_base is None or pos - last_base >= horizon:
            baseline.append(outcome)
            last_base = pos
        move = _change(c_spec.change_unit, cond[i - window].value, cond[i].value)
        hit = move >= threshold if direction == "rise" else move <= -threshold
        if hit and (last_used is None or pos - last_used >= horizon):
            episodes.append((cond[i].obs_date, move, outcome, end_obs))
            last_used = pos
    if len(episodes) < 5:
        raise ToolError(f"only {len(episodes)} non-overlapping episodes; too few to describe")

    def summary(values: list[float]) -> dict:
        ordered = sorted(values)
        q = lambda p: ordered[min(len(ordered) - 1, int(p * (len(ordered) - 1) + 0.5))]  # noqa: E731
        return {"n": len(values), "mean": statistics.fmean(values), "median": statistics.median(values),
                "share_up": sum(v > 0 for v in values) / len(values), "p10": q(0.10), "p90": q(0.90)}

    ep, base = summary([e[2] for e in episodes]), summary(baseline)
    available = max(e[3].available_utc for e in episodes)
    t_unit = "pp" if t_spec.change_unit == "pp" else "pct"
    c_unit = "%p" if c_spec.change_unit == "pp" else "%"
    params = {"condition_series": condition_series, "window_obs": window, "direction": direction,
              "threshold": threshold, "threshold_unit": c_unit, "target_series": target_series,
              "horizon_obs": horizon, "first_episode": episodes[0][0].isoformat(),
              "last_episode": episodes[-1][0].isoformat(),
              "condition_snapshot_sha256": cond[-1].file_sha256, "target_snapshot_sha256": target[-1].file_sha256}
    what = (f"{c_spec.label} {window}개 관측 동안 {threshold:g}{c_unit} 이상 "
            f"{'상승' if direction == 'rise' else '하락'}한 뒤 {t_spec.label} {horizon}개 관측 변화")
    ids = {}
    for name, stats in (("episodes", ep), ("all_days", base)):
        prefix = "조건 충족 구간" if name == "episodes" else "전체 기간(비교 기준)"
        ids[name] = {
            "n": ctx.registry.derived(f"{prefix} 표본 수 — {what}", stats["n"], "count", available, params),
            "mean": ctx.registry.derived(f"{prefix} 평균 — {what}", stats["mean"], t_unit, available, params),
            "median": ctx.registry.derived(f"{prefix} 중앙값 — {what}", stats["median"], t_unit, available, params),
            "share_up": ctx.registry.derived(f"{prefix} 상승 비율 — {what}", stats["share_up"], "share",
                                             available, params),
            "p10": ctx.registry.derived(f"{prefix} 하위 10% — {what}", stats["p10"], t_unit, available, params),
            "p90": ctx.registry.derived(f"{prefix} 상위 10% — {what}", stats["p90"], t_unit, available, params),
        }
    return {"description": what, "episodes": {k: {"evidence_id": ids["episodes"][k], "value": v}
                                               for k, v in ep.items()},
            "all_days_baseline": {k: {"evidence_id": ids["all_days"][k], "value": v} for k, v in base.items()},
            "recent_episode_dates": [e[0].isoformat() for e in episodes[-5:]],
            "caveats": ["historical association only, not a causal effect",
                        "episodes are non-overlapping but successive ones can share a regime",
                        "the same snapshot was used for every as-of; these series are not revised"]}


TOOL_SCHEMAS = [
    {"name": "list_series", "strict": True,
     "description": "List the series this agent may use, their units, sources, availability rules and the "
                    "latest date available at the fixed as-of time. Call this first.",
     "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "get_latest", "strict": True,
     "description": "Most recent observations of one series that were available at as-of, each with an "
                    "evidence_id. Later values are withheld and counted in the note.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["series_id", "count"],
                      "properties": {"series_id": {"type": "string", "enum": list(SERIES)},
                                     "count": {"type": "integer", "description": "1 to 30"}}}},
    {"name": "get_change", "strict": True,
     "description": "Change of one series over the last `window` available observations: percentage-point "
                    "difference for rates, percent change for prices. Returns an evidence_id.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["series_id", "window"],
                      "properties": {"series_id": {"type": "string", "enum": list(SERIES)},
                                     "window": {"type": "integer"}}}},
    {"name": "conditional_outcomes", "strict": True,
     "description": "Historical episodes where condition_series rose/fell by at least `threshold` (in %p for "
                    "rates, % for prices) over `window` observations, and the target's change over the next "
                    "`horizon` observations, compared with all days. Non-overlapping episodes; outcomes "
                    "that ended after as-of are excluded. Association only, not causation.",
     "input_schema": {"type": "object", "additionalProperties": False,
                      "required": ["condition_series", "window", "direction", "threshold", "target_series",
                                   "horizon"],
                      "properties": {"condition_series": {"type": "string", "enum": list(SERIES)},
                                     "window": {"type": "integer"},
                                     "direction": {"type": "string", "enum": ["rise", "fall"]},
                                     "threshold": {"type": "number"},
                                     "target_series": {"type": "string", "enum": list(SERIES)},
                                     "horizon": {"type": "integer"}}}},
]

HANDLERS = {"list_series": list_series, "get_latest": get_latest, "get_change": get_change,
            "conditional_outcomes": conditional_outcomes}
