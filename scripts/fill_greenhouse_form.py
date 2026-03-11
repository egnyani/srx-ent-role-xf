#!/usr/bin/env python3
"""Fill a Greenhouse application form in a real browser, optionally submit it, and verify the outcome."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.answer_engine import choose_option
from src.answer_memory import remember_answer
from src.applicant_profile import load_profile
from src.application_history import append_history_event, build_history_event
from src.apply_queue import update_queue_item
from src.greenhouse_apply import SESSION_DIR, load_session, resolve_field_answer

QUESTION_DEBUG_DIR = Path("output/question_debug")


def _import_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
        return sync_playwright, PlaywrightTimeoutError
    except Exception as exc:  # pragma: no cover - dependency check
        raise SystemExit(
            "Playwright Python is not installed. Install it with:\n"
            "  .venv/bin/pip install playwright\n"
            "  .venv/bin/playwright install chromium"
        ) from exc


def _latest_session_file() -> Path | None:
    files = sorted(SESSION_DIR.glob("*.json"))
    return files[-1] if files else None


def _normalize_bool_like(value: str) -> str:
    low = (value or "").strip().lower()
    if low in {"true", "yes"}:
        return "Yes"
    if low in {"false", "no", "none"}:
        return "No" if low != "none" else "None"
    return value


def _combo_target_value(field: dict, value: str) -> str:
    label = (field.get("label") or "").lower()
    if "racial/ethnic background" in label:
        return value
    if "identify as transgender" in label:
        return value
    return _normalize_bool_like(value)


def _is_combo_field(field: dict) -> bool:
    label = (field.get("label") or "").lower()
    key = field.get("field_key") or ""
    if key == "candidate-location":
        return True
    if key.startswith("4006"):
        return True
    combo_signals = [
        "school",
        "degree",
        "discipline",
        "state",
        "country",
        "authorized to work",
        "require sponsorship",
        "worked with us",
        "comfortable to be in the office",
        "noncompete",
        "sms",
        "hear about us",
        "recruitment marketing",
        "gender",
        "race",
        "affirmation",
        "security clearance",
        "racial/ethnic",
        "sexual orientation",
        "transgender",
        "disability",
        "veteran",
    ]
    return any(signal in label for signal in combo_signals)


def _locator_for_field(page, field: dict):
    field_id = field["field_key"]
    return page.locator(f'[id="{field_id}"]')


def _container_for_field(page, field: dict):
    field_id = field["field_key"]
    return page.locator(f'label[for="{field_id}"]').locator("xpath=..")


def _has_combo_toggle(page, field: dict) -> bool:
    try:
        toggle = _container_for_field(page, field).get_by_role("button", name=re.compile(r"Toggle flyout", re.I)).first
        return toggle.count() > 0
    except Exception:
        return False


def _click_exact_option(page, option_text: str) -> bool:
    patterns = [
        page.get_by_role("option", name=re.compile(rf"^{re.escape(option_text)}$", re.I)).first,
        page.locator('[id*="-option-"]').filter(has_text=re.compile(rf"^{re.escape(option_text)}$", re.I)).first,
    ]
    for locator in patterns:
        try:
            locator.wait_for(timeout=1200)
            locator.click()
            page.wait_for_timeout(250)
            return True
        except Exception:
            continue
    return False


def _visible_options(page) -> list[str]:
    options = page.get_by_role("option")
    values: list[str] = []
    try:
        count = options.count()
    except Exception:
        return values
    for i in range(count):
        try:
            text = (options.nth(i).inner_text(timeout=800) or "").strip()
        except Exception:
            continue
        if text:
            values.append(text)
    return values


def _select_via_flyout(page, field: dict, option_text: str) -> None:
    container = _container_for_field(page, field)
    toggle = container.get_by_role("button", name=re.compile(r"Toggle flyout", re.I)).first
    toggle.click(timeout=1500)
    page.wait_for_timeout(500)
    if _click_exact_option(page, option_text.strip()):
        return
    raise RuntimeError(f"Could not select option: {option_text}")


def _select_option_id(page, field: dict, option_index: int) -> None:
    container = _container_for_field(page, field)
    toggle = container.get_by_role("button", name=re.compile(r"Toggle flyout", re.I)).first
    toggle.click(timeout=1500)
    page.wait_for_timeout(400)
    option_id = f'react-select-{field["field_key"]}-option-{option_index}'
    option = page.locator(f'[id="{option_id}"]').first
    option.wait_for(timeout=1500)
    option.evaluate("(el) => el.click()")
    page.wait_for_timeout(250)


def _select_option_id_verified(page, field: dict, option_index: int, expected_text: str) -> None:
    _select_option_id(page, field, option_index)
    container = _container_for_field(page, field)
    page.wait_for_timeout(500)
    if expected_text.lower() in (container.inner_text(timeout=1500) or "").lower():
        return
    raise RuntimeError(f"Option did not stick for {field['field_key']}: {expected_text}")


def _select_first_matching_option(page, field: dict, expected_texts: list[str], contains_token: str | None = None) -> None:
    container = _container_for_field(page, field)
    toggle = container.get_by_role("button", name=re.compile(r"Toggle flyout", re.I)).first
    toggle.click(timeout=1500)
    page.wait_for_timeout(400)

    for text in expected_texts:
        if _click_exact_option(page, text):
            page.wait_for_timeout(400)
            if text.lower() in (container.inner_text(timeout=1500) or "").lower():
                return

    if contains_token:
        options = page.get_by_role("option")
        count = options.count()
        token = contains_token.lower()
        for i in range(count):
            option = options.nth(i)
            option_text = (option.inner_text(timeout=1000) or "").strip()
            if token in option_text.lower():
                option.evaluate("(el) => el.click()")
                page.wait_for_timeout(400)
                if option_text.lower() in (container.inner_text(timeout=1500) or "").lower():
                    return

    raise RuntimeError(
        f"Could not select matching option for {field['field_key']}: "
        f"{expected_texts} / contains {contains_token}"
    )


def _fill_combo(page, field: dict, value: str, profile: dict) -> None:
    locator = _locator_for_field(page, field)
    container = _container_for_field(page, field)
    toggle = container.get_by_role("button", name=re.compile(r"Toggle flyout", re.I)).first
    try:
        toggle.click(timeout=800)
        page.wait_for_timeout(250)
    except Exception:
        locator.click()

    locator.fill("")
    locator.fill(value)
    page.wait_for_timeout(600)

    options = _visible_options(page)
    chosen = choose_option(field.get("label", ""), options, value.strip(), profile) if options else value.strip()

    if _click_exact_option(page, chosen):
        container_text = (container.inner_text(timeout=1500) or "").lower()
        if chosen.lower() in container_text:
            remember_answer(
                question=field.get("label", ""),
                options=options,
                selected_option=chosen,
                source="live_fill",
                section=field.get("section", ""),
            )
            return
        raise RuntimeError(f"Option click did not stick for {field['label']}: {chosen}")

    locator.press("ArrowDown")
    locator.press("Enter")
    page.wait_for_timeout(400)
    container_text = (container.inner_text(timeout=1500) or "").lower()
    if chosen.lower() in container_text:
        remember_answer(
            question=field.get("label", ""),
            options=options,
            selected_option=chosen,
            source="live_fill",
            section=field.get("section", ""),
        )
        return
    raise RuntimeError(f"Combo value did not stick for {field['label']}: {chosen}")


def _get_phone_country_and_number(profile: dict) -> tuple[str, str]:
    """Return (country_hint, national_number) for composite phone fields."""
    raw = (profile.get("identity") or {}).get("phone") or ""
    if not raw.strip():
        return "", ""
    try:
        import phonenumbers
        parsed = phonenumbers.parse(raw.strip(), None)
        country_code = f"+{parsed.country_code}"
        national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
        national_digits = re.sub(r"\D", "", national)
        return country_code, national_digits or national
    except Exception:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return "+1", digits or raw


def _fill_phone_composite(page, field: dict, value: str, profile: dict) -> None:
    """Fill composite phone: select country first, then fill national number."""
    country_hint, national_number = _get_phone_country_and_number(profile)
    if not national_number:
        national_number = value
    container = _container_for_field(page, field)
    locator = _locator_for_field(page, field)
    try:
        toggle = container.get_by_role("button", name=re.compile(r"Toggle flyout", re.I)).first
        if toggle.count() > 0:
            toggle.click(timeout=1500)
            page.wait_for_timeout(400)
            options = _visible_options(page)
            if options and any("+" in (o or "") for o in options[:5]):
                chosen = choose_option(
                    field.get("label", ""), options, country_hint, profile, field=field
                )
                if chosen and _click_exact_option(page, chosen):
                    page.wait_for_timeout(400)
    except Exception:
        pass
    locator.fill("")
    locator.fill(national_number)


def _fill_location(page, field: dict, value: str) -> None:
    locate_button = page.get_by_role("button", name=re.compile(r"Locate me", re.I)).first
    locator = _locator_for_field(page, field)
    container = _container_for_field(page, field)
    target_value = (value or "").strip()
    try:
        locate_button.click(force=True, timeout=2000)
        page.wait_for_timeout(2500)
        current_value = (locator.input_value() or "").strip()
    except Exception as exc:
        current_value = ""

    container_text = (container.inner_text(timeout=1000) or "").strip().lower()
    if current_value or target_value.lower() in container_text:
        return

    locator.click(timeout=1500)
    locator.fill("")
    locator.fill(target_value)
    page.wait_for_timeout(900)
    if _click_exact_option(page, target_value):
        page.wait_for_timeout(400)
        current_value = (locator.input_value() or "").strip()
        container_text = (container.inner_text(timeout=1000) or "").strip().lower()
        if current_value or target_value.lower() in container_text:
            return

    raise RuntimeError("Location (City) did not populate from Locate me or exact suggestion selection")


def _fill_special_eeo(page, field: dict, value: str, profile: dict) -> None:
    if field["field_key"] == "4006106006":
        _select_first_matching_option(page, field, ["South Asian", "Asian"], contains_token="Asian")
        return
    if field["field_key"] == "4006108006":
        _fill_combo(page, field, value, profile)
        return
    _fill_combo(page, field, value, profile)


def _fill_text(page, field: dict, value: str) -> None:
    _locator_for_field(page, field).fill(value)


def _fill_file(page, field: dict, value: str) -> None:
    file_path = (REPO_ROOT / value).resolve() if not Path(value).is_absolute() else Path(value)
    _locator_for_field(page, field).set_input_files(str(file_path))


def _extract_required_unanswered_fields(page) -> list[dict]:
    return page.locator("form").evaluate(
        """(form) => {
          const out = [];
          if (!form) return out;
          for (const label of form.querySelectorAll('label[for]')) {
            const fieldId = label.getAttribute('for');
            const control = form.querySelector(`#${CSS.escape(fieldId)}`);
            if (!control) continue;
            const labelText = (label.textContent || '').replace(/\\*/g, ' ').replace(/\\s+/g, ' ').trim();
            const required = label.textContent?.includes('*') || control.getAttribute('aria-required') === 'true' || control.required;
            if (!required) continue;
            const tag = (control.tagName || '').toLowerCase();
            const type = tag === 'input' ? (control.getAttribute('type') || 'text') : tag;
            let currentValue = '';
            if (type === 'file') {
              currentValue = (control.files && control.files.length) ? 'attached' : '';
            } else {
              currentValue = (control.value || '').trim();
            }
            const container = label.parentElement;
            const containerText = (container?.innerText || '').replace(/\\s+/g, ' ').trim();
            const normalizedLabel = labelText.replace(/\\s+/g, ' ').trim();
            const normalizedContainer = containerText.replace(normalizedLabel, '').trim();
            const unansweredPlaceholder = /^select\\.{0,3}$/i.test(normalizedContainer) || normalizedContainer === '';
            const empty = !currentValue && unansweredPlaceholder;
            if (!empty) continue;
            const describedBy = control.getAttribute('aria-describedby');
            let helperText = '';
            if (describedBy) {
              const helperNode = form.querySelector(`#${CSS.escape(describedBy)}`) || document.querySelector(`#${CSS.escape(describedBy)}`);
              helperText = (helperNode?.innerText || '').replace(/\\s+/g, ' ').trim();
            }
            const options = [];
            if (container) {
              for (const optionNode of container.querySelectorAll('[role="option"], [id*="-option-"]')) {
                const text = (optionNode.innerText || optionNode.textContent || '').replace(/\\s+/g, ' ').trim();
                if (text) options.push(text);
              }
            }
            out.push({
              field_key: fieldId,
              label: labelText,
              field_type: type,
              required: true,
              helper_text: helperText,
              options,
            });
          }
          return out;
        }"""
    )


def _write_question_debug(session_path: Path, stage: str, questions: list[dict]) -> None:
    QUESTION_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = QUESTION_DEBUG_DIR / f"{session_path.stem}_{stage}.json"
    path.write_text(json.dumps(questions, indent=2, ensure_ascii=True), encoding="utf-8")


def _fill_field(page, field: dict, value: str, profile: dict) -> None:
    if field["field_type"] == "file":
        _fill_file(page, field, value)
    elif field["field_key"] == "candidate-location":
        _fill_location(page, field, value)
    elif field["field_key"] in {"4006106006", "4006108006"}:
        _fill_special_eeo(page, field, value, profile)
    elif field["field_key"] == "phone" and _has_combo_toggle(page, field):
        _fill_phone_composite(page, field, value, profile)
    elif _is_combo_field(field) or _has_combo_toggle(page, field):
        _fill_combo(page, field, _combo_target_value(field, value), profile)
    else:
        _fill_text(page, field, value)


def _second_pass_fill(page, plan: dict, profile: dict) -> tuple[list[str], list[dict]]:
    extra_filled: list[str] = []
    extra_failed: list[dict] = []
    questions = _extract_required_unanswered_fields(page)
    _write_question_debug(Path(plan.get("session_path", "")) if plan.get("session_path") else Path("session.json"), "unanswered_before_second_pass", questions)
    for field in questions:
        value, _ = resolve_field_answer(field, plan["job"], profile)
        if not value:
            continue
        try:
            _fill_field(page, field, value, profile)
            extra_filled.append(field["label"])
            page.wait_for_timeout(150)
        except Exception as exc:
            extra_failed.append({"label": field["label"], "error": f"second-pass: {exc}"})
    return extra_filled, extra_failed


def _submit_button_candidates(page) -> list:
    return [
        page.get_by_role("button", name=re.compile(r"submit application", re.I)).first,
        page.get_by_role("button", name=re.compile(r"submit", re.I)).first,
        page.locator('button[type="submit"]').first,
        page.locator('input[type="submit"]').first,
    ]


def _body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def _detect_submit_outcome(page) -> tuple[str, str]:
    current_url = page.url.lower()
    body_text = _body_text(page).lower()

    if any(
        signal in body_text
        for signal in {
            "application submitted",
            "your application has been submitted",
            "thank you for applying",
            "thanks for applying",
            "we have received your application",
            "application received",
        }
    ) or "/thank_you" in current_url:
        return "submitted", "Submission confirmation detected on the Greenhouse success page."

    if any(
        signal in body_text
        for signal in {
            "verification code",
            "enter the code",
            "check your email",
            "one-time code",
            "confirm your email",
            "verify your email",
        }
    ):
        return "needs_email_code", "Greenhouse is asking for email verification or a one-time code."

    validation_error_signals = {
        "this field is required",
        "please enter a valid",
        "please select",
        "please complete",
        "please answer",
        "there was a problem",
        "there was an error",
    }
    if any(signal in body_text for signal in validation_error_signals):
        return "failed", "Submit clicked, but Greenhouse still shows inline validation errors."

    invalid_controls = page.locator('[aria-invalid="true"], .field-error, .error, [data-testid*="error"]')
    try:
        if invalid_controls.count() > 0:
            return "failed", "Submit clicked, but Greenhouse still shows invalid form controls."
    except Exception:
        pass

    return "submitted", "Submit clicked and no post-submit validation or email-code checkpoint was detected."


def _submit_application(page) -> tuple[str, str]:
    last_error = ""
    for locator in _submit_button_candidates(page):
        try:
            locator.wait_for(timeout=2500)
            locator.click(timeout=2500)
            page.wait_for_load_state("networkidle", timeout=10000)
            page.wait_for_timeout(1500)
            return _detect_submit_outcome(page)
        except Exception as exc:
            last_error = str(exc)
            continue
    return "failed", f"Could not click a Greenhouse submit button: {last_error or 'submit control not found'}"


def fill_session(session_path: Path, review_wait: bool, submit: bool) -> None:
    sync_playwright, PlaywrightTimeoutError = _import_playwright()
    plan = load_session(session_path)
    plan["session_path"] = str(session_path)
    profile = load_profile()
    job = plan["job"]
    queue_key = job.get("queue_key", "") or job.get("url", "")
    filled = []
    failed = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            geolocation={"latitude": 43.0392, "longitude": -76.1351},
            permissions=["geolocation"],
        )
        page = context.new_page()
        page.goto(job["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        for field in plan.get("resolved_fields", []):
            value = field.get("value", "")
            if not value:
                continue
            try:
                _fill_field(page, field, value, profile)
                filled.append(field["label"])
                page.wait_for_timeout(150)
            except PlaywrightTimeoutError as exc:
                failed.append({"label": field["label"], "error": f"timeout: {exc}"})
            except Exception as exc:  # pragma: no cover - browser variance
                failed.append({"label": field["label"], "error": str(exc)})

        extra_filled, extra_failed = _second_pass_fill(page, plan, profile)
        filled.extend(extra_filled)
        failed.extend(extra_failed)

        print(f"Filled fields: {len(filled)}")
        if failed:
            print("Fields that still need manual attention:")
            for item in failed:
                print(f"- {item['label']}: {item['error']}")

        status = "filled_for_review" if not failed else "needs_manual_review"
        note = (
            f"Filled {len(filled)} fields; browser left open for review."
            if not failed
            else f"Filled {len(filled)} fields; {len(failed)} fields still need manual attention."
        )
        event_type = "form_filled"

        if submit and not failed:
            status, note = _submit_application(page)
            event_type = "application_submitted" if status == "submitted" else "submit_attempted"

        append_history_event(
            build_history_event(
                event_type=event_type,
                status=status,
                plan=plan,
                session_path=session_path,
                queue_key=queue_key,
                notes=note,
                errors=failed,
            )
        )
        if queue_key:
            update_queue_item(
                queue_key,
                status=status,
                notes=note,
            )

        if submit:
            print(f"\nSubmit result: {status}")
            print(note)
        else:
            print("\nBrowser left open for review. Do not submit blindly.")

        if review_wait and status != "submitted":
            input("Press Enter here after you finish reviewing the form...")
        context.close()
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill a Greenhouse form from the latest session plan")
    parser.add_argument("--session", help="Path to a session JSON file")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for terminal confirmation before closing the browser")
    parser.add_argument("--submit", action="store_true", help="Submit the application after fill and verify the outcome")
    args = parser.parse_args()

    session_path = Path(args.session) if args.session else _latest_session_file()
    if not session_path or not session_path.exists():
        print("No session file found. Run scripts/run_greenhouse_apply.py first.")
        return 1

    fill_session(session_path, review_wait=not args.no_wait, submit=args.submit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
