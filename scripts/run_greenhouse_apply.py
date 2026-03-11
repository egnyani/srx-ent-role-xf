#!/usr/bin/env python3
"""Prepare a supervised Greenhouse application session."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.applicant_profile import load_profile
from src.application_history import append_history_event, build_history_event
from src.apply_queue import load_queue, next_queued_item, update_queue_item
from src.greenhouse_apply import build_application_plan, load_application_html, open_in_browser, write_session


def find_item(queue_key: str) -> dict | None:
    for item in load_queue():
        if item.get("queue_key") == queue_key:
            return item
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a supervised Greenhouse apply session")
    parser.add_argument("--queue-key", help="Specific queue key to run")
    parser.add_argument("--no-open", action="store_true", help="Do not open the live job page in the browser")
    args = parser.parse_args()

    job = find_item(args.queue_key) if args.queue_key else next_queued_item("greenhouse")
    if not job:
        print("No queued Greenhouse item found.")
        return 1

    profile = load_profile()
    if not profile:
        print("Applicant profile not found or unreadable.")
        return 1

    html, html_source = load_application_html(job["url"])
    plan = build_application_plan(job, profile, html)
    session_path = write_session(plan)

    unresolved = len([f for f in plan["unresolved_fields"] if f["required"]])
    update_queue_item(
        job["queue_key"],
        status="in_progress",
        last_attempt_at=plan["generated_at"],
        attempt_count=int(job.get("attempt_count", 0)) + 1,
        notes=f"Session prepared: {session_path.name}; html source: {html_source}; unresolved required fields: {unresolved}",
    )
    append_history_event(
        build_history_event(
            event_type="session_prepared",
            status="in_progress",
            plan=plan,
            session_path=session_path,
            queue_key=job["queue_key"],
            notes=(
                f"Prepared Greenhouse session from {html_source} HTML with "
                f"{len(plan['resolved_fields'])} resolved fields and {unresolved} unresolved required fields."
            ),
        )
    )

    print(f"Prepared Greenhouse session: {session_path}")
    print(f"Job: {job['job_title']} @ {job['company_name']}")
    print(f"HTML source: {html_source}")
    print(f"Resolved fields: {len(plan['resolved_fields'])}")
    print(f"Unresolved required fields: {unresolved}")
    if unresolved:
        print("Still needs answers for:")
        for field in plan["unresolved_fields"]:
            if field["required"]:
                print(f"- {field['label']} ({field['field_type']})")

    if not args.no_open:
        open_in_browser(job["url"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
