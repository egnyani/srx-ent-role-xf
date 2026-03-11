"""Question-aware answer selection for live application forms."""

from __future__ import annotations

import json
import os
import re

from .answer_memory import lookup_answer

# Optional: rapidfuzz for school fuzzy matching
try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _norm(text)))


def _bool_hint(value: str) -> str:
    value_n = _norm(value)
    if value_n in {"yes", "true"}:
        return "yes"
    if value_n in {"no", "false"}:
        return "no"
    return value_n


# EEO semantic mappings: profile intent -> option label synonyms
EEO_GENDER_MAP = {
    "woman": ["female", "woman", "f", "f "],
    "man": ["male", "man", "m", "m "],
    "non-binary": ["non-binary", "nonbinary", "gender non-conforming", "genderqueer", "non-binary/non-conforming"],
    "decline": ["decline", "prefer not", "do not wish", "choose not", "don't wish", "i don't wish"],
}

EEO_ETHNICITY_MAP = {
    "asian": ["asian", "south asian", "east asian", "southeast asian", "asian (not hispanic)", "asian or pacific islander"],
    "south asian": ["south asian", "asian", "asian (not hispanic)"],
    "white": ["white", "caucasian", "white (not hispanic)"],
    "black": ["black", "african american", "black or african american"],
    "hispanic": ["hispanic", "latino", "hispanic or latino", "hispanic/latino"],
    "decline": ["decline", "prefer not", "do not wish", "choose not"],
}

EEO_DISABILITY_MAP = {
    "yes": ["yes", "i have", "i am an individual with"],
    "no": ["no", "i don't have", "i do not have", "no, i don't", "no, i do not"],
    "decline": ["decline", "prefer not", "do not wish", "choose not"],
}

EEO_VETERAN_MAP = {
    "yes": ["veteran", "i am a protected veteran", "i identify", "armed forces"],
    "no": ["not a protected veteran", "no", "i am not", "i don't identify"],
    "decline": ["decline", "prefer not", "do not wish", "choose not"],
}


def _eeo_exact_lookup(desired: str, options: list[str], mapping: dict) -> str:
    """Match desired value to options using domain-specific synonym mapping."""
    desired_lower = _norm(desired)
    for category, synonyms in mapping.items():
        if any(s in desired_lower for s in synonyms):
            for opt in options:
                opt_lower = _norm(opt)
                if any(s in opt_lower for s in synonyms):
                    return opt
    return ""


def _is_country_code_options(options: list[str]) -> bool:
    """Check if options look like country code dropdown (e.g. 'United States+1')."""
    if not options or len(options) < 5:
        return False
    count = 0
    for opt in (o or "" for o in options):
        if "+" in opt and len(opt) > 4:
            count += 1
            if count >= 3:
                return True
    return False


def _fuzzy_school_match(desired: str, options: list[str], threshold: int = 85) -> str:
    """Match school/university with fuzzy logic; avoid alphabetic fallback."""
    if not desired or not options:
        return ""
    if HAS_RAPIDFUZZ:
        result = process.extractOne(
            desired, options,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold,
        )
        if result:
            return result[0]
    # Fallback: check if any option contains significant words from desired
    desired_words = [w for w in desired.lower().split() if len(w) > 3]
    for opt in options:
        opt_lower = (opt or "").lower()
        matches = sum(1 for w in desired_words if w in opt_lower)
        if matches >= min(2, len(desired_words)):
            return opt
    return ""


def _fuzzy_discipline_match(desired: str, options: list[str], threshold: int = 72) -> str:
    if not desired or not options:
        return ""
    if HAS_RAPIDFUZZ:
        result = process.extractOne(
            desired, options,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=threshold,
        )
        if result:
            return result[0]
    desired_words = [w for w in desired.lower().split() if len(w) > 3]
    for opt in options:
        opt_lower = (opt or "").lower()
        if sum(1 for w in desired_words if w in opt_lower) >= 2:
            return opt
    return ""


