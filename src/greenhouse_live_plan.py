"""Live-field extraction and answer planning for Greenhouse forms."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .answer_engine import choose_option
from .greenhouse_apply import resolve_field_answer

LIVE_PLAN_DIR = Path("output/live_field_plans")


def _normalize_bool_like(value: str) -> str:
    low = (value or "").strip().lower()
    if low in {"true", "yes"}:
        return "Yes"
    if low in {"false", "no", "none"}:
        return "No" if low != "none" else "None"
    return value


def extract_greenhouse_fields(page) -> list[dict]:
    fields = page.locator("form").evaluate(
        """(form) => {
          const out = [];
          if (!form) return out;
          for (const label of form.querySelectorAll('label[for]')) {
            const fieldId = label.getAttribute('for');
            const control = form.querySelector(`#${CSS.escape(fieldId)}`);
            if (!control) continue;
            const labelText = (label.textContent || '').replace(/\\*/g, ' ').replace(/\\s+/g, ' ').trim();
            const required = label.textContent?.includes('*') || control.getAttribute('aria-required') === 'true' || control.required;
            const tag = (control.tagName || '').toLowerCase();
            const type = tag === 'input' ? (control.getAttribute('type') || 'text') : tag;
            const describedBy = control.getAttribute('aria-describedby');
            let helperText = '';
            if (describedBy) {
              const helperNode = form.querySelector(`#${CSS.escape(describedBy)}`) || document.querySelector(`#${CSS.escape(describedBy)}`);
              helperText = (helperNode?.innerText || '').replace(/\\s+/g, ' ').trim();
            }
            const container = label.parentElement;
            const containerText = (container?.innerText || '').replace(/\\s+/g, ' ').trim();
            const options = [];
            if (container) {
              for (const optionNode of container.querySelectorAll('[role="option"], [id*="-option-"]')) {
                const text = (optionNode.innerText || optionNode.textContent || '').replace(/\\s+/g, ' ').trim();
                if (text) options.push(text);
              }
            }
            const sectionNode = label.closest('fieldset, section, .application-field, .application-question')?.parentElement;
            const sectionText = (sectionNode?.querySelector('h2, h3, legend, .section-header')?.innerText || '').replace(/\\s+/g, ' ').trim();
            out.push({
              field_key: fieldId,
              label: labelText,
              field_type: type,
              required,
              helper_text: helperText,
              section: sectionText,
              options,
              current_value: (control.value || '').trim(),
              container_text: containerText,
            });
          }
          return out;
        }"""
    )
    for field in fields:
        field["options"] = _extract_live_options(page, field)
    return fields


def _container_for_field(page, field: dict):
    field_id = field["field_key"]
    return page.locator(f'label[for="{field_id}"]').locator("xpath=..")


def _extract_live_options(page, field: dict) -> list[str]:
    field_id = field.get("field_key", "")
    if not field_id:
        return field.get("options") or []
    container = _container_for_field(page, field)
    try:
        toggle = container.get_by_role("button", name=re.compile(r"Toggle flyout", re.I)).first
        if toggle.count() == 0:
            return field.get("options") or []
        toggle.click(timeout=1200)
        page.wait_for_timeout(250)
        options = page.get_by_role("option")
        values: list[str] = []
        count = options.count()
        for i in range(count):
            text = (options.nth(i).inner_text(timeout=600) or "").strip()
            if text:
                values.append(text)
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
        return values
    except Exception:
        return field.get("options") or []


def build_live_answer_plan(fields: list[dict], job: dict, profile: dict) -> list[dict]:
    planned: list[dict] = []
    for field in fields:
        value, source = resolve_field_answer(field, job, profile)
        desired_value = value
        selected_option = ""
        options = field.get("options") or []
        if field.get("field_key") == "phone":
            options = []
        if options and value:
            selected_option = choose_option(
                field.get("label", ""), options, value, profile, field=field
            )
            desired_value = selected_option or value
        planned.append(
            {
                **field,
                "desired_value": desired_value,
                "source": source,
                "selected_option": selected_option,
                "normalized_value": _normalize_bool_like(value),
            }
        )
    return planned


def write_live_plan(session_path: Path, stage: str, payload: object) -> Path:
    LIVE_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    path = LIVE_PLAN_DIR / f"{session_path.stem}_{stage}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path
