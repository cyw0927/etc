"""Append-only point-in-time forward predictions, maturity scoring, and pre-registered tests.

The ledger is a LOCAL SQLite file (data/ledger/); never commit it to the public repository.
Forecast and score rows are immutable. SQLite unique keys + transactions keep first arrivals.
See docs/preregistration_v0.4.md before interpreting any significance result.
"""

from __future__ import annotations

import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gmia.config import AssetSpec, asset_specs, resolve
from gmia.evaluation.significance import benjamini_hochberg, loss_diff_test
from gmia.models.registry import MODEL_LABELS

ASSETS = ("SPY", "QQQ", "KOSPI", "NIKKEI", "GOLD", "BTC", "USDKRW", "USDJPY", "WTI")
HORIZONS = (5, 20)
MODELS = (
    "baseline_base_rate", "baseline_momentum",
    "logistic_regression", "hist_gradient_boosting", "lightgbm",
    "logistic_regression_shrink", "logistic_regression_platt",
    "hist_gradient_boosting_shrink", "hist_gradient_boosting_platt",
    "lightgbm_shrink", "lightgbm_platt",
    "h1_trend", "h2_vol_regime", "h3_rates_regime", "h4_short_reversal",
)
BASELINE = "baseline_base_rate"
MIN_PAIRS = 500
MIN_SPAN_DAYS = 540
FDR_Q = 0.10
FAMILY_SIZE = len(ASSETS) * len(HORIZONS) * (len(MODELS) - 1)
assert FAMILY_SIZE == 252 and all(m in MODEL_LABELS for m in MODELS)


def ledger_path(cfg: dict) -> Path:
    return resolve(cfg.get("forward_test", {}).get("ledger_path", "data/ledger/forward.sqlite3"))


