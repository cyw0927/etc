"""International news / geopolitics module — interface only in v0.2 (NOT IMPLEMENTED).

Design constraints carried from the GMIA prompts:
- Korean-media secondary coverage of international affairs is excluded by default; foreign outlets and
  official primary sources are preferred, through legal RSS/API access only (no paywall circumvention).
- Impact is classified per country / industry / asset, never as one global sentiment.
- Facts, party claims, media interpretation and AI inference are kept separate.
- News scores are NOT model features until point-in-time historical news can be backtested. Until then the
  news agent may only attach qualitative commentary next to the statistical forecast; it can never change it.
"""

from gmia.news.schema import Article, AssetImpact, SOURCE_POLICY  # noqa: F401