def _score_option(question: str, option: str, desired_value: str, profile: dict) -> int:
    option_n = _norm(option)
    desired_n = _norm(desired_value)
    score = 0

    if option_n == desired_n:
        score += 100
    if desired_n and desired_n in option_n:
        score += 35

    desired_tokens = _tokenize(desired_value)
    option_tokens = _tokenize(option)
    score += 4 * len(desired_tokens & option_tokens)

    bool_hint = _bool_hint(desired_value)
    if bool_hint == "yes" and option_n.startswith("yes"):
        score += 20
    if bool_hint == "no" and option_n.startswith("no"):
        score += 20

    eeo = profile.get("eeo", {})
    if "disability" in _norm(question):
        disability = _norm(eeo.get("disability_status", ""))
        if disability == "no":
            if "no, i don't have" in option_n or "no, i do not have" in option_n:
                score += 40
            if "prefer not" in option_n or "don't wish" in option_n:
                score -= 20
    if "veteran" in _norm(question):
        veteran = _norm(eeo.get("veteran_status", ""))
        if veteran == "no":
            if "not a protected veteran" in option_n or "no" == option_n:
                score += 25
            if "prefer not" in option_n:
                score -= 20
    if "transgender" in _norm(question) and _norm(eeo.get("transgender", "")) == "no":
        if option_n.startswith("no"):
            score += 25

    return score


def _llm_select_option(
    question: str,
    options: list[str],
    desired_value: str,
    profile: dict,
    field: dict | None = None,
) -> str:
    """Use Groq (Llama 3.3 70B) or Ollama for option selection."""
    cfg = (profile.get("agent_instructions") or {}).get("ai_fallback") or {}
    if not cfg.get("enabled"):
        return ""

    provider = cfg.get("provider", "groq")
    model = cfg.get("model") or ("llama-3.3-70b-versatile" if provider == "groq" else "llama3.1:8b")

    # Domain hints for better planning
    section = (field or {}).get("section") or ""
    section_lower = section.lower()
    label_lower = (field.get("label") if field else question) or ""

    eeo_hint = ""
    if any(k in section_lower for k in ["equal employment", "eeo", "demographic", "diversity", "voluntary"]):
        eeo_hint = (
            "IMPORTANT: This is an Equal Employment Opportunity question. "
            "Map the desired answer to the closest matching option label exactly as shown. "
            "For gender: 'Woman' or 'Female' intent → pick 'Female'. "
            "When uncertain, prefer 'Decline To Self Identify' over a wrong answer.\n"
        )

    edu_hint = ""
    if any(k in label_lower for k in ["school", "university", "college", "institution", "degree", "discipline"]):
        edu_hint = (
            "IMPORTANT: This is a school/education field. "
            "Match by institution or degree name similarity. "
            "If the exact school is absent, pick the most similar option. "
            "Never pick alphabetically first.\n"
        )

    prompt = (
        f"{eeo_hint}{edu_hint}"
        "You are choosing the safest exact answer option for a job application.\n"
        "Return exactly one option from the provided list.\n"
        "If none are appropriate, return UNKNOWN.\n\n"
        f"Question: {question}\n"
        f"Desired answer intent: {desired_value}\n"
        f"Options: {json.dumps(options, ensure_ascii=True)}\n"
        f"Applicant profile (relevant): {json.dumps({k: profile.get(k) for k in ['identity', 'education', 'eeo'] if profile.get(k)}, ensure_ascii=True)}\n"
    )

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return ""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=80,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception:
            return ""
    else:
        # Ollama fallback
        import requests
        endpoint = os.getenv("OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")
        try:
            resp = requests.post(
                endpoint,
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=25,
            )
            resp.raise_for_status()
            text = (resp.json().get("response") or "").strip()
        except Exception:
            return ""

    if not text or text.upper() == "UNKNOWN":
        return ""

    # Match returned text to an exact option
    for option in options:
        if _norm(text) == _norm(option):
            return option
        if _norm(option) in _norm(text):
            return option
    return ""


