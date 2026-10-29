"""Bitemporal availability contract for future adapters (not legacy feature joins)."""

from dataclasses import dataclass
from datetime import datetime, timezone


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("availability timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Availability:
    """released_at is publication time of THIS vintage, not its reference period.

    Missing or assumed release time cannot certify exact PIT. Live replay also checks ingest.
    """

    released_at: datetime | None
    ingested_at: datetime
    evidence: str  # exact_release / conservative_lag / unknown

    def __post_init__(self):
        _aware(self.ingested_at)
        if self.released_at is not None:
            _aware(self.released_at)
        if self.evidence not in {"exact_release", "conservative_lag", "unknown"}:
            raise ValueError("unsupported availability evidence")

    def eligible(self, decision_at: datetime, *, live_replay: bool = True) -> bool:
        decision = _aware(decision_at)
        if self.released_at is None or self.evidence != "exact_release":
            return False
        return (_aware(self.released_at) <= decision and
                (not live_replay or _aware(self.ingested_at) <= decision))
