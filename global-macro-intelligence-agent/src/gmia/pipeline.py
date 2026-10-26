"""End-to-end run: load stored data -> features -> walk-forward evaluation -> latest forecasts -> artifacts."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from importlib.metadata import version

import pandas as pd
import yaml

from gmia import DISCLAIMER, __version__
from gmia.config import ARTIFACTS_DIR, PROJECT_ROOT, asset_specs
from gmia.data import fred, market
from gmia.evaluation.backtest import InsufficientHistory, run_walk_forward
from gmia.features.build import build_dataset
from gmia.models.predict import latest_forecast
from gmia.report import write_report
from gmia.utils.logging import get_logger

log = get_logger("gmia.pipeline")


def load_inputs(cfg: dict) -> dict:
    raw = cfg["data"]["raw_dir"]
    prices, metas = {}, {}
    for key in cfg["assets"]:
        loaded = market.load_asset(raw, key)
        if loaded is None:
            log.warning("no stored data for %s (run scripts/fetch_data.py)", key)
            continue
        prices[key], metas[key] = loaded
    rates = {}
    for sid in cfg.get("rates", {}):
        loaded = fred.load_fred(raw, sid, "rates")
        if loaded is not None:
            rates[sid] = loaded[0].iloc[:, 0]
    macro_rt = {}
    use_macro = cfg["modeling"].get("use_macro_vintages", "auto")
    if use_macro in ("auto", True):
        for sid in cfg.get("macro", {}):
            loaded = fred.load_fred(raw, sid, "macro_realtime")
            if loaded is not None:
                macro_rt[sid] = loaded[0]
    return {"prices": prices, "metas": metas, "rates": rates if cfg["modeling"].get("use_rates", True) else {},
            "macro_rt": macro_rt}


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    except Exception:
        return None


def run(cfg: dict, run_id: str | None = None) -> dict:
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARTIFACTS_DIR / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs(cfg)
    prices, specs, m = inputs["prices"], asset_specs(cfg), cfg["modeling"]

    summaries, fold_metrics, preds, reliab, curves, forecasts, verdicts, skipped = [], [], [], [], [], [], [], []
    for target in m["targets"]:
        if target not in prices:
            skipped.append({"target": target, "reason": "data unavailable"})
            continue
        cross = list(dict.fromkeys(m["common_cross_assets"] + m.get("extra_cross_assets", {}).get(target, [])))
        ds, feats = build_dataset(target, prices, m["horizons"], cross, m.get("correlation_pairs", []),
                                  inputs["rates"], inputs["macro_rt"])
        for h in m["horizons"]:
            log.info("evaluating %s h=%d (%d rows, %d features)", target, h, len(ds), len(feats))
            try:
                res = run_walk_forward(ds, feats, h, cfg)
            except InsufficientHistory as e:
                skipped.append({"target": target, "horizon": h, "reason": str(e)})
                continue
            tag = {"target": target, "horizon": h}
            for name, frame, sink in (("summary", res["summary"], summaries), ("fold_metrics", res["fold_metrics"], fold_metrics),
                                      ("predictions", res["predictions"], preds), ("reliability", res["reliability"], reliab),
                                      ("curves", res["curves"], curves)):
                sink.append(frame.assign(**tag))
            fc = latest_forecast(ds, feats, h, res["verdict"], cfg)
            spec = specs[target]
            fc.update({"target": target, "name": spec.name, "ticker": spec.ticker, "price_type": spec.price_type,
                       "currency": spec.currency, "horizon_unit": spec.horizon_unit,
                       "data_last_date": prices[target].index.max().strftime("%Y-%m-%d"),
                       "n_features": len(feats), "features": feats, "verdict": res["verdict"]})
            forecasts.append(fc)
            verdicts.append({**tag, **res["verdict"]})

    pd.concat(summaries).to_csv(out_dir / "metrics_summary.csv", index=False)
    pd.concat(fold_metrics).to_csv(out_dir / "fold_metrics.csv", index=False)
    pd.concat(preds).to_parquet(out_dir / "oos_predictions.parquet")
    pd.concat(reliab).to_csv(out_dir / "reliability.csv", index=False)
    pd.concat(curves).to_parquet(out_dir / "equity_curves.parquet")
    pd.DataFrame(verdicts).to_csv(out_dir / "verdicts.csv", index=False)

    run_meta = {
        "run_id": run_id, "gmia_version": __version__, "git_commit": _git_commit(),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "packages": {p: version(p) for p in ("pandas", "numpy", "scikit-learn", "lightgbm", "yfinance")},
        "data": {k: {"source": v.get("source"), "start": v["quality"]["start"], "end": v["quality"]["end"],
                     "fetched_at_utc": v.get("fetched_at_utc")} for k, v in inputs["metas"].items()},
        "rates_used": sorted(inputs["rates"]), "macro_realtime_used": sorted(inputs["macro_rt"]),
        "macro_note": None if inputs["macro_rt"] else
            "US macro (CPI, unemployment, IP, M2) excluded from models: no release-date vintages (set FRED_API_KEY)",
        "skipped": skipped, "disclaimer": DISCLAIMER,
    }
    (out_dir / "run_meta.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / "forecasts.json").write_text(json.dumps(forecasts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with open(out_dir / "config.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump({k: v for k, v in cfg.items() if not k.startswith("_")}, f, allow_unicode=True, sort_keys=False)
    write_report(out_dir, forecasts, pd.concat(summaries), run_meta)

    latest = ARTIFACTS_DIR / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(out_dir, latest)
    log.info("run %s written to %s (also copied to %s)", run_id, out_dir, latest)
    return {"run_id": run_id, "out_dir": out_dir, "forecasts": forecasts, "run_meta": run_meta}
