"""Persistent audit log for application preparation, filling, and submission events."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

HISTORY_PATH = Path("data/application_history.json")


def load_history(path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def append_history_event(event: dict, path: Path = HISTORY_PATH) -> dict:
    items = load_history(path)
    record = {
        "timestamp": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        **event,
    }
    items.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=True), encoding="utf-8")
    return record


def build_history_event(
    *,
    event_type: str,
    status: str,
    plan: dict,
    session_path: str | Path | None = None,
    queue_key: str = "",
    notes: str = "",
    errors: list[dict] | None = None,
) -> dict:
    job = plan.get("job", {})
    resolved_fields = plan.get("resolved_fields", [])
    unresolved_fields = plan.get("unresolved_fields", [])
    return {
        "event_type": event_type,
        "status": status,
        "queue_key": queue_key,
        "company_name": job.get("company_name", ""),
        "job_title": job.get("job_title", ""),
        "url": job.get("url", ""),
        "apply_target": job.get("apply_target", ""),
        "session_path": str(session_path) if session_path else "",
        "resolved_fields": [
            {
                "field_key": field.get("field_key", ""),
                "label": field.get("label", ""),
                "field_type": field.get("field_type", ""),
                "value": field.get("value", ""),
                "source": field.get("source", ""),
            }
            for field in resolved_fields
        ],
        "unresolved_fields": [
            {
                "field_key": field.get("field_key", ""),
                "label": field.get("label", ""),
                "field_type": field.get("field_type", ""),
                "required": bool(field.get("required")),
            }
            for field in unresolved_fields
        ],
        "notes": notes,
        "errors": errors or [],
    }
