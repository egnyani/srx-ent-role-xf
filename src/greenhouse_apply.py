"""Greenhouse application helpers for a supervised apply runner."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
import requests

from .http_client import FetchError, get

SESSION_DIR = Path("output/apply_sessions")


def fetch_application_html(url: str) -> str:
    resp = get(url)
    if resp.status_code != 200:
        raise FetchError(f"Greenhouse returned {resp.status_code}: {url}")
    return resp.text


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception as exc:  # pragma: no cover - dependency check
        raise FetchError(
            "Playwright Python is not installed for Greenhouse browser fallback."
        ) from exc


def fetch_application_html_browser(url: str) -> str:
    sync_playwright = _import_playwright()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        html = page.content()
        context.close()
        browser.close()
    return html


def _field_entry(field_type: str, field_key: str, label: str, required: bool) -> dict:
    return {
        "field_type": field_type,
        "field_key": field_key,
        "label": label.strip(),
        "required": required,
    }


def parse_fields(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="application-form") or soup.find("form")
    if not form:
        return []

    fields: list[dict] = []
    seen: set[str] = set()
    for label in form.find_all("label"):
        field_id = label.get("for")
        if not field_id or field_id in seen:
            continue
        control = form.find(id=field_id)
        if control is None:
            continue
        seen.add(field_id)
        label_text = label.get_text(" ", strip=True)
        required = "*" in label_text or control.get("aria-required") == "true"
        clean_label = label_text.replace("*", "").strip()
        tag = control.name
        if tag == "input":
            field_type = control.get("type", "text")
            fields.append(_field_entry(field_type, field_id, clean_label, required))
        elif tag in {"textarea", "select"}:
            fields.append(_field_entry(tag, field_id, clean_label, required))
    return fields


def load_application_html(url: str) -> tuple[str, str]:
    try:
        html = fetch_application_html(url)
        if parse_fields(html):
            return html, "http"
    except FetchError:
        pass

    html = fetch_application_html_browser(url)
    return html, "browser"


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip().lower())


def _candidate_location_value(profile: dict) -> str:
    identity = profile.get("identity", {})
    prefs = profile.get("preferences", {})
    override = (prefs.get("application_city_override") or "").strip()
    if override:
        return override
    city = (identity.get("location_city") or "").strip()
    state = (prefs.get("application_state_override") or identity.get("location_state") or "").strip()
    country = (identity.get("country") or "").strip()
    return ", ".join(part for part in [city, state, country] if part)


def _normalized_phone(identity: dict) -> str:
    raw = (identity.get("phone") or "").strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits or raw


def _parse_phone(identity: dict) -> tuple[str, str]:
    """Return (country_option_hint, national_number) for composite phone fields."""
    raw = (identity.get("phone") or "").strip()
    if not raw:
        return "", ""
    try:
        import phonenumbers
        parsed = phonenumbers.parse(raw, None)
        country_code = f"+{parsed.country_code}"
        national = phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.NATIONAL
        )
        national_digits = re.sub(r"\D", "", national)
        # Hint for matching "United States+1" style options
        region = phonenumbers.region_code_for_number(parsed)
        return f"{country_code}", national_digits or national
    except Exception:
        return "", _normalized_phone(identity)


def answer_for_field(field: dict, profile: dict) -> tuple[str, str]:
    identity = profile.get("identity", {})
    work_auth = profile.get("work_authorization", {})
    education = profile.get("education", {})
    prefs = profile.get("preferences", {})
    eeo = profile.get("eeo", {})
    custom = profile.get("custom_answers", {})
    docs = profile.get("documents", {})
    instructions = profile.get("agent_instructions", {})
    defaults = instructions.get("default_question_answers", {})

    key = field["field_key"]
    label = _normalize_label(field["label"])
    field_type = field["field_type"]

    if key == "first_name":
        return identity.get("first_name", ""), "identity.first_name"
    if key == "last_name":
        return identity.get("last_name", ""), "identity.last_name"
    if key == "email":
        return identity.get("email", ""), "identity.email"
    if key == "phone":
        _, national = _parse_phone(identity)
        return national or _normalized_phone(identity), "identity.phone"
    if key.endswith("__country") and "phone" in key:
        country_hint, _ = _parse_phone(identity)
        return country_hint, "identity.phone_country"
    if key.startswith("school--"):
        return education.get("school", ""), "education.school"
    if key.startswith("degree--"):
        return education.get("degree", ""), "education.degree"
    if key.startswith("discipline--"):
        return education.get("major", ""), "education.major"
    if key == "address":
        return identity.get("address_line_1", ""), "identity.address_line_1"
    if key in {"city", "candidate_city"}:
        return identity.get("location_city", ""), "identity.location_city"
    if key in {"state", "province", "candidate_state"}:
        return prefs.get("application_state_override") or identity.get("location_state", ""), "preferences.application_state_override"
    if key in {"postal_code", "zip", "zipcode"}:
        return identity.get("postal_code", ""), "identity.postal_code"
    if key in {"country", "candidate_country"}:
        return identity.get("country", ""), "identity.country"
    if key == "candidate-location":
        return _candidate_location_value(profile), "preferences.application_city_override"
    if key == "resume":
        return docs.get("resume_path", ""), "documents.resume_path"
    if key == "cover_letter":
        return docs.get("cover_letter_path", ""), "documents.cover_letter_path"

    if "linkedin" in label:
        return identity.get("linkedin_url", ""), "identity.linkedin_url"
    if "website" in label or "portfolio" in label:
        return identity.get("portfolio_url", "") or identity.get("github_url", ""), "identity.portfolio_url"
    if label == "country":
        return identity.get("country", ""), "identity.country"
    if label == "school":
        return education.get("school", ""), "education.school"
    if label == "degree":
        return education.get("degree", ""), "education.degree"
    if label == "discipline":
        return education.get("major", ""), "education.major"
    if label == "address":
        return identity.get("address_line_1", ""), "identity.address_line_1"
    if "city/region" in label or label == "city":
        return identity.get("location_city", ""), "identity.location_city"
    if "state/province" in label or label == "state":
        return prefs.get("application_state_override") or identity.get("location_state", ""), "preferences.application_state_override"
    if "zip code" in label or "postal code" in label:
        return identity.get("postal_code", ""), "identity.postal_code"
    if "country code" in label:
        return "US", "identity.country"
    if "authorized to work" in label:
        return defaults.get("work_authorization", "Yes"), "agent_instructions.default_question_answers.work_authorization"
    if "require sponsorship" in label or "sponsorship" in label:
        return defaults.get("sponsorship_needed", "Yes"), "agent_instructions.default_question_answers.sponsorship_needed"
    if "at least 18 years of age" in label:
        return "Yes", "agent_instructions.default_question_answers.over_18"
    if "previously worked with us" in label or "intern or co-op" in label:
        return defaults.get("worked_here_before", "No"), "agent_instructions.default_question_answers.worked_here_before"
    if "previously worked for" in label:
        return defaults.get("worked_here_before", "No"), "agent_instructions.default_question_answers.worked_here_before"
    if "worked at accenture in the past" in label:
        return "No", "agent_instructions.default_question_answers.worked_at_accenture"
    if "relocation" in label or "comfortable to be in the office" in label:
        return defaults.get("relocation", "Yes"), "agent_instructions.default_question_answers.relocation"
    if "live within 70 miles" in label:
        return "No", "agent_instructions.default_question_answers.relocation_radius"
    if "current company" in label:
        return custom.get("current_company", ""), "custom_answers.current_company"
    if (
        "noncompete" in label
        or "non-compete" in label
        or "nondisclosure" in label
        or "non-disclosure" in label
        or "confidentiality agreement" in label
    ):
        return defaults.get("noncompete", "None"), "agent_instructions.default_question_answers.noncompete"
    if "via sms" in label or "sms" in label:
        return defaults.get("sms_updates", "Yes"), "agent_instructions.default_question_answers.sms_updates"
    if "how did you hear about us" in label:
        return defaults.get("heard_about_company", "Internet"), "agent_instructions.default_question_answers.heard_about_company"
    if "recruitment marketing communications" in label or "receive email communications" in label:
        return defaults.get("recruitment_marketing_emails", "Yes"), "agent_instructions.default_question_answers.recruitment_marketing_emails"
    if "security clearance" in label:
        return defaults.get("security_clearance", "No"), "agent_instructions.default_question_answers.security_clearance"
    if "currently working on a project with accenture" in label:
        return "No", "agent_instructions.default_question_answers.current_accenture_project"
    if "government civilian or military employee" in label:
        return "No", "agent_instructions.default_question_answers.government_employee"
    if "current employee of the u.s. government" in label:
        return "No", "agent_instructions.default_question_answers.current_government_employee"
    if "serving as enlisted personnel" in label:
        return "No", "agent_instructions.default_question_answers.reserves_or_guard"
    if "within the past 10 years" in label and "u.s. government" in label:
        return "No", "agent_instructions.default_question_answers.past_government_employee"
    if "family members or people you have close relationships" in label:
        return "No", "agent_instructions.default_question_answers.family_relationship"
    if "relationship with a non-u.s. government official" in label:
        return "No", "agent_instructions.default_question_answers.foreign_official_relationship"
    if "relative employed with" in label:
        return "No", "agent_instructions.default_question_answers.relative_employed"
    if label == "affirmation":
        return "Yes", "agent_instructions.default_question_answers.affirmation"
    if "acknowledge that all information provided is accurate and true" in label:
        return "Yes", "agent_instructions.default_question_answers.affirmation"
    if "veteran" in label:
        return eeo.get("veteran_status", "") or defaults.get("veteran_status", "No"), "eeo.veteran_status"
    if "ethnicity" in label or "race" in label or "racial/ethnic" in label or "ethnic background" in label:
        return eeo.get("ethnicity", ""), "eeo.ethnicity"
    if "hispanic/latino" in label:
        return eeo.get("hispanic_latino", ""), "eeo.hispanic_latino"
    if "sexual orientation" in label:
        return eeo.get("sexual_orientation", ""), "eeo.sexual_orientation"
    if "transgender" in label:
        return eeo.get("transgender", ""), "eeo.transgender"
    if "gender" in label:
        return eeo.get("gender", ""), "eeo.gender"
    if "disability" in label:
        return eeo.get("disability_status", ""), "eeo.disability_status"
    if "visa" in label:
        return work_auth.get("current_visa_status", ""), "work_authorization.current_visa_status"
    if "salary" in label:
        return custom.get("salary_expectations", ""), "custom_answers.salary_expectations"
    if "notice period" in label:
        return custom.get("notice_period", ""), "custom_answers.notice_period"

    if field_type == "file":
        return "", ""
    return "", ""


def _ai_suggest(field: dict, job: dict, profile: dict) -> tuple[str, str]:
    """Use Groq (Llama) or Ollama for unknown field suggestions."""
    cfg = (profile.get("agent_instructions") or {}).get("ai_fallback") or {}
    if not cfg.get("enabled"):
        return "", ""
    provider = cfg.get("provider", "groq")
    model = cfg.get("model") or ("llama-3.3-70b-versatile" if provider == "groq" else "llama3.1:8b")
    prompt = (
        "You are helping fill a job application conservatively.\n"
        "Only answer if the application question can be answered from the provided profile.\n"
        "If unsure, respond with exactly UNKNOWN.\n\n"
        f"Job title: {job.get('job_title', '')}\n"
        f"Company: {job.get('company_name', '')}\n"
        f"Question label: {field.get('label', '')}\n"
        f"Applicant profile JSON: {json.dumps(profile, ensure_ascii=True)}\n"
    )
    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return "", ""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=100,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception:
            return "", ""
    else:
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
            return "", ""
    if not text or text.upper() == "UNKNOWN":
        return "", ""
    return text.splitlines()[0].strip(), f"ai_fallback.{model}"


def resolve_field_answer(field: dict, job: dict, profile: dict) -> tuple[str, str]:
    value, source = answer_for_field(field, profile)
    if value:
        return value, source
    return _ai_suggest(field, job, profile)


def build_application_plan(job: dict, profile: dict, html: str) -> dict:
    fields = parse_fields(html)
    resolved: list[dict] = []
    unresolved: list[dict] = []

    for field in fields:
        value, source = answer_for_field(field, profile)
        if not value:
            value, source = _ai_suggest(field, job, profile)
        entry = {
            "field_key": field["field_key"],
            "label": field["label"],
            "field_type": field["field_type"],
            "required": field["required"],
            "value": value,
            "source": source,
        }
        if value or not field["required"]:
            resolved.append(entry)
        else:
            unresolved.append(entry)

    return {
        "job": {
            "queue_key": job.get("queue_key", ""),
            "company_name": job.get("company_name", ""),
            "job_title": job.get("job_title", ""),
            "url": job.get("url", ""),
            "apply_target": job.get("apply_target", ""),
        },
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "resolved_fields": resolved,
        "unresolved_fields": unresolved,
        "notes": [
            profile.get("work_authorization", {}).get("work_authorization_note", ""),
            profile.get("agent_instructions", {}).get("workday_profile_note", ""),
            profile.get("agent_instructions", {}).get("date_format_note", ""),
        ],
    }


def write_session(plan: dict) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    company = re.sub(r"[^a-z0-9]+", "_", plan["job"]["company_name"].lower()).strip("_") or "company"
    title = re.sub(r"[^a-z0-9]+", "_", plan["job"]["job_title"].lower()).strip("_") or "role"
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = SESSION_DIR / f"{stamp}_{company}_{title}.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def open_in_browser(url: str) -> None:
    codex_home = os.getenv("CODEX_HOME", str(Path.home() / ".codex"))
    pwcli = Path(codex_home) / "skills" / "playwright" / "scripts" / "playwright_cli.sh"
    subprocess.run(["bash", str(pwcli), "open", url], check=True)


def load_session(path: str | Path) -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))
