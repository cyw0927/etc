"""Feature and label construction for one target asset.

Timing rules (no look-ahead):
- Row t = the close of the target's own bar dated t. The forecast is made at that close.
- Target's own features use bars up to and including t.
- Every OTHER series (other assets, correlations, FRED rates, macro vintages) is joined as-of the latest
  date STRICTLY BEFORE t. This is conservative across time zones: e.g. for SPY at t, KOSPI's close on t
  would be available, but we only use KOSPI up to t-1; FRED's yield dated t-1 is published by t.
- Labels: y_h(t) = 1 if adj_close[t+h] / adj_close[t] - 1 > 0, with h counted in the target's own bars
  (trading days for exchange-traded assets, calendar days for BTC). label_end_h(t) = date of bar t+h.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OWN_FEATURES = ["ret_1", "ret_5", "ret_20", "ret_60", "ma_gap_20", "ma_gap_60", "vol_20", "vol_60", "rsi_14"]


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def own_features(px: pd.DataFrame) -> pd.DataFrame:
    """Features from the target's own bars; value at t uses data up to t only."""
    c = px["adj_close"]
    r1 = c.pct_change(fill_method=None)
    f = pd.DataFrame(index=px.index)
    f["ret_1"] = r1
    for n in (5, 20, 60):
        f[f"ret_{n}"] = c / c.shift(n) - 1
    for n in (20, 60):
        f[f"ma_gap_{n}"] = c / c.rolling(n).mean() - 1
        f[f"vol_{n}"] = r1.rolling(n).std()
    f["rsi_14"] = rsi(c)
    vol = px.get("volume")
    if vol is not None and (vol.fillna(0) > 0).mean() > 0.9:
        v = vol.where(vol > 0)
        f["volume_chg"] = np.log(v.rolling(5).mean() / v.rolling(60).mean())
    return f


def hypothesis_own_features(px: pd.DataFrame) -> pd.DataFrame:
    """Long-window own features for the pre-registered hypotheses (not given to the v0.2 models)."""
    c = px["adj_close"]
    r1 = c.pct_change(fill_method=None)
    f = pd.DataFrame(index=px.index)
    f["mom_12_1"] = c.shift(21) / c.shift(252) - 1
    f["ma_gap_200"] = c / c.rolling(200).mean() - 1
    vol_252 = r1.rolling(252).std()
    f["vol_ratio"] = r1.rolling(20).std() / vol_252
    return f


def hypothesis_rate_features(rates: dict[str, pd.Series]) -> pd.DataFrame:
    if "DGS2" not in rates or "DGS10" not in rates:
        return pd.DataFrame()
    r = pd.concat([rates["DGS2"].rename("us2y"), rates["DGS10"].rename("us10y")], axis=1).dropna()
    return pd.DataFrame({"us2y_chg60": r["us2y"].diff(60), "us10y_chg60": r["us10y"].diff(60)})


def asof_strict(target_index: pd.DatetimeIndex, series: pd.DataFrame) -> pd.DataFrame:
    """Values of `series` as of the last date strictly before each target date."""
    left = pd.DataFrame({"date": target_index.values})
    right = series.sort_index().copy()
    right.index.name = "date"
    right = right.reset_index()
    right["date"] = pd.to_datetime(right["date"]).astype(left["date"].dtype)
    merged = pd.merge_asof(left, right, on="date", direction="backward", allow_exact_matches=False)
    return merged.set_index("date").set_axis(target_index, axis=0)


def cross_asset_features(prices: dict[str, pd.DataFrame], keys: list[str]) -> pd.DataFrame:
    """5- and 20-bar returns of other assets on their own calendars (joined later with asof_strict)."""
    frames = []
    for k in keys:
        if k not in prices:
            continue
        c = prices[k]["adj_close"]
        frames.append(pd.DataFrame({f"{k}_ret_5": c / c.shift(5) - 1, f"{k}_ret_20": c / c.shift(20) - 1}))
    return frames


