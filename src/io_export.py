"""Export filtered jobs to Excel, with read-back for deduplication."""

import os
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

COLUMNS = ["company_name", "job_title", "location", "url", "source"]
MAX_WIDTH = 60
PADDING = 4


def load_existing_jobs(path: str) -> list[dict]:
    """
    Read jobs already saved in an Excel file.
    Returns an empty list if the file doesn't exist or can't be read.
    """
    if not Path(path).exists():
        return []
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception:
        return []
    if not rows:
        return []
    # First row is the header
    header = [str(c).lower() if c else "" for c in rows[0]]
    jobs = []
    for row in rows[1:]:
        job = {header[i]: (row[i] or "") for i in range(len(header))}
        jobs.append(job)
    return jobs


def export_to_excel(jobs: list[dict], path: str) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    for c, col in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=col)
        cell.font = Font(bold=True)
    for r, job in enumerate(jobs, start=2):
        for c, col in enumerate(COLUMNS, start=1):
            ws.cell(row=r, column=c, value=job.get(col, ""))
    for c in range(1, len(COLUMNS) + 1):
        max_len = 0
        for r in range(1, ws.max_row + 1):
            val = ws.cell(row=r, column=c).value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        width = min(max_len + PADDING, MAX_WIDTH)
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = width
    wb.save(path)
