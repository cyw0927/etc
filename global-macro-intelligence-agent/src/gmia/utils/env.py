"""Minimal .env loader (KEY=VALUE lines) so secrets stay out of the repository and the config."""

from __future__ import annotations

import os

from gmia.config import PROJECT_ROOT


def load_dotenv(path=None) -> None:
    path = path or PROJECT_ROOT / ".env"
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
