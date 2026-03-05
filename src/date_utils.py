"""Date parsing utilities for ATS job postings."""

from datetime import datetime, timezone


def iso_to_date_str(value) -> str:
    """Parse an ISO 8601 string → 'YYYY-MM-DD', or '' on failure."""
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # Quick path: ISO 8601 always starts with YYYY-MM-DD
    if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
        candidate = s[:10]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            pass
    return ""


def unix_ms_to_date_str(value) -> str:
    """Convert epoch milliseconds (Lever's createdAt) → 'YYYY-MM-DD', or '' on failure."""
    if not value:
        return ""
    try:
        ms = int(value)
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def slash_to_date_str(value) -> str:
    """
    Handle Workday's 'MM/DD/YYYY' or ISO format → 'YYYY-MM-DD'.
    Falls back to iso_to_date_str for ISO strings.
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # Try MM/DD/YYYY (10 chars exactly)
    if len(s) >= 10 and s[2:3] == "/" and s[5:6] == "/":
        try:
            dt = datetime.strptime(s[:10], "%m/%d/%Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    # Fall back to ISO parsing
    return iso_to_date_str(s)
