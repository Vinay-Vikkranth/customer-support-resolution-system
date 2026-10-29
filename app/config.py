"""Load simple KEY=value settings without overriding explicitly supplied environment variables."""

import os
from pathlib import Path


def load_env():
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key.replace("_", "").isalnum():
            os.environ.setdefault(key, value.strip('"').strip("'"))


load_env()
