"""Persistent memory for question/option/answer triples seen across applications."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

MEMORY_PATH = Path("data/answer_memory.json")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _option_signature(options: list[str]) -> list[str]:
    return sorted({_norm(opt) for opt in options if (opt or "").strip()})


def _question_key(question: str, options: list[str], section: str = "") -> str:
    """Include section to distinguish EEO from non-EEO fields with same options."""
    base = f"{_norm(section)}::{_norm(question)}||{'|'.join(_option_signature(options))}"
    return base


def load_memory(path: Path = MEMORY_PATH) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_memory(memory: dict[str, dict], path: Path = MEMORY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, indent=2, ensure_ascii=True), encoding="utf-8")


def lookup_answer(question: str, options: list[str], section: str = "", path: Path = MEMORY_PATH) -> str:
    memory = load_memory(path)
    record = memory.get(_question_key(question, options, section))
    if not record:
        return ""
    if record.get("stale"):
        return ""
    return record.get("selected_option", "")


def remember_answer(
    *,
    question: str,
    options: list[str],
    selected_option: str,
    source: str,
    outcome: str = "used",
    section: str = "",
    path: Path = MEMORY_PATH,
) -> None:
    if not selected_option or not options:
        return
    memory = load_memory(path)
    key = _question_key(question, options, section)
    memory[key] = {
        "question": question,
        "options": [opt for opt in options if (opt or "").strip()],
        "selected_option": selected_option,
        "source": source,
        "outcome": outcome,
        "stale": False,
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    save_memory(memory, path)
