"""Entry-level SWE filter for job postings."""

import re
from typing import Sequence

# ---------------------------------------------------------------------------
# Experience-requirement screening
# ---------------------------------------------------------------------------
# These patterns in a job description indicate the role requires more
# experience than an entry-level / new-grad candidate would have.

_OVEREXP_PATTERNS = [
    # ── 3+ / 3 or more / at least 3 ────────────────────────────────────────
    # "3+ years" in any context (3+ years of experience, 3+ years required, …)
    re.compile(r"\b3\s*\+\s*years?\b", re.I),
    # "3 or more years", "3 plus years"
    re.compile(r"\b3\s+(?:or\s+more|plus)\s+years?\b", re.I),
    # "minimum 3 years", "at least 3 years", "requires 3 years", "minimum of 3 years"
    re.compile(r"\b(?:minimum|at\s+least|requires?)\s+(?:of\s+)?3\s+years?\b", re.I),
    # Range with lower bound ≥ 3 going higher, e.g. "3-5 years", "3 to 7 years"
    # (but NOT "0-3", "1-3", "2-3" — those are fine)
    re.compile(r"\b3\s*(?:\-|to)\s*[4-9]\d*\s*years?\b", re.I),

    # ── 4 + years (clearly senior) ──────────────────────────────────────────
    re.compile(r"\b[4-9]\s*\+\s*years?\b", re.I),
    re.compile(r"\b[4-9]\d*\s+(?:or\s+more|plus)\s+years?\b", re.I),
    re.compile(r"\b(?:minimum|at\s+least|requires?)\s+(?:of\s+)?[4-9]\s+years?\b", re.I),
    # Ranges where the LOWER bound is 4+ (e.g. "4-6 years", "5 to 8 years")
    re.compile(r"\b[4-9]\s*(?:to|\-)\s*\d+\s*years?\b", re.I),

    # ── Special phrasings ───────────────────────────────────────────────────
    # Amazon's "3+ years of non-internship professional…"
    re.compile(r"\b3\s*\+\s*years?\s+of\s+non[\s\-]?internship", re.I),
]


def _requires_too_much_experience(text: str) -> bool:
    """Return True if the description requires 3+ years (too senior for entry-level)."""
    for pat in _OVEREXP_PATTERNS:
        if pat.search(text):
            return True
    return False

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

# US state abbreviations (2-letter) — matched as whole words to avoid false positives
_US_STATES_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

# Full US state names
_US_STATES_FULL = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming",
}

# US city / metro signals
_US_CITY_SIGNALS = {
    "new york", "los angeles", "san francisco", "seattle", "boston",
    "chicago", "austin", "denver", "atlanta", "dallas", "houston",
    "miami", "washington dc", "washington, dc", "washington d.c",
    "mountain view", "menlo park", "palo alto", "sunnyvale", "santa clara",
    "san jose", "redwood city", "bellevue", "kirkland", "redmond",
    "pittsburgh", "philadelphia", "phoenix", "minneapolis", "portland",
    "san diego", "raleigh", "charlotte", "nashville", "salt lake",
    "annapolis junction", "chantilly", "herndon", "mclean", "rosslyn",
    "fort belvoir", "lorton", "hawthorne", "cape canaveral",
    "foster city", "fayetteville", "columbia, md", "jacksonville",
    "cottonwood heights", "bastrop", "mcgregor", "helena, montana",
    "greenwich", "louisville, colorado",
}

