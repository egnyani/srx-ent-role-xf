#!/usr/bin/env python3
"""Build or refresh a local application queue from scraper outputs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.apply_queue import build_queue_item, load_queue, queue_key, save_queue
from src.io_export import load_existing_jobs

STRICT_PATH = "output/entry_roles.xlsx"
INTERESTING_PATH = "output/interesting_roles.xlsx"
APPLIED_PATH = Path("data/applied_jobs.json")


def load_applied_urls() -> set[str]:
    if not APPLIED_PATH.exists():
        return set()
    try:
        payload = json.loads(APPLIED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        item.get("job_url", "").strip()
        for item in payload
        if item.get("job_url")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build application queue from exported jobs")
    parser.add_argument("--strict", default=STRICT_PATH, help="Path to strict jobs Excel")
    parser.add_argument("--interesting", default=INTERESTING_PATH, help="Path to interesting jobs Excel")
    parser.add_argument("--include-interesting", action="store_true", help="Include interesting bucket")
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on newly queued jobs")
    args = parser.parse_args()

    strict_jobs = load_existing_jobs(args.strict)
    interesting_jobs = load_existing_jobs(args.interesting) if args.include_interesting else []
    existing_queue = load_queue()
    existing_keys = {item.get("queue_key", "") for item in existing_queue}
    applied_urls = load_applied_urls()

    new_items: list[dict] = []
    counts = Counter()

    def add_jobs(jobs: list[dict], bucket: str) -> None:
        nonlocal new_items
        for job in jobs:
            url = (job.get("url") or "").strip()
            key = queue_key(job)
            if url and url in applied_urls:
                counts["applied_skipped"] += 1
                continue
            if key in existing_keys:
                counts["existing_skipped"] += 1
                continue
            new_items.append(build_queue_item(job, bucket))
            existing_keys.add(key)
            counts[f"{bucket}_queued"] += 1
            if args.limit is not None and len(new_items) >= args.limit:
                return

    add_jobs(strict_jobs, "strict")
    if args.limit is None or len(new_items) < args.limit:
        add_jobs(interesting_jobs, "interesting")

    merged = existing_queue + new_items
    save_queue(merged)

    print(f"Queue size: {len(merged)}")
    print(f"New items added: {len(new_items)}")
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
