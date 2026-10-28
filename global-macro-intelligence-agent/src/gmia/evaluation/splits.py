"""Time-ordered splits: expanding walk-forward validation folds plus one final holdout.

Purging: a training row t is kept only if its label window has ENDED before the test block starts
(label_end(t) < test_start). With h-bar labels this removes the last h rows before each boundary, so no
training label overlaps the test period. Random shuffling is never used.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Fold:
    name: str
    kind: str  # "validation" or "holdout"
    train_index: pd.DatetimeIndex
    test_index: pd.DatetimeIndex
    purged: int

    def describe(self) -> dict:
        return {
            "fold": self.name, "kind": self.kind,
            "train_start": self.train_index.min(), "train_end": self.train_index.max(), "n_train": len(self.train_index),
            "test_start": self.test_index.min(), "test_end": self.test_index.max(), "n_test": len(self.test_index),
            "purged_rows": self.purged,
        }


def _fold(name: str, kind: str, dates: pd.DatetimeIndex, label_end: pd.Series,
          test_start: pd.Timestamp, test_end: pd.Timestamp | None) -> Fold | None:
    before = dates[dates < test_start]
    train = before[label_end.loc[before] < test_start]
    test = dates[(dates >= test_start) & (dates < test_end)] if test_end is not None else dates[dates >= test_start]
    if len(train) == 0 or len(test) == 0:
        return None
    return Fold(name, kind, train, test, purged=len(before) - len(train))


def make_folds(label_end: pd.Series, min_train_years: float, val_block_years: float, holdout_years: float) -> list[Fold]:
    """label_end: index = sample dates (labelled rows only), values = date the label is realized."""
    dates = pd.DatetimeIndex(label_end.index).sort_values()
    label_end = label_end.loc[dates]
    first, last = dates.min(), dates.max()
    holdout_start = last - pd.DateOffset(years=holdout_years)
    folds: list[Fold] = []
    block_start = first + pd.DateOffset(years=min_train_years)
    i = 0
    while block_start < holdout_start:
        block_end = min(block_start + pd.DateOffset(years=val_block_years), holdout_start)
        f = _fold(f"val_{i:02d}_{block_start:%Y}", "validation", dates, label_end, block_start, block_end)
        if f is not None:
            folds.append(f)
        block_start, i = block_end, i + 1
    h = _fold("holdout", "holdout", dates, label_end, holdout_start, None)
    if h is not None:
        folds.append(h)
    return folds
