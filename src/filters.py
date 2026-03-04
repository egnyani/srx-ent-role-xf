"""Entry-level SWE filter for job postings."""

SWE_KEYWORDS = [
    "software", "developer", "backend", "frontend", "full stack", "fullstack",
    "sde", "swe", "mobile", "ios", "android",
]
SENIORITY_KEYWORDS = [
    "senior", "staff", "principal", "lead", "manager", "director",
    "architect", "head", "vp", "intern", "internship", "sr.", " sr ",
]
ENTRY_LEVEL_SIGNALS = [
    "0-3", "0 to 3", "1-3", "1 to 3", "new grad", "new graduate",
    "entry level", "entry-level", "junior", "associate", "university",
    "early career", "engineer i", "engineer 1", "swe i", "swe 1",
    "software engineer i", "software engineer 1", "level 1", "level i",
    "recent grad", "recent graduate", "0-2", "0 to 2", "1-2 year",
]


def is_entry_level_swe(job: dict) -> tuple[bool, str]:
    """
    Returns (True, reason) if the job is likely an entry-level SWE role.

    Filtering logic:
      1. Title must contain an SWE keyword.
      2. Title must NOT contain a seniority keyword.
      3. If the title or description contains an explicit entry-level signal,
         that's a strong positive match.
      4. If no explicit signal is found but steps 1 & 2 pass, the role is
         still included — many entry-level postings simply say "Software
         Engineer" without explicit level language.
    """
    title = (job.get("job_title") or "").lower()
    desc = (job.get("description_text") or "").lower()
    combined = f"{title} {desc}"

    # Step 1: must have an SWE keyword in the title
    if not any(kw in title for kw in SWE_KEYWORDS):
        return (False, "")

    # Step 2: must NOT have a seniority keyword in the title
    if any(kw in title for kw in SENIORITY_KEYWORDS):
        return (False, "")

    # Step 3: check for explicit entry-level signals (title or description)
    for signal in ENTRY_LEVEL_SIGNALS:
        if signal in combined:
            return (True, signal)

    # Step 4: no explicit signal but no seniority either — include the role
    # (e.g. plain "Software Engineer" at a sponsoring company)
    return (True, "no-seniority")