# Explicit non-US signals — countries, provinces, major foreign cities
_NON_US_SIGNALS = [
    # Countries
    "india", "canada", "united kingdom", "england", "scotland", "wales",
    "ireland", "germany", "france", "spain", "italy", "netherlands",
    "portugal", "poland", "austria", "switzerland", "sweden", "norway",
    "denmark", "finland", "belgium", "czech", "hungary", "romania",
    "bulgaria", "serbia", "ukraine", "russia", "turkey", "israel",
    "uae", "united arab emirates", "saudi arabia", "qatar", "singapore",
    "australia", "new zealand", "japan", "china", "south korea", "korea",
    "brazil", "mexico", "argentina", "chile", "colombia", "costa rica",
    "luxembourg", "slovenia", "croatia", "estonia", "latvia", "lithuania",
    "slovakia", "chile", "peru",
    # Canadian provinces
    "ontario", "british columbia", "alberta", "quebec", "nova scotia",
    "manitoba", "saskatchewan", "new brunswick", "newfoundland",
    # Non-US city names
    "london", "dublin", "paris", "berlin", "amsterdam", "madrid",
    "barcelona", "lisbon", "warsaw", "krakow", "bucharest", "belgrade",
    "zagreb", "prague", "budapest", "vienna", "zurich", "brussels",
    "stockholm", "oslo", "copenhagen", "helsinki", "toronto", "vancouver",
    "montreal", "calgary", "mississauga", "hyderabad", "bangalore",
    "bengaluru", "mumbai", "pune", "delhi", "chennai", "gurugram",
    "gurgaon", "noida", "ahmedabad", "kolkata", "tokyo", "osaka",
    "beijing", "shanghai", "guangzhou", "shenzhen", "hong kong",
    "seoul", "sydney", "melbourne", "singapore", "tel aviv",
    "mexico city", "são paulo", "buenos aires", "santiago", "bogota",
    "aarhus", "dundee", "edinburgh", "glasgow", "graz", "dusseldorf",
    "lysaker", "luxembourg",
    # Country codes used as suffixes (e.g. "Dublin, IE", "London, gb", "São Carlos, br")
    ", ie", ", gb", ", mx", ", no", ", dk", ", se", ", fi", ", nl",
    ", de", ", fr", ", es", ", it", ", pt", ", pl", ", at", ", ch",
    ", be", ", in", " - in", ", br", ", au", ", ca", ", nz", ", sg",
    ", jp", ", cn", ", kr", ", il", ", ae", ", sa",
    # Region indicators
    "latam", "emea", "apac", "eastern europe", "western europe",
    # Specific patterns
    "in - bengaluru", "in-bengaluru",
]

# Patterns that confirm US even if non-US strings are present
_US_OVERRIDE_PATTERNS = [
    r"\bUSA?\b",
    r"United States",
    r"U\.S\.",
    r"US Remote",
    r"Remote U\.?S",
    r"Remote,?\s*US",
]


def is_us_location(job: dict) -> bool:
    """
    Return True if the job appears to be US-based or US-remote.
    Strategy:
      1. Empty / generic location (Remote, Hybrid, Any Office) → include
      2. Explicit US override patterns → include
      3. Any non-US signal → exclude
      4. US state abbreviation or full name found → include
      5. Known US city found → include
      6. Anything else unrecognised → include (avoid false negatives)
    """
    raw = (job.get("location") or "").strip()
    if not raw:
        return True

    loc_lower = raw.lower()

    # Step 1: purely generic / unknown location
    _generic = {"remote", "hybrid", "any office", "distributed", "in-office",
                "location", "flexible", "work from home", "wfh", "anywhere"}
    if loc_lower in _generic:
        return True

    # Step 2: explicit US override (e.g. "United States", "USA", "US Remote")
    for pat in _US_OVERRIDE_PATTERNS:
        if re.search(pat, raw, re.IGNORECASE):
            return True

    # Step 3: non-US signals → exclude
    for sig in _NON_US_SIGNALS:
        if sig in loc_lower:
            return False

    # Step 4: US state abbreviation as a whole word (case-insensitive on raw)
    for abbr in _US_STATES_ABBR:
        if re.search(r'\b' + abbr + r'\b', raw, re.IGNORECASE):
            return True

    # Step 5: US state full name
    for state in _US_STATES_FULL:
        if state in loc_lower:
            return True

    # Step 6: known US city
    for city in _US_CITY_SIGNALS:
        if city in loc_lower:
            return True

    # Step 7: unknown location — include rather than wrongly exclude
    return True