def utc_time(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def bar_completion_utc(date: str | pd.Timestamp, spec: AssetSpec) -> datetime:
    """Calendar-date bar completed only after exchange-local close + 15 minutes."""
    day = pd.Timestamp(date).date()
    hours, minutes = map(int, spec.close_time.split(":"))
    close = datetime(day.year, day.month, day.day, hours, minutes, tzinfo=ZoneInfo(spec.close_tz))
    return (close + timedelta(minutes=15)).astimezone(timezone.utc)


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS forecasts (
        forecast_date TEXT NOT NULL,
        asset TEXT NOT NULL,
        horizon INTEGER NOT NULL,
        model TEXT NOT NULL,
        probability REAL NOT NULL CHECK(probability >= 0 AND probability <= 1),
        recorded_utc TEXT NOT NULL,
        git_commit TEXT,
        run_id TEXT NOT NULL,
        anchor_price REAL NOT NULL CHECK(anchor_price > 0),
        currency TEXT NOT NULL,
        PRIMARY KEY (forecast_date, asset, horizon, model)
    );
    CREATE TABLE IF NOT EXISTS scores (
        forecast_date TEXT NOT NULL,
        asset TEXT NOT NULL,
        horizon INTEGER NOT NULL,
        model TEXT NOT NULL,
        label_end TEXT NOT NULL,
        y INTEGER NOT NULL CHECK(y IN (0, 1)),
        realized_return REAL NOT NULL,
        scored_utc TEXT NOT NULL,
        source_fetched_utc TEXT NOT NULL,
        PRIMARY KEY (forecast_date, asset, horizon, model),
        FOREIGN KEY (forecast_date, asset, horizon, model)
          REFERENCES forecasts(forecast_date, asset, horizon, model)
    );
    CREATE TRIGGER IF NOT EXISTS forecasts_no_update BEFORE UPDATE ON forecasts
      BEGIN SELECT RAISE(ABORT, 'forecasts are append-only'); END;
    CREATE TRIGGER IF NOT EXISTS forecasts_no_delete BEFORE DELETE ON forecasts
      BEGIN SELECT RAISE(ABORT, 'forecasts are append-only'); END;
    CREATE TRIGGER IF NOT EXISTS scores_no_update BEFORE UPDATE ON scores
      BEGIN SELECT RAISE(ABORT, 'scores are append-only'); END;
    CREATE TRIGGER IF NOT EXISTS scores_no_delete BEFORE DELETE ON scores
      BEGIN SELECT RAISE(ABORT, 'scores are append-only'); END;
    """)
    db.commit()
    return db


@contextmanager
def db_session(path: Path):
    db = connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def append_forecasts(
    path: Path, forecasts: list[dict], prices: dict[str, pd.DataFrame], cfg: dict,
    run_id: str, git_commit: str | None, recorded_utc: datetime | None = None,
) -> dict:
    """Store the first actual issued forecast for every (date, asset, horizon, model).

    Every candidate is recorded, never just the selected model. Reject incomplete anchors.
    One transaction handles the whole run; rerunning a date cannot overwrite a previous value.
    """
    when = utc_time(recorded_utc or datetime.now(timezone.utc))
    specs = asset_specs(cfg)
    rows = []
    for fc in forecasts:
        asset, h, date = fc["target"], int(fc["horizon"]), fc["forecast_date"]
        if asset not in ASSETS or h not in HORIZONS:
            continue
        if asset not in prices:
            raise ValueError(f"missing anchor asset {asset}")
        frame = prices[asset]
        stamp = pd.Timestamp(date)
        if stamp not in frame.index:
            raise ValueError(f"forecast anchor {asset}/{date} absent from price series")
        anchor = float(frame.loc[stamp, "adj_close"])
        if not np.isfinite(anchor) or anchor <= 0:
            raise ValueError(f"bad anchor price: {asset}/{date}")
        if when < bar_completion_utc(date, specs[asset]):
            raise ValueError(f"incomplete anchor bar: {asset}/{date}")
        probs = fc["p_up_all_models"]
        # A candidate may be legitimately unavailable (e.g. H3 without historical rates).
        # Never manufacture a probability; absent candidates retain p=1 in the 252-test family.
        for model in MODELS:
            if model not in probs:
                continue
            prob = float(probs[model])
            if not math.isfinite(prob) or not 0 <= prob <= 1:
                raise ValueError(f"invalid probability for {asset}/{h}/{model}")
            rows.append((date, asset, h, model, prob, when.isoformat(),
                         git_commit, run_id, anchor, specs[asset].currency))
    with db_session(path) as db:
        before = db.total_changes
        db.executemany("""
            INSERT OR IGNORE INTO forecasts
            (forecast_date, asset, horizon, model, probability, recorded_utc,
             git_commit, run_id, anchor_price, currency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        inserted = db.total_changes - before
    return {"attempted": len(rows), "inserted": inserted, "duplicates": len(rows) - inserted,
            "path": str(path)}


def score_pending(
    path: Path, cfg: dict, prices: dict[str, pd.DataFrame], metas: dict[str, dict],
    now_utc: datetime | None = None, eligible: set[tuple[str, str, int]] | None = None,
) -> dict:
    """Score ONLY matured forecasts using newly fetched real market data.

    Late predictions and premature/stale/invalid observations remain unscored.
    Scores are immutable: future vendor revisions must never rewrite previously scored rows.
    v0.4.1 (docs/preregistration_v0.4.1.md): a forecast recorded at or after the completion of
    the bar FOLLOWING its forecast date is a stale issue and is never scored.
    v0.4.2 (docs/preregistration_v0.4.2.md): when `eligible` is given, only forecasts whose
    (forecast_date, asset, horizon) passed the caller's checks are considered; others are held.
    """
    when = utc_time(now_utc or datetime.now(timezone.utc))
    specs = asset_specs(cfg)
    stats = {"pending": 0, "scored": 0, "held": 0, "late_excluded": 0, "stale_issue_excluded": 0,
             "not_mature": 0, "stale_source": 0, "missing_data": 0, "invalid": 0}
    with db_session(path) as db:
        pending = db.execute("""
            SELECT f.forecast_date, f.asset, f.horizon, f.model, f.recorded_utc
            FROM forecasts f
            LEFT JOIN scores s
            ON s.forecast_date=f.forecast_date AND s.asset=f.asset
              AND s.horizon=f.horizon AND s.model=f.model
            WHERE s.model IS NULL
            ORDER BY f.asset, f.horizon, f.forecast_date, f.model
        """).fetchall()
        stats["pending"] = len(pending)
        new_scores = []
        for origin, asset, h, model, recorded in pending:
            if eligible is not None and (origin, asset, int(h)) not in eligible:
                stats["held"] += 1
                continue
            if asset not in prices or asset not in specs:
                stats["missing_data"] += 1
                continue
            px = prices[asset]["adj_close"].sort_index()
            date = pd.Timestamp(origin)
            if date not in px.index:
                stats["missing_data"] += 1
                continue
            pos = int(px.index.get_loc(date))
            if pos + h >= len(px):
                stats["not_mature"] += 1
                continue
            end = px.index[pos + h]
            completed = bar_completion_utc(end, specs[asset])
            if utc_time(recorded) >= completed:
                stats["late_excluded"] += 1
                continue
            # Timely issuance: part of the outcome path was already public when it was recorded.
            if utc_time(recorded) >= bar_completion_utc(px.index[pos + 1], specs[asset]):
                stats["stale_issue_excluded"] += 1
                continue
            if when < completed:
                stats["not_mature"] += 1
                continue
            fetched = metas.get(asset, {}).get("fetched_at_utc")
            if fetched is None or utc_time(fetched) <= completed:
                stats["stale_source"] += 1
                continue
            if utc_time(fetched) > when:
                stats["invalid"] += 1
                continue
            a, b = float(px.iloc[pos]), float(px.iloc[pos + h])
            if not np.isfinite(a) or not np.isfinite(b) or a <= 0 or b <= 0:
                stats["invalid"] += 1
                continue
            ret = b / a - 1
            new_scores.append((origin, asset, h, model, end.strftime("%Y-%m-%d"),
                               int(ret > 0), ret, when.isoformat(), utc_time(fetched).isoformat()))
        before = db.total_changes
        db.executemany("""
            INSERT OR IGNORE INTO scores
            (forecast_date, asset, horizon, model, label_end, y,
             realized_return, scored_utc, source_fetched_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, new_scores)
        stats["scored"] = db.total_changes - before
    return stats


def read_forecasts(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with db_session(path) as db:
        return pd.read_sql_query("SELECT * FROM forecasts ORDER BY forecast_date, asset, horizon, model", db)


def read_scores(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    with db_session(path) as db:
        return pd.read_sql_query("""
            SELECT f.forecast_date, f.asset, f.horizon, f.model, f.probability,
                   f.recorded_utc, f.git_commit, s.label_end, s.y,
                   s.realized_return, s.scored_utc
            FROM scores s INNER JOIN forecasts f
            ON f.forecast_date=s.forecast_date AND f.asset=s.asset
              AND f.horizon=s.horizon AND f.model=s.model
            ORDER BY f.asset, f.horizon, f.forecast_date, f.model
        """, db)


def forward_significance(scored: pd.DataFrame) -> pd.DataFrame:
    """All 252 preregistered tests, including missing ones with p=1 for BH denominator."""
    cols = ["asset", "horizon", "model", "n", "span_days", "brier", "brier_base",
            "mean_brier_diff", "se_hac", "t_stat", "p_one_sided",
            "p_bh_adjusted", "enough_data", "bh_significant", "supported"]
    rows = []
    for asset in ASSETS:
        for h in HORIZONS:
            if not scored.empty:
                group = scored[(scored["asset"] == asset) & (scored["horizon"] == h)]
                base = group[group["model"] == BASELINE][["forecast_date", "probability", "y"]].rename(
                    columns={"probability": "base_p", "y": "base_y"})
            else:
                group = pd.DataFrame(columns=["forecast_date", "model", "probability", "y"])
                base = pd.DataFrame(columns=["forecast_date", "base_p", "base_y"])
            for model in MODELS:
                if model == BASELINE:
                    continue
                candidate = group[group["model"] == model][["forecast_date", "probability", "y"]]
                matched = candidate.merge(base, on="forecast_date", how="inner", validate="one_to_one")
                if not matched.empty and (matched["y"] != matched["base_y"]).any():
                    raise ValueError(f"inconsistent labels for {asset}/{h}/{model}")
                matched = matched.sort_values("forecast_date")
                n = len(matched)
                span = ((pd.Timestamp(matched["forecast_date"].iloc[-1]) -
                         pd.Timestamp(matched["forecast_date"].iloc[0])).days if n else 0)
                enough = n >= MIN_PAIRS and span >= MIN_SPAN_DAYS
                brier = float(((matched["probability"] - matched["y"]) ** 2).mean()) if n else float("nan")
                brier_base = float(((matched["base_p"] - matched["y"]) ** 2).mean()) if n else float("nan")
                if enough:
                    result = loss_diff_test(matched["y"], matched["probability"],
                                            matched["base_p"], lag=h)
                    p = float(result["p_one_sided"])
                    if not math.isfinite(p):
                        p = 1.0
                else:
                    result = {}
                    p = 1.0
                rows.append({"asset": asset, "horizon": h, "model": model, "n": n,
                             "span_days": span, "brier": brier, "brier_base": brier_base,
                             "mean_brier_diff": brier - brier_base if n else float("nan"),
                             "se_hac": result.get("se_hac", float("nan")),
                             "t_stat": result.get("t_stat", float("nan")), "p_one_sided": p,
                             "enough_data": enough})
    result = pd.DataFrame(rows)
    if len(result) != FAMILY_SIZE:
        raise AssertionError("the pre-registered 252-test family changed")
    rejected, adj = benjamini_hochberg(result["p_one_sided"], FDR_Q)
    result["p_bh_adjusted"] = adj
    result["bh_significant"] = rejected
    result["supported"] = (result["enough_data"] & result["bh_significant"] &
                           (result["mean_brier_diff"] < 0))
    return result[cols]
