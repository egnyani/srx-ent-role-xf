"""Generate local resume documents used by the apply runner."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESUME_DATA_PATH = Path("data/resume_data.json")
DEFAULT_RESUME_PDF_PATH = Path("output/generated_documents/Gnyani_Enugandula_Resume.pdf")

_GENERATED_RESUME_PATH: str | None = None


def _relative_repo_path(value: str | Path) -> str:
    path = Path(value)
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _documents_config(profile: dict) -> dict:
    docs = profile.get("documents", {})
    return docs if isinstance(docs, dict) else {}


def _resume_data_path(profile: dict) -> Path:
    docs = _documents_config(profile)
    configured = docs.get("resume_data_path")
    path = Path(configured) if configured else DEFAULT_RESUME_DATA_PATH
    return path if path.is_absolute() else REPO_ROOT / path


def _resume_pdf_path(profile: dict) -> Path:
    docs = _documents_config(profile)
    configured = docs.get("resume_path")
    path = Path(configured) if configured else DEFAULT_RESUME_PDF_PATH
    return path if path.is_absolute() else REPO_ROOT / path


def ensure_resume_pdf(profile: dict, *, force: bool = False) -> str:
    global _GENERATED_RESUME_PATH

    output_path = _resume_pdf_path(profile)
    if _GENERATED_RESUME_PATH and not force:
        return _GENERATED_RESUME_PATH
    if output_path.exists() and not force:
        _GENERATED_RESUME_PATH = _relative_repo_path(output_path)
        return _GENERATED_RESUME_PATH

    input_path = _resume_data_path(profile)
    if not input_path.exists():
        raise FileNotFoundError(f"Resume data JSON not found: {input_path}")

    npm_cmd = "npm.cmd" if sys.platform.startswith("win") else "npm"
    command = [
        npm_cmd,
        "run",
        "generate:resume-pdf",
        "--",
        "--input",
        _relative_repo_path(input_path),
        "--output",
        _relative_repo_path(output_path),
    ]
    subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    _GENERATED_RESUME_PATH = _relative_repo_path(output_path)
    return _GENERATED_RESUME_PATH