_NON_ENGLISH_TITLE_WORDS = {
    # Portuguese
    "engenheiro", "desenvolvedor", "analista", "pleno", "junior", "sênior",
    "coordenador", "gerente", "programador",
    # Spanish
    "ingeniero", "desarrollador", "programador", "analista", "coordinador",
    # French
    "développeur", "ingénieur", "analyste",
    # German
    "entwickler", "ingenieur", "softwareentwickler",
    # General non-ASCII signal
}

def _is_non_english_title(title: str) -> bool:
    """Return True if the title is likely non-English."""
    # Non-ASCII characters (accents, special chars)
    try:
        title.encode("ascii")
    except UnicodeEncodeError:
        return True
    # Known non-English job words (ASCII but foreign language)
    title_lower = title.lower()
    return any(word in title_lower.split() for word in _NON_ENGLISH_TITLE_WORDS)


def is_entry_level_swe(job: dict) -> tuple[bool, str]:
    """
    Returns (True, reason) if the job is likely an entry-level SWE role.

    Filtering logic:
      1. Title must not contain non-ASCII characters (filters non-English postings).
      2. Title must contain an SWE keyword.
      3. Title must NOT contain a seniority keyword.
      4. Description must not require too much experience (3+ years).
      5. Check for explicit entry-level signals.
      6. No seniority + SWE keyword = include (plain "Software Engineer").
    """
    title = (job.get("job_title") or "").lower()
    desc = (job.get("description_text") or "").lower()
    combined = f"{title} {desc}"

    # Step 1: reject non-English titles (e.g. "Engenheiro de Software Pleno")
    if _is_non_english_title(job.get("job_title") or ""):
        return (False, "")

    # Step 2: must have an SWE keyword in the title
    if not any(kw in title for kw in SWE_KEYWORDS):
        return (False, "")

    # Step 3: must NOT have a seniority keyword in the title
    if any(kw in title for kw in SENIORITY_KEYWORDS):
        return (False, "")

    # Step 4: reject if description requires too much experience
    # e.g. "3+ years", "4+ years", "minimum 5 years"
    if desc and _requires_too_much_experience(desc):
        return (False, "")

    # Step 4: check for explicit entry-level signals (title or description)
    for signal in ENTRY_LEVEL_SIGNALS:
        if signal in combined:
            return (True, signal)

    # Step 5: no explicit signal but no seniority either — include the role
    # (e.g. plain "Software Engineer" at a sponsoring company)
    return (True, "no-seniority")


# ---------------------------------------------------------------------------
# Skill-based fallback — catches roles titled "Analyst", "Application
# Developer", etc. that share the same requirements as SWE positions.
# ---------------------------------------------------------------------------

# Minimum number of matching skill tokens for a job to pass the skill filter.
_SKILL_MATCH_THRESHOLD = 3

