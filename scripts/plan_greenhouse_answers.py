#!/usr/bin/env python3
"""Build a live answer plan for extracted Greenhouse fields."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.applicant_profile import load_profile
from src.greenhouse_apply import SESSION_DIR, load_session
from src.greenhouse_live_plan import LIVE_PLAN_DIR, build_live_answer_plan, write_live_plan


def _latest_session_file() -> Path | None:
    files = sorted(SESSION_DIR.glob("*.json"))
    return files[-1] if files else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan answers for extracted Greenhouse fields")
    parser.add_argument("--session", help="Path to a session JSON file")
    parser.add_argument("--extract", help="Path to an extracted fields JSON file")
    args = parser.parse_args()

    session_path = Path(args.session) if args.session else _latest_session_file()
    if not session_path or not session_path.exists():
        print("No session file found. Run scripts/run_greenhouse_apply.py first.")
        return 1

    extract_path = Path(args.extract) if args.extract else LIVE_PLAN_DIR / f"{session_path.stem}_extracted_fields.json"
    if not extract_path.exists():
        print(f"Extracted field file not found: {extract_path}")
        return 1

    plan = load_session(session_path)
    fields = json.loads(extract_path.read_text(encoding="utf-8"))
    profile = load_profile()
    answer_plan = build_live_answer_plan(fields, plan["job"], profile)
    output_path = write_live_plan(session_path, "answer_plan", answer_plan)
    print(f"Planned answers: {len(answer_plan)}")
    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
