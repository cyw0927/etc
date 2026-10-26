"""Logging to console and to artifacts/logs/gmia.log (data-collection errors included)."""

from __future__ import annotations

import logging
import sys

from gmia.config import ARTIFACTS_DIR

_CONFIGURED = False


def get_logger(name: str = "gmia") -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        log_dir = ARTIFACTS_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        root = logging.getLogger("gmia")
        root.setLevel(logging.INFO)
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        file = logging.FileHandler(log_dir / "gmia.log", encoding="utf-8")
        file.setFormatter(fmt)
        root.addHandler(console)
        root.addHandler(file)
        root.propagate = False
        _CONFIGURED = True
    return logging.getLogger(name)
