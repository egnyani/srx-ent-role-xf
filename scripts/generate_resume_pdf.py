#!/usr/bin/env python3
"""Generate the applicant resume PDF used by the apply flow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.applicant_profile import load_profile
from src.resume_documents import ensure_resume_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the resume PDF from structured resume data")
    parser.add_argument("--force", action="store_true", help="Regenerate even if the PDF already exists")
    args = parser.parse_args()

    profile = load_profile()
    if not profile:
        print("Applicant profile not found or unreadable.")
        return 1

    output_path = ensure_resume_pdf(profile, force=args.force)
    print(f"Generated resume PDF: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
