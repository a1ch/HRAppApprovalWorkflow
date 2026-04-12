"""
Email template engine for HR approval workflows.
Generates HTML + plain text emails for each stage of the approval chain.
"""

from dataclasses import dataclass
from urllib.parse import urlencode


@dataclass
class EmailMessage:
    to: str
    subject: str
    body_html: str
    body_text: str


def _approval_link(base_url: str, request_id: str, approver_email: str, action: str) -> str:
    params = urlencode({
        "request_id": request_id,
        "approver":   approver_email,
        "action":     action,
    })
    return f"{base_url}/api/approval-action?{params}"


def _html_wrapper(content: str, subject: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 14px; color: #1a1a1a; margin: 0; padding: 0; background: #f5f5f5; }}
  .wrap {{ max-width: 600px; margin: 32px auto; background: #fff; border-radius: 8px; overflow: hidden; border: 1px solid #e0e0e0; }}
  .header {{ background: #003366; padding: 24px 32px; }}
  .header h1 {{ color: #fff; font-size: 18px; margin: 0; font-weight: 600; }}
  .header p {{ color: #a0b8d0; font-size: 13px; margin: 4px 0 0; }}
  .body {{ padding: 28px 32px; }}
  .greeting {{ font-size: 15px; margin-bottom: 16px; }}
  .detail-box {{ background: #f8f9fa; border-radius: 6px; padding: 16px 20px; margin: 20px 0; border-left: 3px solid #003366; }}
  .detail-row {{ display: flex; gap: 12px; margin-bottom: 8px; font-size: 13px; }}
  .detail-row:last-child {{ margin-bottom: 0; }}
  .detail-label {{ color: #666; min-width: 130px; font-weight: 600; }}
  .detail-value {{ color: #1a1a1a; }}
  .action-row {{ display: flex; gap: 12px; margin: 28px 0; }}
  .btn {{ display: inline-block; padding: 12px 28px; border-radius: 6px; font-size: 14px; font-weight: 600; text-decoration: none; text-align: center; }}
  .btn-approve {{ background: #1a7a3c; color: #fff; }}
  .btn-reject {{ background: #fff; color: #c0392b; border: 2px solid #c0392b; }}
  .note {{ font-size: 12px; color: #888; margin-top: 20px; line-height: 1.6; }}
  .footer {{ background: #f8f9fa; padding: 16px 32px; border-top: 1px solid #e0e0e0; }}
  .footer p {{ font-size: 12px; color: #999; margin: 0; }}
  .chain {{ margin: 20px 0; }}
  .chain-step {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 13px; }}
  .chain-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .dot-done {{ background: #1a7a3c; }}
  .dot-current {{ background: #003366; }}
  .dot-pending {{ background: #ccc; }}
  .notify-banner {{ background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px; padding: 14px 18px; margin: 20px 0; font-size: 13px; color: #5d4037; }}
  .rejection-reason {{ background: #fdf0f0; border-radius: 6px; padding: 14px 18px; margin: 20px 0; border-left: 3px solid #c0392b; }}
  .rejection-reason p {{ font-size: 13px; margin: 0; }}
  .rejection-reason .label {{ font-weight: 600; color: #c0392b; margin-bottom: 6px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>Stream-Flo USA — HR Approvals</h1>
    <p>{subject}</p>
  </div>
  <div class="body">
    {content}
  </div>
  <div class="footer">
    <p>This is an automated message from the Stream-Flo HR Approval System. Do not reply to this email.</p>
    <p style="margin-top:6px">Stream-Flo USA LLC &bull; Houston, TX</p>
  </div>
</div>
</body>
</html>"""


def build_approver_email(
    base_url: str,
    request_id: str,
    approver_name: str,
    approver_email: str,
    request_details: dict,
    workflow_name: str,
    approval_chain: list[str],
    current_step: int,
    previous_approvals: list[dict],
) -> EmailMessage:
    """Email sent to each approver in sequence."""

    employee  = request_details.get("employee_name", "[Employee]")
    req_type  = request_details.get("request_type", workflow_name)
    initiator = request_details.get("initiator_name", "[Initiator]")
    submitted = request_details.get("submitted_date", "")
    notes     = request_details.get("notes", "")

    approve_url = _approval_link(base_url, request_id, approver_email, "approve")
    reject_url  = _approval_link(base_url, request_id, approver_email, "reject")

    chain_html = '<div class="chain">'
    for i, role in enumerate(approval_chain):
        if i < current_step:
            dot_class = "dot-done"
            label = f"{role} — <span style='color:#1a7a3c'>Approved</span>"
            if i < len(previous_approvals):
                label += f" by {previous_approvals[i].get('name', role)}"
        elif i == current_step:
            dot_class = "dot-current"
            label = f"<strong>{role} — Awaiting your decision</strong>"
        else:
            dot_class = "dot-pending"
            label = f"{role} — Pending"
        chain_html += f'<div class="chain-step"><div class="chain-dot {dot_class}"></div><span>{label}</span></div>'
    chain_html += "</div>"

    prev_html = ""
    if previous_approvals:
        prev_html = "".join(
            f'<div class="detail-row"><span class="detail-label">Approved by:</span>'
            f'<span class="detail-value">{a["name"]} ({a["role"]}) on {a["date"]}</span></div>'
            for a in previous_approvals
        )

    notes_html = (
        f'<div class="detail-row"><span class="detail-label">Notes:</span>'
        f'<span class="detail-value">{notes}</span></div>'
    ) if notes else ""

    content = f"""
<p class="greeting">Hi {approver_name},</p>
<p>An HR request requires your approval (step {current_step + 1} of {len(approval_chain)}).</p>

<div class="detail-box">
  <div class="detail-row"><span class="detail-label">Request type:</span><span class="detail-value">{req_type}</span></div>
  <div class="detail-row"><span class="detail-label">Employee:</span><span class="detail-value">{employee}</span></div>
  <div class="detail-row"><span class="detail-label">Initiated by:</span><span class="detail-value">{initiator}</span></div>
  <div class="detail-row"><span class="detail-label">Submitted:</span><span class="detail-value">{submitted}</span></div>
  {prev_html}
  {notes_html}
</div>

<p style="font-size:13px;color:#555;margin-bottom:8px">Approval chain progress:</p>
{chain_html}

<p style="margin-top:24px;font-size:14px">Please review and take action:</p>
<div class="action-row">
  <a href="{approve_url}" class="btn btn-approve">Approve</a>
  <a href="{reject_url}" class="btn btn-reject">Reject</a>
</div>

<p class="note">
  Clicking Approve records your decision immediately.<br>
  Clicking Reject will ask you to provide a reason before confirming.<br>
  Request ID: <code>{request_id}</code>
</p>
"""

    subject = f"Action required: {req_type} — {employee}"
    return EmailMessage(
        to=approver_email,
        subject=subject,
        body_html=_html_wrapper(content, subject),
        body_text=(
            f"Hi {approver_name},\n\nAn HR request requires your approval.\n\n"
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

    effective_row = (
        f'<div class="detail-row"><span class="detail-label">Effective date:</span>'
        f'<span class="detail-value">{effective}</span></div>'
    ) if effective else ""

    content = f"""
<p class="greeting">Hi {notify_name},</p>
<div class="notify-banner">
  This is a notification only — no action is required from you.
</div>
<p>The following HR request has been fully approved and is ready for processing.</p>

<div class="detail-box">
  <div class="detail-row"><span class="detail-label">Request type:</span><span class="detail-value">{req_type}</span></div>
  <div class="detail-row"><span class="detail-label">Employee:</span><span class="detail-value">{employee}</span></div>
  <div class="detail-row"><span class="detail-label">Initiated by:</span><span class="detail-value">{initiator}</span></div>
  {effective_row}
  <div class="detail-row"><span class="detail-label">Status:</span><span class="detail-value" style="color:#1a7a3c;font-weight:600">Fully Approved</span></div>
</div>

<p style="font-size:13px;color:#555">
  You are receiving this as <strong>{notify_role}</strong>. Please take any necessary follow-up actions per your role.
</p>
"""

    subject = f"FYI: {req_type} approved — {employee}"
    return EmailMessage(
        to=notify_email,
        subject=subject,
        body_html=_html_wrapper(content, subject),
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
        status_html   = '<span style="color:#1a7a3c;font-weight:600">Fully Approved</span>'
        message       = "Your request has been approved by all required approvers and will now be processed by HR."
        action_note   = "If you have questions about next steps, contact your HR representative."
        comments_html = ""
        pdf_html      = ""
        if pdf_url:
            pdf_html = (
                '<div style="margin:20px 0;padding:14px 18px;background:#f8f9fa;'
                'border-radius:6px;border-left:3px solid #003366">'
                '<p style="font-size:13px;margin:0 0 6px;font-weight:600;color:#1a1a1a">Approval record</p>'
                '<p style="font-size:12px;margin:0;color:#555">A PDF record of this approval has been saved to SharePoint HR Records.</p>'
                f'<a href="{pdf_url}" style="display:inline-block;margin-top:10px;font-size:13px;color:#185FA5">'
                'View approval record PDF</a></div>'
            )
    else:
        status_html = '<span style="color:#c0392b;font-weight:600">Rejected</span>'
        message     = f"Your request was rejected by {rejected_by}."
        action_note = "Please contact HR for more information. You may resubmit after addressing the reason for rejection."
        pdf_html    = ""
        comments_html = ""
        if rejection_comments:
            comments_html = (
                '<div class="rejection-reason">'
                '<p class="label">Reason for rejection</p>'
                f'<p>{rejection_comments}</p>'
                '</div>'
            )

    content = f"""
<p class="greeting">Hi {requester_name},</p>
<p>Your HR request has been reviewed. Here is the outcome:</p>

<div class="detail-box">
  <div class="detail-row"><span class="detail-label">Request type:</span><span class="detail-value">{req_type}</span></div>
  <div class="detail-row"><span class="detail-label">Employee:</span><span class="detail-value">{employee}</span></div>
  <div class="detail-row"><span class="detail-label">Decision:</span><span class="detail-value">{status_html}</span></div>
</div>

<p style="font-size:14px">{message}</p>
{comments_html}
{pdf_html}
<p class="note">{action_note}</p>
"""

    status_word = "approved" if approved else "rejected"
    subject     = f"Your {req_type.lower()} request has been {status_word}"
    plain       = (
        f"Hi {requester_name},\n\nYour request ({req_type}) for {employee} "
        f"has been {status_word}.\n\n{message}"
    )
    if rejection_comments:
        plain += f"\n\nReason: {rejection_comments}"
    if pdf_url:
        plain += f"\n\nApproval record: {pdf_url}"

    return EmailMessage(
        to=requester_email,
        subject=subject,
        body_html=_html_wrapper(content, subject),
        body_text=plain,
    )
