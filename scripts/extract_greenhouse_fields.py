#!/usr/bin/env python3
"""Extract live Greenhouse fields from the current application page."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.greenhouse_apply import SESSION_DIR, load_session
from src.greenhouse_live_plan import extract_greenhouse_fields, write_live_plan


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception as exc:
        raise SystemExit(
            "Playwright Python is not installed. Install it with:\n"
            "  .venv/bin/pip install playwright\n"
            "  .venv/bin/playwright install chromium"
        ) from exc


def _latest_session_file() -> Path | None:
    files = sorted(SESSION_DIR.glob("*.json"))
    return files[-1] if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract live Greenhouse fields")
    parser.add_argument("--session", help="Path to a session JSON file")
    args = parser.parse_args()

    session_path = Path(args.session) if args.session else _latest_session_file()
    if not session_path or not session_path.exists():
        print("No session file found. Run scripts/run_greenhouse_apply.py first.")
        return 1

    plan = load_session(session_path)
    sync_playwright = _import_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(plan["job"]["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        fields = extract_greenhouse_fields(page)
        output_path = write_live_plan(session_path, "extracted_fields", fields)
        print(f"Extracted fields: {len(fields)}")
        print(f"Wrote: {output_path}")
        input("Press Enter here after you finish reviewing the extracted page...")
        context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
