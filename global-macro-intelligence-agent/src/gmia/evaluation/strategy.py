"""Illustrative long/flat rule applied to out-of-sample probabilities.

Definition (documented so results are reproducible):
- signal_t = 1 if P(up over h bars) at close t > threshold, else 0 (flat = cash, 0% return, no interest)
- with execution lag L, the position over the bar from close t to close t+1 is signal_{t-L}
  (L=1: decide at close t, trade at the NEXT close — no same-close execution is assumed)
- cost = cost_bps x |change in position| at each rebalance; buy-and-hold pays no costs
- the h-bar probability drives a daily-rebalanced position; this is a simple usefulness check,
  not an optimized or recommended strategy
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _stats(r: pd.Series, bars_per_year: float) -> dict:
    r = r.fillna(0.0)
    equity = (1 + r).cumprod()
    years = len(r) / bars_per_year if bars_per_year else np.nan
    total = float(equity.iloc[-1] - 1) if len(r) else np.nan
    dd = equity / equity.cummax() - 1
    vol = float(r.std() * np.sqrt(bars_per_year)) if len(r) > 1 else np.nan
    return {
        "total_return": total,
        "cagr": float((1 + total) ** (1 / years) - 1) if years and years > 0 and total > -1 else np.nan,
        "ann_vol": vol,
        "sharpe_rf0": float(r.mean() * bars_per_year / vol) if vol and vol > 0 else np.nan,
        "max_drawdown": float(dd.min()) if len(dd) else np.nan,
    }


def long_flat_backtest(p: pd.Series, ret_next_1: pd.Series, threshold: float, lag: int, cost_bps: float,
                       bars_per_year: float) -> tuple[dict, pd.DataFrame]:
    df = pd.DataFrame({"p": p, "r": ret_next_1}).dropna(subset=["r"])
    signal = (df["p"] > threshold).astype(float)
    pos = signal.shift(lag).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    strat_gross = pos * df["r"]
    strat_net = strat_gross - turnover * cost_bps / 1e4
    curve = pd.DataFrame({
        "strategy_net": (1 + strat_net).cumprod(),
        "buy_and_hold": (1 + df["r"]).cumprod(),
        "position": pos,
    })
    out = {f"strategy_{k}": v for k, v in _stats(strat_net, bars_per_year).items()}
    out.update({f"strategy_gross_{k}": v for k, v in _stats(strat_gross, bars_per_year).items() if k == "total_return"})
    out.update({f"buy_hold_{k}": v for k, v in _stats(df["r"], bars_per_year).items()})
    out["exposure"] = float(pos.mean())
    out["round_trips"] = float(turnover.sum() / 2)
    out["cost_bps"] = cost_bps
    out["execution_lag_bars"] = lag
    return out, curve
