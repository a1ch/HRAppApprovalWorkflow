"""
Daily "stuck item" monitor.

Scans every configured HR approval list and emails a digest of requests that
have either ERRORED or STALLED (in progress with no approver action for too
long). Driven by a timer trigger in function_app.py. Read-only against the
lists - the only thing it writes is the outbound digest email.

Env (App Settings):
  MONITOR_RECIPIENT    - who receives the digest. Default: MAIL_SENDER_ADDRESS.
  MONITOR_STALL_HOURS  - hours with no progress before "stalled". Default: 48.
  MONITOR_ALWAYS_SEND  - "true" to send even when nothing is stuck (a daily
                         "all clear"). Default: only email when there are findings.
"""

import os
import logging
from datetime import datetime, timezone

from list_configs import LIST_CONFIGS
from email_templates import EmailMessage

logger = logging.getLogger(__name__)


def _stall_hours() -> float:
    try:
        return float(os.environ.get("MONITOR_STALL_HOURS", "48") or 48)
    except ValueError:
        return 48.0


def _parse_dt(value) -> "datetime | None":
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _employee(fields: dict) -> str:
    raw = (fields.get("EmployeeNameText") or "").strip()
    if raw:
        return raw.split("<")[0].strip().strip('"').strip() or raw
    return (
        fields.get("Applicant_x0020_Name")
        or fields.get("ReplacedEmployee")
        or fields.get("Title")
        or "(unknown)"
    )


def _last_progress(fields: dict) -> "datetime | None":
    dates = [d for d in (_parse_dt(fields.get(f"ApproverStep{i}Date")) for i in range(5)) if d]
    if dates:
        return max(dates)
    return _parse_dt(fields.get("Created"))


def scan(orch) -> tuple[list[dict], list[dict]]:
    """Return (errors, stalled) lists of flagged-item dicts."""
    now = datetime.now(timezone.utc)
    threshold = _stall_hours()
    errors: list[dict] = []
    stalled: list[dict] = []

    for list_key, config in LIST_CONFIGS.items():
        try:
            items = orch.sp.get_all_items_for_list(list_key, config)
        except Exception as e:
            logger.exception("Monitor: failed to read '%s': %s", list_key, e)
            continue

        status_col = config.status_internal
        for f in items:
            status  = (f.get(status_col) or "").strip()
            err_msg = (f.get("ErrorMessage") or "").strip()
            is_error = status == config.error_status_value or bool(err_msg)
            finished = (
                status in (config.approved_status_value, config.rejected_status_value)
                or bool(f.get("FullyApprovedDate"))
            )
            picked_up = bool((f.get("WorkflowCategory") or "").strip())

            rec = {
                "list":     config.display_name,
                "id":       f.get("id", ""),
                "employee": _employee(f),
                "step":     f.get("CurrentApprovalStep", ""),
                "status":   status or "(none)",
                "error":    err_msg,
            }

            if is_error:
                errors.append(rec)
                continue
            if finished or not picked_up:
                continue

            last = _last_progress(f)
            if last is None:
                continue
            age_h = (now - last).total_seconds() / 3600.0
            if age_h > threshold:
                rec["age_hours"] = round(age_h, 1)
                stalled.append(rec)

    return errors, stalled


def _row(rec: dict, *, age: bool = False, err: bool = False) -> str:
    tail = ""
    if age:
        tail = f" &mdash; <b>stalled {rec.get('age_hours')}h</b>"
    if err and rec.get("error"):
        tail = f" &mdash; {rec['error']}"
    return (
        f"<li style='margin:4px 0;'><b>{rec['list']}</b> #{rec['id']} &mdash; "
        f"{rec['employee']} (step {rec['step']}, {rec['status']}){tail}</li>"
    )


def build_email(errors: list[dict], stalled: list[dict], recipient: str) -> EmailMessage:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    threshold = _stall_hours()
    parts = [
        "<div style=\"font-family:Arial,sans-serif;color:#1a1a1a;\">",
        f"<h2 style='margin:0 0 8px;'>HR approvals &mdash; daily monitor ({today})</h2>",
        f"<p style='margin:0 0 16px;color:#555;'>{len(errors)} errored, "
        f"{len(stalled)} stalled (&gt;{int(threshold)}h with no approver action).</p>",
    ]
    if errors:
        parts.append("<h3 style='color:#c0392b;margin:14px 0 4px;'>&#128308; Errors</h3><ul>")
        parts += [_row(r, err=True) for r in errors]
        parts.append("</ul>")
    if stalled:
        parts.append("<h3 style='color:#b8860b;margin:14px 0 4px;'>&#128993; Stalled</h3><ul>")
        parts += [_row(r, age=True) for r in stalled]
        parts.append("</ul>")
    if not errors and not stalled:
        parts.append("<p style='color:#1a7a3c;font-weight:600;'>&#9989; All clear &mdash; "
                     "no errored or stalled requests.</p>")
    parts.append("</div>")

    subject = f"HR approvals: {len(errors)} errored, {len(stalled)} stalled ({today})"
    text = (
        f"HR approvals monitor {today}: {len(errors)} errored, {len(stalled)} stalled "
        f"(>{int(threshold)}h)."
    )
    return EmailMessage(to=recipient, subject=subject, body_html="".join(parts), body_text=text)


def scan_and_notify(orch) -> None:
    errors, stalled = scan(orch)
    logger.info("Monitor: %d errored, %d stalled", len(errors), len(stalled))

    always = (os.environ.get("MONITOR_ALWAYS_SEND", "") or "").strip().lower() in ("1", "true", "yes")
    if not errors and not stalled and not always:
        return

    recipient = (os.environ.get("MONITOR_RECIPIENT", "").strip()
                 or os.environ.get("MAIL_SENDER_ADDRESS", "").strip())
    if not recipient:
        logger.warning("Monitor: no MONITOR_RECIPIENT or MAIL_SENDER_ADDRESS set - cannot send digest")
        return

    orch.mailer.send(build_email(errors, stalled, recipient))
    logger.info("Monitor: digest sent to %s", recipient)
