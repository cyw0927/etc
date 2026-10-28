"""Research-only event-time macro features. No legacy pipeline or issuance integration."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import math
import re
import pandas as pd


def aware(t):
    if t.tzinfo is None or t.utcoffset() is None: raise ValueError('timezone-aware timestamp required')
    return t.astimezone(timezone.utc)

@dataclass(frozen=True)
class MacroRevision:
    series: str
    observation_date: date
    value: float
    released_at: datetime | None
    ingested_at: datetime
    source_url: str
    source_sha256: str
    release_evidence: str

    def eligible(self, cutoff):
        decision=aware(cutoff); received=aware(self.ingested_at)
        if self.released_at is None or self.release_evidence!='exact_verified': return False
        release=aware(self.released_at)
        if not re.fullmatch(r'[0-9a-f]{64}',self.source_sha256) or not self.source_url.startswith('https://'):
            raise ValueError('source provenance is incomplete')
        if not math.isfinite(self.value) or received<release: raise ValueError('invalid value or timeline')
        return release<=decision and received<=decision


def features_at(revisions, cutoff, series):
    """Latest observation and latest revision that actually arrived by cutoff; missing remains NA."""
    relevant={}
    for r in revisions:
        if r.series not in series or not r.eligible(cutoff): continue
        k=(r.series,r.observation_date)
        old=relevant.get(k)
        if old is None or aware(r.released_at)>aware(old.released_at): relevant[k]=r
        elif aware(r.released_at)==aware(old.released_at) and r!=old: raise ValueError('conflicting revision provenance')
    output={}
    for sid in series:
        available=[r for (s,_),r in relevant.items() if s==sid]
        output[sid+'_pit']=max(available,key=lambda r:r.observation_date).value if available else float('nan')
    return output


def feature_matrix(revisions, decision_times, series):
    """Create model-ready frame using per-row decisions; never infer availability from observation dates."""
    return pd.DataFrame([features_at(revisions,t,series) for t in decision_times],index=pd.DatetimeIndex(decision_times))
