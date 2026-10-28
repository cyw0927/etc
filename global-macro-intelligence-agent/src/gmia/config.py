"""Configuration loading and project paths."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "default.yaml"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"


@dataclass(frozen=True)
class AssetSpec:
    key: str
    ticker: str
    name: str
    price_type: str
    currency: str
    calendar: str  # "trading" or "calendar"
    close_tz: str
    close_time: str

    @property
    def horizon_unit(self) -> str:
        return "calendar days" if self.calendar == "calendar" else "trading days"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = copy.deepcopy(cfg)
    cfg["_path"] = str(path)
    return cfg


def asset_specs(cfg: dict[str, Any]) -> dict[str, AssetSpec]:
    return {key: AssetSpec(key=key, **spec) for key, spec in cfg["assets"].items()}


def resolve(path: str | Path) -> Path:
    """Resolve a config path relative to the project root."""
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p
