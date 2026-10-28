"""Data contracts for the future news pipeline (Phase 3). No collection code exists yet."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Verification = Literal["confirmed_fact", "official_claim", "multi_source_independent", "single_outlet",
                       "unverified_party_claim", "speculation"]  # A..F of the master prompt
Direction = Literal["positive", "negative", "ambiguous"]
Basis = Literal["fact", "party_claim", "media_interpretation", "ai_inference"]

SOURCE_POLICY = {
    "preferred_outlets": ["Reuters", "Associated Press", "Financial Times", "Bloomberg", "The Wall Street Journal",
                          "Nikkei Asia", "South China Morning Post", "BBC", "Deutsche Welle", "France 24", "Al Jazeera"],
    "preferred_primary": ["central banks", "statistics offices / finance ministries", "company filings",
                          "IMF / World Bank / BIS / OECD", "IEA / EIA / OPEC", "official sanctions and legal texts"],
    "excluded_by_default": ["Korean media secondary coverage of international affairs"],
    "allowed_korean": ["Bank of Korea, Statistics Korea and other official Korean economic statistics"],
    "access_rules": ["legal RSS / API only", "no paywall circumvention", "store headline, URL and metadata, not full paid text"],
}


@dataclass
class AssetImpact:
    target: str  # country, industry or asset, e.g. "WTI", "airlines", "KRW"
    direction: Direction
    basis: Basis
    rationale: str


@dataclass
class Article:
    title: str
    outlet: str
    url: str
    published_at: datetime          # when the article became public (point-in-time key for backtests)
    event_at: datetime | None
    countries: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    event_type: str | None = None
    verification: Verification = "single_outlet"
    original_source: str | None = None  # wire/agency the story relies on; duplicates share it
    duplicate_of: str | None = None
    impacts: list[AssetImpact] = field(default_factory=list)
