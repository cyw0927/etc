"""Strict temporal availability: observation date never implies publication time."""
from dataclasses import dataclass
from datetime import datetime, timezone


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Vintage:
    """Publication and ingestion refer to this revision; end is exclusive."""
    observation_id: str
    published_at: datetime | None
    ingested_at: datetime
    valid_until: datetime | None
    evidence: str
    value: float

    def available(self, decision: datetime) -> bool:
        cutoff=utc(decision); ingest=utc(self.ingested_at)
        if self.evidence != 'verified_release' or self.published_at is None:
            return False
        release=utc(self.published_at)
        if self.valid_until is not None and utc(self.valid_until)<=release:
            raise ValueError('invalid vintage validity window')
        return release<=cutoff and ingest<=cutoff and (self.valid_until is None or cutoff<utc(self.valid_until))


def latest_known(records: list[Vintage], decision: datetime) -> dict[str, Vintage]:
    selected={}
    for row in records:
        if not row.available(decision):
            continue
        old=selected.get(row.observation_id)
        if old is None or utc(row.published_at)>utc(old.published_at):
            selected[row.observation_id]=row
        elif utc(row.published_at)==utc(old.published_at) and row!=old:
            raise ValueError('conflicting vintage with identical publication time')
    return selected