def choose_option(
    question: str,
    options: list[str],
    desired_value: str,
    profile: dict,
    field: dict | None = None,
) -> str:
    """Select the best matching option for a form field."""
    cleaned = [opt.strip() for opt in options if (opt or "").strip()]
    if not cleaned:
        return desired_value

    section = (field or {}).get("section") or ""
    remembered = lookup_answer(question, cleaned, section=section)
    if remembered:
        for option in cleaned:
            if _norm(option) == _norm(remembered):
                return option

    exact = [opt for opt in cleaned if _norm(opt) == _norm(desired_value)]
    if exact:
        return exact[0]

    # EEO pre-LLM lookup (avoids wrong picks like Male when profile says Woman)
    label_n = _norm(question)
    section_n = _norm(section)
    eeo_section = any(k in section_n for k in ["eeo", "demographic", "diversity", "voluntary", "equal employment"])

    if "gender" in label_n or ("gender" in section_n and eeo_section):
        eeo_match = _eeo_exact_lookup(desired_value, cleaned, EEO_GENDER_MAP)
        if eeo_match:
            return eeo_match
        # Safe fallback for EEO gender: prefer Decline over wrong answer
        for opt in cleaned:
            if "decline" in _norm(opt) or "prefer not" in _norm(opt):
                return opt

    if ("ethnicity" in label_n or "race" in label_n or "racial" in label_n) and eeo_section:
        eeo_match = _eeo_exact_lookup(desired_value, cleaned, EEO_ETHNICITY_MAP)
        if eeo_match:
            return eeo_match
        for opt in cleaned:
            if "decline" in _norm(opt) or "prefer not" in _norm(opt):
                return opt

    if "disability" in label_n and eeo_section:
        eeo_match = _eeo_exact_lookup(desired_value, cleaned, EEO_DISABILITY_MAP)
        if eeo_match:
            return eeo_match
        for opt in cleaned:
            if "decline" in _norm(opt) or "prefer not" in _norm(opt):
                return opt

    if "veteran" in label_n and eeo_section:
        eeo_match = _eeo_exact_lookup(desired_value, cleaned, EEO_VETERAN_MAP)
        if eeo_match:
            return eeo_match
        for opt in cleaned:
            if "decline" in _norm(opt) or "prefer not" in _norm(opt):
                return opt

    # Phone country code: options are "United States+1" etc — match by country, not by number
    if _is_country_code_options(cleaned) and desired_value:
        # desired_value might be a phone number; we need country from profile
        identity = profile.get("identity", {})
        phone_raw = (identity.get("phone") or "").strip()
        if phone_raw:
            try:
                import phonenumbers
                parsed = phonenumbers.parse(phone_raw, None)
                region = phonenumbers.region_code_for_number(parsed)
                country_code = f"+{parsed.country_code}"
                # Match "United States+1" or "Canada+1"
                for opt in cleaned:
                    if country_code in opt or (region and region.upper() in opt.upper()):
                        return opt
            except Exception:
                pass
        return ""

    # School/education: fuzzy match before LLM
    if any(k in label_n for k in ["school", "university", "college", "institution"]):
        fuzzy_match = _fuzzy_school_match(desired_value, cleaned)
        if fuzzy_match:
            return fuzzy_match
        return ""

    if "discipline" in label_n or "major" in label_n:
        fuzzy_match = _fuzzy_discipline_match(desired_value, cleaned)
        if fuzzy_match:
            return fuzzy_match
        return ""

    # LLM fallback
    ai_choice = _llm_select_option(question, cleaned, desired_value, profile, field)
    if ai_choice:
        return ai_choice

    # Last resort: rule-based scoring (avoid alphabetic for education)
    if any(k in label_n for k in ["school", "university", "college", "discipline", "major"]):
        return ""

    ranked = sorted(cleaned, key=lambda opt: _score_option(question, opt, desired_value, profile), reverse=True)
    return ranked[0] if ranked else desired_value
