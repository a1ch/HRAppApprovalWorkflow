"""
Email template engine for HR approval workflows.
Generates HTML + plain text emails for each stage of the approval chain.

Design matches the Stream-Flo Group "SharePoint Daily Digest" emails:
  - ALL styling is inline (no <style> block) so Outlook/Gmail don't strip it.
  - Table-based 600px layout, rendered consistently across clients.
  - 'color-scheme: light only' meta prevents dark-mode colour inversion
    (the cause of the old black-on-navy illegibility).
  - Heavy Arial Black font stack applied per element (brand face).
  - Navy (#003366) accent + tri-colour group ribbon.
"""

from dataclasses import dataclass
from urllib.parse import urlencode
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
    _MT = ZoneInfo("America/Denver")
except Exception:
    _MT = timezone.utc


def _fmt_dt(value) -> str:
    """Render an ISO/UTC datetime as friendly Mountain Time, e.g. 'Jun 13, 2026 at 6:40 PM MDT'.
    Date-only / midnight values render as just 'Jun 13, 2026'. Unparseable values pass through."""
    if not value:
        return "&mdash;"
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_MT)
    if (local.hour, local.minute, local.second) == (0, 0, 0):
        return local.strftime(f"%b {local.day}, %Y")
    hour12 = local.strftime("%I").lstrip("0") or "12"
    return local.strftime(f"%b {local.day}, %Y at {hour12}:%M %p %Z")


# ── Brand palette (from the SharePoint Daily Digest) ───────────────────────
GROUP_NAME   = "Stream-Flo Group of Companies"
ACCENT       = "#003366"   # navy
ACCENT_DARK  = "#002449"   # darkened navy (header gradient base + sub-bar)
ACCENT_SOFT  = "#E6EBF0"   # light navy tint (count/chip backgrounds)
HEAD_FONT    = "'Arial Black','Segoe UI',Arial,sans-serif"
GROUP_BRANDS = [("#003366"), ("#0066b3"), ("#0d7a7a")]  # tri-colour ribbon

GREEN = "#1a7a3c"
RED   = "#c0392b"
INK   = "#0f172a"
BODY  = "#1e293b"
MUTE  = "#64748b"
FAINT = "#94a3b8"


@dataclass
class EmailMessage:
    to: str
    subject: str
    body_html: str
    body_text: str


def _approval_link(base_url: str, request_id: str, approver_email: str, action: str, list_key: str = "") -> str:
    params = urlencode({
        "request_id": request_id,
        "approver":   approver_email,
        "action":     action,
        "list_key":   list_key,
    })
    return f"{base_url}/api/approval-action?{params}"


