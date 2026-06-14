"""
Approval escalation - reminders + a final notice. NON-destructive: nothing is
ever auto-cancelled.

Once a day, for every in-progress request, it looks at how long the request has
sat with no approver action and:
  * at each ESCALATION_REMINDER_DAYS threshold (default 7 and 14) re-sends the
    pending approver their approve/reject email, flagged as a reminder;
  * at ESCALATION_FINAL_DAYS (default 30) emails HR + the initiator that the
    request has been pending that long (still open, not cancelled).

Idempotent via the per-item EscalationStage column - the highest threshold (in
days) already actioned. The clock resets automatically when the request advances
a step: its "last progress" timestamp moves forward, so the age drops below the
recorded stage and the stage is cleared.

Env (App Settings):
  ESCALATION_REMINDER_DAYS - comma list, default "7,14"
  ESCALATION_FINAL_DAYS    - single number, default "30"
  ESCALATION_HR_RECIPIENT  - HR mailbox for the final notice
                             (default: MONITOR_RECIPIENT or MAIL_SENDER_ADDRESS)
"""

import os
import logging
from datetime import datetime, timezone

from list_configs import LIST_CONFIGS
from approval_matrix import get_workflow
from email_templates import EmailMessage
from orchestrator import resolve_role
from monitor import _last_progress

logger = logging.getLogger(__name__)


def _reminder_days() -> list[int]:
    raw = os.environ.get("ESCALATION_REMINDER_DAYS", "7,14") or "7,14"
    out = [int(p.strip()) for p in raw.split(",") if p.strip().isdigit()]
    return sorted(set(out))


def _final_days() -> int:
    try:
        return int(os.environ.get("ESCALATION_FINAL_DAYS", "30") or 30)
    except ValueError:
        return 30


def _chain(workflow) -> list[str]:
    return list(workflow.approval_chain) + (["CEO"] if workflow.requires_ceo else [])


def _build_final_notice(details: dict, request_type: str, days: int,
                        approver_name: str, recipient: str) -> EmailMessage:
    emp  = details.get("employee_name") or "(unknown)"
    appr = approver_name or "the current approver"
    html = (
        "<div style=\"font-family:Arial,sans-serif;color:#1a1a1a;\">"
        f"<h2 style='margin:0 0 8px;'>HR request pending {days} days</h2>"
        f"<p>The request below has been awaiting approval for <b>{days} days</b> "
        "with no decision and may need a nudge:</p>"
        "<table style='border-collapse:collapse;font-size:14px;'>"
        f"<tr><td style='padding:2px 12px 2px 0;color:#666;'>Request</td><td>{request_type}</td></tr>"
        f"<tr><td style='padding:2px 12px 2px 0;color:#666;'>Employee</td><td>{emp}</td></tr>"
        f"<tr><td style='padding:2px 12px 2px 0;color:#666;'>Waiting on</td><td>{appr}</td></tr>"
        "</table>"
        "<p style='color:#555;margin-top:14px;'>This is a notification only - the request "
        "has <b>not</b> been cancelled and remains open for approval.</p>"
        "</div>"
    )
    text = (f"HR request pending {days} days: {request_type} for {emp}, waiting on {appr}. "
            "Not cancelled - still open for approval.")
    return EmailMessage(
        to=recipient,
        subject=f"Pending {days} days: {request_type} - {emp}",
        body_html=html,
        body_text=text,
    )


def run(orch) -> None:
    now        = datetime.now(timezone.utc)
    reminders  = _reminder_days()
    final      = _final_days()
    thresholds = sorted(set(reminders + [final]))
    hr_recipient = (
        os.environ.get("ESCALATION_HR_RECIPIENT", "").strip()
        or os.environ.get("MONITOR_RECIPIENT", "").strip()
        or os.environ.get("MAIL_SENDER_ADDRESS", "").strip()
    )

    reminders_sent = 0
    finals_sent    = 0

    for list_key, config in LIST_CONFIGS.items():
        try:
            items = orch.sp.get_all_items_for_list(list_key, config)
        except Exception as e:
            logger.exception("Escalation: failed to read '%s': %s", list_key, e)
            continue

        status_col = config.status_internal
        for f in items:
            status = (f.get(status_col) or "").strip()
            if status in (config.approved_status_value, config.rejected_status_value,
                          config.error_status_value):
                continue
            if f.get("FullyApprovedDate") or (f.get("ErrorMessage") or "").strip():
                continue
            if not (f.get("WorkflowCategory") or "").strip():
                continue

            workflow = get_workflow(f.get("WorkflowKey", ""))
            if not workflow:
                continue
            chain = _chain(workflow)
            step  = int(f.get("CurrentApprovalStep", 0) or 0)
            if step >= len(chain):
                continue

            last = _last_progress(f)
            if last is None:
                continue
            age_days = (now - last).total_seconds() / 86400.0

            try:
                stage = int(float(f.get("EscalationStage") or 0))
            except (TypeError, ValueError):
                stage = 0

            item_id = f["id"]

            # Reset the stage if the request progressed since we last escalated.
            if stage and age_days < stage:
                stage = 0
                try:
                    orch.sp.update_item(item_id, {"EscalationStage": 0}, config.display_name)
                except Exception:
                    pass

            new_stage = stage
            is_final  = False
            for th in thresholds:
                if age_days >= th and th > new_stage:
                    new_stage = th
                    is_final  = th >= final
            if new_stage <= stage:
                continue

            try:
                if is_final:
                    details = orch._extract_request_details(f, workflow, config)
                    try:
                        appr_name, _ = resolve_role(chain[step], f)
                    except Exception:
                        appr_name = ""
                    targets = [t for t in {hr_recipient, (f.get("InitiatorEmail") or "").strip()} if t]
                    for t in targets:
                        orch.mailer.send(_build_final_notice(details, workflow.request_type,
                                                             new_stage, appr_name, t))
                    finals_sent += 1
                    logger.info("Escalation: %d-day notice for %s (%s)", new_stage, item_id, list_key)
                else:
                    if orch.send_step_reminder(item_id, f, config, new_stage):
                        reminders_sent += 1
                        logger.info("Escalation: %d-day reminder for %s (%s)", new_stage, item_id, list_key)
                orch.sp.update_item(item_id, {"EscalationStage": new_stage}, config.display_name)
            except Exception as e:
                logger.exception("Escalation: failed for %s in '%s': %s", item_id, list_key, e)

    logger.info("Escalation run: %d reminders, %d final notices", reminders_sent, finals_sent)
