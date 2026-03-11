"""Helpers for building and maintaining an application queue."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .dedup import job_fingerprint

QUEUE_PATH = Path("data/apply_queue.json")
QUEUE_STATUSES = {
    "queued",
    "in_progress",
    "filled_for_review",
    "needs_manual_review",
    "needs_email_code",
    "submitted",
    "failed",
}


def load_queue(path: Path = QUEUE_PATH) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_queue(items: list[dict], path: Path = QUEUE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=True), encoding="utf-8")


def update_queue_item(queue_key: str, **updates) -> dict | None:
    status = updates.get("status")
    if status and status not in QUEUE_STATUSES:
        raise ValueError(f"Unsupported queue status: {status}")
    items = load_queue()
    updated_item = None
    for item in items:
        if item.get("queue_key") != queue_key:
            continue
        item.update(updates)
        item["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        updated_item = item
        break
    if updated_item is not None:
        save_queue(items)
    return updated_item


def next_queued_item(apply_target: str) -> dict | None:
    items = load_queue()
    for item in items:
        if item.get("status") != "queued":
            continue
        if item.get("apply_target") != apply_target:
            continue
        if not item.get("auto_apply_supported"):
            continue
        return item
    return None


def infer_apply_target(url: str) -> str:
    u = (url or "").lower()
    if "greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "ashbyhq.com" in u:
        return "ashby"
    if "myworkdayjobs.com" in u or "workday" in u:
        return "workday"
    if "smartrecruiters.com" in u:
        return "smartrecruiters"
    if "icims.com" in u:
        return "icims"
    return "unknown"


def supports_auto_apply(item: dict) -> bool:
    return item.get("apply_target") in {"greenhouse", "lever"}


def queue_key(job: dict) -> str:
    url = (job.get("url") or "").strip()
    return url or job_fingerprint(job)


def build_queue_item(job: dict, bucket: str) -> dict:
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    apply_target = infer_apply_target(job.get("url", ""))
    return {
        "queue_key": queue_key(job),
        "status": "queued",
        "bucket": bucket,
        "company_name": job.get("company_name", ""),
        "job_title": job.get("job_title", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "source": job.get("source", ""),
        "date_posted": job.get("date_posted", ""),
        "score": job.get("score", ""),
        "apply_target": apply_target,
        "auto_apply_supported": supports_auto_apply({"apply_target": apply_target}),
        "created_at": now,
        "updated_at": now,
        "last_attempt_at": "",
        "attempt_count": 0,
        "notes": "",
    }