def _wrap(eyebrow: str, inner_html: str) -> str:
    """Full HTML document: tri-colour ribbon, navy header, sub-bar, body, footer.
    All inline-styled and table-based to render consistently across email clients."""
    ribbon = "".join(
        f'<td style="height:6px;line-height:6px;font-size:0;background:{c};">&nbsp;</td>'
        for c in GROUP_BRANDS
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="color-scheme" content="light only"/>
<title>{eyebrow}</title></head>
<body style="margin:0;padding:0;width:100%;background:#eef2f7;font-family:{HEAD_FONT};font-size:15px;line-height:1.5;color:{BODY};-webkit-font-smoothing:antialiased;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;padding:32px 16px;"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px;background:#ffffff;border-radius:14px;border:1px solid #e3e8ef;box-shadow:0 8px 24px rgba(15,23,42,0.08);overflow:hidden;">
  <tr><td style="padding:0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>{ribbon}</tr></table></td></tr>
  <tr><td style="background-color:{ACCENT};background-image:linear-gradient(135deg,{ACCENT} 0%,{ACCENT_DARK} 100%);padding:30px 36px 26px;">
    <div style="font-family:{HEAD_FONT};font-size:23px;font-weight:800;letter-spacing:0.2px;color:#ffffff;line-height:1.15;">{GROUP_NAME}</div>
    <div style="width:46px;height:3px;background:rgba(255,255,255,0.55);border-radius:2px;margin:13px 0 0;"></div>
  </td></tr>
  <tr><td style="background:{ACCENT_DARK};padding:9px 36px;">
    <span style="font-family:{HEAD_FONT};color:rgba(255,255,255,0.92);font-size:11px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;">{eyebrow}</span>
  </td></tr>
  <tr><td style="padding:28px 36px 8px;">{inner_html}</td></tr>
  <tr><td style="padding:22px 36px 26px;background:#fafbfc;border-top:1px solid #eceff4;">
    <div style="font-family:{HEAD_FONT};font-size:11px;color:{FAINT};line-height:1.6;">This is an automated message from the Stream-Flo Group of Companies HR Approval System. Please do not reply to this email.</div>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""


def _detail_card(rows: list) -> str:
    """rows: list of (label, value_html). Renders the navy-bordered summary card."""
    cells = ""
    for i, (label, value) in enumerate(rows):
        pad = "0" if i == len(rows) - 1 else "0 0 9px"
        cells += (
            f'<tr><td style="font-family:{HEAD_FONT};padding:{pad};width:150px;color:{MUTE};font-weight:700;vertical-align:top;font-size:13px;">{label}</td>'
            f'<td style="font-family:{HEAD_FONT};padding:{pad};color:{BODY};vertical-align:top;font-size:13px;">{value}</td></tr>'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin:18px 0 0;background:#f8fafc;border:1px solid #e6ebf2;border-left:4px solid {ACCENT};border-radius:10px;"><tr><td style="padding:16px 18px;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'{cells}</table></td></tr></table>'
    )


def _button(url: str, label: str, bg: str, fg: str, border: str = "") -> str:
    """Bulletproof-ish table button (Outlook renders padding on the cell, not the <a>)."""
    brd = f"border:2px solid {border};" if border else ""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="display:inline-block;margin:0 10px 0 0;">'
        f'<tr><td style="background:{bg};border-radius:8px;{brd}">'
        f'<a href="{url}" style="font-family:{HEAD_FONT};display:inline-block;padding:12px 28px;font-size:14px;font-weight:700;color:{fg};text-decoration:none;letter-spacing:0.2px;">{label}</a>'
        '</td></tr></table>'
    )


