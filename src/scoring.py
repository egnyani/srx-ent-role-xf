"""
Job relevance scoring.

Scores each job 0-100 based on:
  - Skill match (40 pts)  — how many of the user's skills appear in the description
  - Role keywords (20 pts) — strong-signal titles (AI/ML, backend, Python, etc.)
  - Entry-level signals (20 pts) — explicit new-grad / 0-3 year language
  - Recency (20 pts) — jobs posted today score highest

Sort the email digest by score descending so the best matches appear first.
"""

import re
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Skill tokens — same set as filters.py but stored here for scoring weight.
# Weight = contribution to the 40-pt skill bucket (capped at 40).
# ---------------------------------------------------------------------------
_SKILL_WEIGHTS: list[tuple[str, int]] = [
    # Languages
    ("python", 3), ("c#", 4), ("javascript", 2), ("typescript", 3),
    ("golang", 4), ("sql", 2),
    # Backend
    ("fastapi", 5), ("flask", 3), ("node.js", 3), ("nodejs", 3),
    ("rest api", 2), ("restful", 2), ("microservice", 3),
    ("websocket", 3), ("celery", 4), ("redis", 3), ("kafka", 4),
    # Frontend / web
    ("react", 3), ("next.js", 4), ("nextjs", 4),
    ("express.js", 3), ("expressjs", 3), ("html5", 1), ("css3", 1),
    # Cloud
    ("aws", 3), ("amazon web services", 3), ("azure", 3),
    ("lambda", 3), ("dynamodb", 3), ("kubernetes", 4),
    ("api gateway", 2), ("cloudwatch", 3),
    # Databases
    ("postgresql", 3), ("postgres", 3), ("sql server", 2),
    ("mongodb", 3), ("databricks", 4), ("snowflake", 4), ("etl", 2),
    # DevOps
    ("docker", 3), ("ci/cd", 3), ("jenkins", 2),
    ("grafana", 3), ("prometheus", 3),
    # AI / ML / LLM
    ("langchain", 5), ("llm", 5), ("large language model", 5),
    ("rag", 5), ("prompt engineering", 5), ("hugging face", 4),
    ("huggingface", 4), ("pytorch", 4), ("scikit-learn", 3),
    ("vector db", 4), ("vector database", 4), ("embeddings", 3),
    ("a/b testing", 2),
]

# Role keyword bonuses — titles that signal high relevance to the user's goals
_ROLE_BONUSES: list[tuple[str, int]] = [
    ("ai engineer", 20), ("ml engineer", 20), ("machine learning engineer", 20),
    ("data engineer", 15), ("backend engineer", 18), ("backend developer", 18),
    ("full stack", 15), ("fullstack", 15), ("software engineer", 12),
    ("python developer", 18), ("python engineer", 18),
    ("llm engineer", 20), ("platform engineer", 12),
    ("cloud engineer", 12), ("devops engineer", 12),
    ("data scientist", 10), ("senior data analyst", 8),
]

# Entry-level signal bonuses
_ENTRY_SIGNALS: list[tuple[str, int]] = [
    ("new grad", 20), ("new graduate", 20), ("recent grad", 20),
    ("entry level", 18), ("entry-level", 18),
    ("0-2 years", 18), ("0-3 years", 15), ("1-2 years", 15), ("1-3 years", 12),
    ("early career", 16), ("junior", 14), ("associate", 12),
    ("engineer i", 15), ("engineer 1", 15), ("level 1", 15),
    ("university", 10), ("internship", 5),
]


def _skill_score(desc: str) -> int:
    """Return skill-match contribution (0–40)."""
    text = desc.lower()
    raw = sum(w for token, w in _SKILL_WEIGHTS if token in text)
    return min(raw, 40)


def _role_score(title: str) -> int:
    """Return role-keyword contribution (0–20)."""
    t = title.lower()
    for keyword, pts in _ROLE_BONUSES:
        if keyword in t:
            return pts
    return 0


def _entry_score(title: str, desc: str) -> int:
    """Return entry-level signal contribution (0–20)."""
    combined = (title + " " + desc).lower()
    for signal, pts in _ENTRY_SIGNALS:
        if signal in combined:
            return pts
    return 0


def _recency_score(date_posted: str) -> int:
    """
    Return recency contribution (0–20).
      Today          → 20
      Yesterday      → 16
      2-3 days ago   → 12
      4-7 days ago   →  8
      8-14 days ago  →  4
      Older / unknown→  0
    """
    if not date_posted:
        return 0
    try:
        posted = datetime.strptime(date_posted[:10], "%Y-%m-%d").date()
        today  = datetime.now().date()
        delta  = (today - posted).days
        if delta == 0:   return 20
        if delta == 1:   return 16
        if delta <= 3:   return 12
        if delta <= 7:   return  8
        if delta <= 14:  return  4
        return 0
    except ValueError:
        return 0


def score_job(job: dict) -> int:
    """
    Return an integer relevance score 0-100 for *job*.

    Breakdown:
      Skill match   0-40
      Role keywords 0-20
      Entry signals 0-20
      Recency       0-20
    """
    title = job.get("job_title", "")
    desc  = job.get("description_text", "")
    date  = job.get("date_posted", "")

    s = (
        _skill_score(desc)
        + _role_score(title)
        + _entry_score(title, desc)
        + _recency_score(date)
    )
    return min(s, 100)


def score_and_sort(jobs: list[dict]) -> list[dict]:
    """Attach a 'score' field to each job and return sorted highest-first."""
    for job in jobs:
        job["score"] = score_job(job)
    return sorted(jobs, key=lambda j: j.get("score", 0), reverse=True)
