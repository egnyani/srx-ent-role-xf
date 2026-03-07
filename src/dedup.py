"""
Cross-platform job deduplication.

URL-based dedup misses the same job posted on multiple platforms
(e.g. Greenhouse + Adzuna).  This module adds a content fingerprint
built from (title, company, location) so duplicates are caught
regardless of source.
"""

import hashlib
import re


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation/whitespace for stable comparison."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def job_fingerprint(job: dict) -> str:
    """
    Return a short hex fingerprint for a job.

    Uses the first 30 chars of normalized title + company + first 15 chars
    of location so minor location variations (county names, etc.) don't
    create false non-duplicates.
    """
    title    = _normalize(job.get("job_title", ""))[:40]
    company  = _normalize(job.get("company_name", ""))[:30]
    location = _normalize(job.get("location", ""))[:15]
    raw = f"{title}|{company}|{location}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def deduplicate(jobs: list[dict], existing_fingerprints: set[str] | None = None) -> list[dict]:
    """
    Remove duplicate jobs from *jobs*.

    Deduplication is done in two passes:
      1. Against *existing_fingerprints* (jobs already saved from previous runs).
      2. Within the current batch itself (same job from multiple sources).

    Returns the deduplicated list and the updated fingerprint set.
    """
    seen: set[str] = set(existing_fingerprints or [])
    unique: list[dict] = []
    for job in jobs:
        fp = job_fingerprint(job)
        if fp in seen:
            continue
        seen.add(fp)
        job["_fingerprint"] = fp   # attach so callers can persist it easily
        unique.append(job)
    return unique, seen
