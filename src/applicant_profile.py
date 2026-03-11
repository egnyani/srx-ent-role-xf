"""Helpers for loading the local applicant profile."""

from __future__ import annotations

import json
from pathlib import Path

PROFILE_PATH = Path("data/applicant_profile.template.json")


def load_profile(path: Path = PROFILE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