def build_approver_email(
    base_url: str,
    request_id: str,
    approver_name: str,
    approver_email: str,
    request_details: dict,
    workflow_name: str,
    approval_chain: list,
    current_step: int,
    previous_approvals: list,
    list_key: str = "",
) -> EmailMessage:
    """Email sent to each approver in sequence."""

    employee  = request_details.get("employee_name", "[Employee]")
    req_type  = request_details.get("request_type", workflow_name)
    initiator = request_details.get("initiator_name", "[Initiator]")
    submitted = _fmt_dt(request_details.get("submitted_date", ""))
    notes     = request_details.get("notes", "")

    approve_url = _approval_link(base_url, request_id, approver_email, "approve", list_key)
    reject_url  = _approval_link(base_url, request_id, approver_email, "reject", list_key)

    # Approval chain progress (coloured dot + label, inline styled)
    chain_rows = ""
    for i, role in enumerate(approval_chain):
        if i < current_step:
            dot, label = GREEN, f'{role} — <span style="color:{GREEN};font-weight:700;">Approved</span>'
            if i < len(previous_approvals):
                label += f' by {previous_approvals[i].get("name", role)}'
        elif i == current_step:
            dot, label = ACCENT, f'<strong style="color:{INK};">{role} — Awaiting your decision</strong>'
        else:
            dot, label = "#cbd5e1", f'<span style="color:{MUTE};">{role} — Pending</span>'
        chain_rows += (
            f'<tr><td style="width:18px;vertical-align:middle;padding:3px 0;"><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:{dot};"></span></td>'
            f'<td style="font-family:{HEAD_FONT};font-size:13px;padding:3px 0;vertical-align:middle;">{label}</td></tr>'
        )
    chain_html = f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:6px 0 0;">{chain_rows}</table>'

    rows = [
        ("Request type", req_type),
        ("Employee", employee),
        ("Initiated by", initiator),
        ("Submitted", submitted),
    ]
    if notes:
        rows.append(("Notes", notes))

    inner = f"""
<div style="font-family:{HEAD_FONT};font-size:16px;color:{INK};margin:0 0 6px;">Hi {approver_name},</div>
<div style="font-family:{HEAD_FONT};font-size:14px;color:{BODY};">An HR request needs your approval &mdash; step {current_step + 1} of {len(approval_chain)}.</div>
<span style="font-family:{HEAD_FONT};display:inline-block;background:{ACCENT_SOFT};color:{ACCENT};font-size:12px;font-weight:700;letter-spacing:0.3px;padding:6px 14px;border-radius:999px;margin:16px 0 0;">Action required</span>
{_detail_card(rows)}
<div style="font-family:{HEAD_FONT};font-size:11px;font-weight:700;letter-spacing:1.3px;text-transform:uppercase;color:{FAINT};margin:24px 0 2px;">Approval chain</div>
{chain_html}
<div style="font-family:{HEAD_FONT};font-size:14px;color:{BODY};margin:26px 0 14px;">Please review and choose:</div>
<div>{_button(approve_url, "Approve", GREEN, "#ffffff")}{_button(reject_url, "Reject", "#ffffff", RED, border=RED)}</div>
<div style="font-family:{HEAD_FONT};font-size:12px;color:{FAINT};margin-top:22px;line-height:1.6;">
  Approve records your decision immediately. Reject will ask for a reason first.<br>Request ID: {request_id}
</div>
"""

    subject = f"Action required: {req_type} — {employee}"
    return EmailMessage(
        to=approver_email,
        subject=subject,
        body_html=_wrap("HR Approvals", inner),
        body_text=(
            f"Hi {approver_name},\n\nAn HR request requires your approval (step {current_step + 1} of {len(approval_chain)}).\n\n"
            f"Request: {req_type}\nEmployee: {employee}\nInitiated by: {initiator}\n\n"
            f"Approve: {approve_url}\nReject: {reject_url}\n\nRequest ID: {request_id}"
        ),
    )


def build_notify_email(
    notify_name: str,
    notify_email: str,
    request_details: dict,
    workflow_name: str,
    notify_role: str,
) -> EmailMessage:
    """FYI notification sent after full approval — no action required."""

    employee  = request_details.get("employee_name", "[Employee]")
    req_type  = request_details.get("request_type", workflow_name)
    effective = request_details.get("effective_date", "")
    initiator = request_details.get("initiator_name", "[Initiator]")

    rows = [
        ("Request type", req_type),
        ("Employee", employee),
        ("Initiated by", initiator),
    ]
    if effective:
        rows.append(("Effective date", _fmt_dt(effective)))
    rows.append(("Status", f'<span style="color:{GREEN};font-weight:700;">Fully Approved</span>'))

    inner = f"""
<div style="font-family:{HEAD_FONT};font-size:16px;color:{INK};margin:0 0 12px;">Hi {notify_name},</div>
<div style="font-family:{HEAD_FONT};background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:12px 16px;font-size:13px;color:#5d4037;">This is a notification only &mdash; no action is required from you.</div>
<div style="font-family:{HEAD_FONT};font-size:14px;color:{BODY};margin:16px 0 0;">The following HR request has been fully approved and is ready for processing.</div>
{_detail_card(rows)}
<div style="font-family:{HEAD_FONT};font-size:13px;color:{MUTE};margin-top:18px;line-height:1.6;">You are receiving this as <strong style="color:{BODY};">{notify_role}</strong>. Please take any follow-up actions for your role.</div>
"""

    subject = f"FYI: {req_type} approved — {employee}"
    return EmailMessage(
        to=notify_email,
        subject=subject,
        body_html=_wrap("HR Approvals — Notification", inner),
        body_text=(
            f"Hi {notify_name},\n\nFYI: The following request has been fully approved.\n\n"
            f"Request: {req_type}\nEmployee: {employee}\nStatus: Fully Approved\n\nNo action required."
        ),
    )


