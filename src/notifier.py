"""Email notifier — sends a digest when new jobs are found (via Resend)."""

import logging
import os

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY")) and bool(os.environ.get("NOTIFY_EMAIL"))


def send_new_jobs_email(new_jobs: list[dict], total_jobs: int, excel_path: str) -> None:
    """Send a digest email listing new jobs via Resend. No-ops if not configured."""
    if not new_jobs:
        return

    api_key = os.environ.get("RESEND_API_KEY", "")
    recipient = os.environ.get("NOTIFY_EMAIL", "")
    if not api_key or not recipient:
        logger.debug("[NOTIFY] Resend not configured — skipping notification")
        return

    try:
        import resend
    except ImportError:
        logger.warning("[NOTIFY] resend package not installed — run: pip install resend")
        return

    resend.api_key = api_key

    n = len(new_jobs)
    subject = f"🆕 {n} new job{'s' if n != 1 else ''} found – Entry-Level SWE Scraper"

    # Jobs are already sorted by score from main.py; cap email at 50 rows
    rows_html = ""
    for j in new_jobs[:50]:
        title   = j.get("job_title")    or "—"
        company = j.get("company_name") or "—"
        location= j.get("location")     or "—"
        url     = j.get("url")          or ""
        date    = j.get("date_posted")  or "—"
        score   = j.get("score")
        link    = f'<a href="{url}" style="color:#0563C1">{title}</a>' if url else title

        # Score badge colour: green ≥70, orange 40-69, grey <40
        if score is not None:
            if score >= 70:
                badge_bg, badge_fg = "#d4edda", "#155724"
            elif score >= 40:
                badge_bg, badge_fg = "#fff3cd", "#856404"
            else:
                badge_bg, badge_fg = "#f0f0f0", "#555"
            score_badge = (
                f'<span style="background:{badge_bg};color:{badge_fg};'
                f'border-radius:10px;padding:2px 8px;font-size:11px;'
                f'font-weight:bold">{score}%</span>'
            )
        else:
            score_badge = "—"

        rows_html += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{link}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{company}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{location}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:center">{score_badge}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{date}</td>
        </tr>"""

    overflow = ""
    if len(new_jobs) > 50:
        overflow = (
            f'<p style="color:#888">…and {len(new_jobs) - 50} more. '
            f'Open the Excel file for the full list.</p>'
        )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:860px;margin:auto">
      <h2 style="color:#2E4057">{n} New Job{'s' if n != 1 else ''} Added</h2>
      <p>Total jobs in tracker: <strong>{total_jobs}</strong><br>
         File: <code>{excel_path}</code></p>
      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead>
          <tr style="background:#2E4057;color:#fff">
            <th style="padding:8px 10px;text-align:left">Job Title</th>
            <th style="padding:8px 10px;text-align:left">Company</th>
            <th style="padding:8px 10px;text-align:left">Location</th>
            <th style="padding:8px 10px;text-align:center">Match</th>
            <th style="padding:8px 10px;text-align:left">Posted</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      {overflow}
      <p style="color:#aaa;font-size:11px;margin-top:24px">
        Sent by your Entry-Level SWE Job Scraper
      </p>
    </body></html>"""

    try:
        resend.Emails.send({
            "from": "Job Scraper <onboarding@resend.dev>",
            "to": [recipient],
            "subject": subject,
            "html": html,
        })
        logger.info("[NOTIFY] Email sent to %s (%d new jobs)", recipient, n)
    except Exception as e:
        logger.warning("[NOTIFY] Failed to send email: %s", e)