# Skills grouped by category (used for logging / debugging).
# Each entry is (token_to_search_for, weight).
# Weight ≥ 2 means a single hit counts double (strong technical signal).
_SKILL_TOKENS: list[tuple[str, int]] = [
    # --- Languages ---
    ("python", 1),
    ("c#", 2),
    ("javascript", 1),
    ("typescript", 1),
    ("golang", 1),
    (" go ", 1),          # space-padded to avoid "go" in "django" etc.
    ("sql", 1),
    # --- Backend frameworks & infra ---
    ("fastapi", 2),
    ("flask", 1),
    ("node.js", 1),
    ("nodejs", 1),
    ("rest api", 1),
    ("restful", 1),
    ("microservice", 1),
    ("websocket", 1),
    ("celery", 2),
    ("redis", 1),
    ("kafka", 2),
    # --- Web / frontend ---
    ("react", 1),
    ("next.js", 2),
    ("nextjs", 2),
    ("express.js", 1),
    ("expressjs", 1),
    ("html5", 1),
    ("css3", 1),
    # --- Cloud ---
    ("aws", 1),
    ("amazon web services", 1),
    ("azure", 1),
    ("lambda", 1),
    ("dynamodb", 1),
    ("kubernetes", 2),
    ("api gateway", 1),
    ("cloudwatch", 2),
    # --- Databases ---
    ("postgresql", 1),
    ("postgres", 1),
    ("sql server", 1),
    ("mongodb", 1),
    ("databricks", 2),
    ("snowflake", 2),
    ("etl", 1),
    # --- DevOps ---
    ("docker", 1),
    ("ci/cd", 1),
    ("jenkins", 1),
    ("grafana", 2),
    ("prometheus", 2),
    # --- AI / ML / LLM ---
    ("langchain", 2),
    ("llm", 2),
    ("large language model", 2),
    ("rag", 2),
    ("prompt engineering", 2),
    ("hugging face", 2),
    ("huggingface", 2),
    ("pytorch", 2),
    ("scikit-learn", 2),
    ("sklearn", 1),
    ("vector db", 2),
    ("vector database", 2),
    ("embeddings", 1),
    ("a/b testing", 1),
]

# Titles that should be considered for skill-based fallback even though they
# don't contain SWE keywords.  Keep this broad — the skill threshold filters.
_SKILL_FALLBACK_TITLES: list[str] = [
    "analyst",
    "application developer",
    "app developer",
    "data engineer",
    "platform engineer",
    "systems engineer",
    "solutions engineer",
    "cloud engineer",
    "devops engineer",
    "ml engineer",
    "ai engineer",
    "machine learning engineer",
    "data scientist",
    "associate engineer",
    "junior engineer",
    "entry",
    "developer",
    "engineer",
]


def _skill_match_score(text: str) -> int:
    """Return a weighted count of skill tokens found in *text* (lowercased)."""
    score = 0
    text_lower = text.lower()
    for token, weight in _SKILL_TOKENS:
        if token in text_lower:
            score += weight
    return score


def is_skill_match(job: dict) -> tuple[bool, str]:
    """
    Skill-based fallback for non-SWE-titled roles.

    Returns (True, reason) if:
      - The title does NOT contain SWE keywords (handled upstream) but DOES
        contain a fallback-title signal (analyst, developer, engineer, …).
      - The title has no seniority keyword.
      - The description scores ≥ _SKILL_MATCH_THRESHOLD on the weighted skill
        token list.
      - The description does not require too much experience.
    """
    title = (job.get("job_title") or "").lower()
    desc = (job.get("description_text") or "").lower()

    # Exclude business analyst — different track, not a SWE-adjacent role
    if "business analyst" in title:
        return (False, "")

    # Must have a loose "tech role" keyword in title
    if not any(sig in title for sig in _SKILL_FALLBACK_TITLES):
        return (False, "")

    # Allow "senior" for data/tech analyst roles only (e.g. Senior Data Analyst).
    # Business Analyst is excluded — it's a different track and rarely technical enough.
    # All other seniority keywords (staff, principal, lead, manager, …) are still blocked.
    _analyst_role = "analyst" in title and "business analyst" not in title
    _blocking_seniority = [
        kw for kw in SENIORITY_KEYWORDS
        if not (_analyst_role and kw in ("senior", "sr.", " sr "))
    ]
    if any(kw in title for kw in _blocking_seniority):
        return (False, "")

    # Reject if description calls for too much experience
    if desc and _requires_too_much_experience(desc):
        return (False, "")

    # Score description against skills
    score = _skill_match_score(desc)
    if score >= _SKILL_MATCH_THRESHOLD:
        return (True, f"skill-match(score={score})")

    return (False, "")