def build_requester_email(
    requester_name: str,
    requester_email: str,
    request_details: dict,
    approved: bool,
    rejected_by: str = "",
    pdf_url: str = "",
    rejection_comments: str = "",
) -> EmailMessage:
    """Final status email to the person who initiated the request."""

    req_type = request_details.get("request_type", "HR Request")
    employee = request_details.get("employee_name", "[Employee]")

    if approved:
        decision = f'<span style="color:{GREEN};font-weight:700;">Fully Approved</span>'
        message  = "Your request has been approved by all required approvers and will now be processed by HR."
        note     = "If you have questions about next steps, contact your HR representative."
    else:
        decision = f'<span style="color:{RED};font-weight:700;">Rejected</span>'
        message  = f"Your request was rejected by {rejected_by}."
        note     = "Please contact HR for more information. You may resubmit after addressing the reason for rejection."

    rows = [
        ("Request type", req_type),
        ("Employee", employee),
        ("Decision", decision),
    ]

    extra = ""
    if (not approved) and rejection_comments:
        extra += (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0 0;background:#fdf0f0;border-left:4px solid {RED};border-radius:8px;"><tr><td style="padding:14px 18px;">'
            f'<div style="font-family:{HEAD_FONT};font-size:12px;font-weight:700;color:{RED};margin:0 0 6px;">Reason for rejection</div>'
            f'<div style="font-family:{HEAD_FONT};font-size:13px;color:{BODY};">{rejection_comments}</div></td></tr></table>'
        )
    if approved and pdf_url:
        extra += (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:18px 0 0;background:#f8fafc;border-left:4px solid {ACCENT};border-radius:8px;"><tr><td style="padding:14px 18px;">'
            f'<div style="font-family:{HEAD_FONT};font-size:13px;font-weight:700;color:{INK};margin:0 0 4px;">Approval record</div>'
            f'<div style="font-family:{HEAD_FONT};font-size:12px;color:{MUTE};">A PDF record of this approval has been saved to SharePoint HR Records.</div>'
            f'<a href="{pdf_url}" style="font-family:{HEAD_FONT};display:inline-block;margin-top:10px;font-size:13px;font-weight:700;color:{ACCENT};text-decoration:none;">View approval record PDF &rarr;</a></td></tr></table>'
        )

    inner = f"""
<div style="font-family:{HEAD_FONT};font-size:16px;color:{INK};margin:0 0 6px;">Hi {requester_name},</div>
<div style="font-family:{HEAD_FONT};font-size:14px;color:{BODY};">Your HR request has been reviewed. Here is the outcome:</div>
{_detail_card(rows)}
<div style="font-family:{HEAD_FONT};font-size:14px;color:{BODY};margin:16px 0 0;">{message}</div>
{extra}
<div style="font-family:{HEAD_FONT};font-size:12px;color:{FAINT};margin-top:20px;line-height:1.6;">{note}</div>
"""

    status_word = "approved" if approved else "rejected"
    subject = f"Your {req_type.lower()} request has been {status_word}"
    plain = (
        f"Hi {requester_name},\n\nYour request ({req_type}) for {employee} has been {status_word}.\n\n{message}"
    )
    if rejection_comments:
        plain += f"\n\nReason: {rejection_comments}"
    if pdf_url:
        plain += f"\n\nApproval record: {pdf_url}"

    return EmailMessage(
        to=requester_email,
        subject=subject,
        body_html=_wrap("HR Approvals — Outcome", inner),
        body_text=plain,
    )