def rolling_correlations(prices: dict[str, pd.DataFrame], pairs: list[list[str]], window: int = 60) -> pd.DataFrame:
    """Rolling correlation of daily RETURNS (not price levels) on a common Mon–Fri grid."""
    keys = sorted({k for p in pairs for k in p if k in prices})
    if not keys:
        return pd.DataFrame()
    start = min(prices[k].index.min() for k in keys)
    end = max(prices[k].index.max() for k in keys)
    grid = pd.bdate_range(start, end)
    rets = {}
    for k in keys:
        c = prices[k]["adj_close"]
        # forward-fill only across short holiday gaps; never past the series' last real observation
        c = c.reindex(grid).ffill(limit=5).loc[: prices[k].index.max()]
        rets[k] = c.pct_change(fill_method=None)
    rets = pd.DataFrame(rets)
    out = pd.DataFrame(index=grid)
    for a, b in pairs:
        if a in rets and b in rets:
            out[f"corr60_{a}_{b}"] = rets[a].rolling(window, min_periods=window // 2).corr(rets[b])
    return out


def rate_features(rates: dict[str, pd.Series]) -> list[pd.DataFrame]:
    frames = []
    if "DGS2" in rates and "DGS10" in rates:
        r = pd.concat([rates["DGS2"].rename("us2y"), rates["DGS10"].rename("us10y")], axis=1).dropna()
        r["us10y_2y"] = r["us10y"] - r["us2y"]
        r["us2y_chg20"] = r["us2y"].diff(20)
        r["us10y_chg20"] = r["us10y"].diff(20)
        frames.append(r)
    if "DFF" in rates:
        ffr = rates["DFF"].dropna()
        # DFF is daily incl. weekends; use ~3 months of calendar days for the policy-direction proxy
        frames.append(pd.DataFrame({"ffr": ffr, "ffr_chg90d": ffr - ffr.shift(90)}))
    return frames


def macro_features(macro_rt: dict[str, pd.DataFrame]) -> list[pd.DataFrame]:
    """Real-time (vintage) macro features indexed by publication date."""
    frames = []
    for sid, df in macro_rt.items():
        if df.empty:
            continue
        cols = {"value": f"{sid}_rt"}
        if "change" in df:
            cols["change"] = f"{sid}_rt_chg3m"
        frames.append(df[list(cols)].rename(columns=cols))
    return frames


def make_labels(adj_close: pd.Series, horizons: list[int]) -> pd.DataFrame:
    lab = pd.DataFrame(index=adj_close.index)
    dates = pd.Series(adj_close.index, index=adj_close.index)
    lab["ret_next_1"] = adj_close.shift(-1) / adj_close - 1
    for h in horizons:
        fwd = adj_close.shift(-h) / adj_close - 1
        lab[f"fwd_ret_{h}"] = fwd
        lab[f"y_{h}"] = (fwd > 0).astype(float).where(fwd.notna())
        lab[f"label_end_{h}"] = dates.shift(-h)
    return lab


def build_dataset(
    target: str,
    prices: dict[str, pd.DataFrame],
    horizons: list[int],
    cross_keys: list[str],
    corr_pairs: list[list[str]],
    rates: dict[str, pd.Series] | None = None,
    macro_rt: dict[str, pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Return (dataset, feature_columns). Dataset rows include the latest unlabeled bars for forecasting."""
    px = prices[target]
    own = own_features(px)
    external = cross_asset_features(prices, [k for k in cross_keys if k != target])
    corr = rolling_correlations(prices, corr_pairs)
    if not corr.empty:
        external.append(corr)
    external += rate_features(rates or {})
    external += macro_features(macro_rt or {})

    parts = [own] + [asof_strict(px.index, e) for e in external]
    feats = pd.concat(parts, axis=1)
    feature_cols = list(feats.columns)  # the v0.2 feature set given to B2 and M1–M3
    extra = [hypothesis_own_features(px)]
    hyp_rates = hypothesis_rate_features(rates or {})
    if not hyp_rates.empty:
        extra.append(asof_strict(px.index, hyp_rates))
    extra = pd.concat(extra, axis=1)
    extra = extra[[c for c in extra.columns if c not in feats.columns]]
    ds = pd.concat([feats, extra, make_labels(px["adj_close"], horizons)], axis=1)
    ds = ds.loc[own[OWN_FEATURES].notna().all(axis=1)]  # warm-up: need 60 bars of own history
    return ds, feature_cols
