"""
Azure Function App entry points.

Functions:
  1. PollNewRequests    — timer, runs every 5 min, polls all 6 HR lists for Pending items
  2. ApprovalAction     — approver clicks Approve in their email (records immediately)
  3. RejectionFormGet   — approver clicks Reject — shows a form to enter reason
  4. RejectionFormPost  — processes the rejection form submission
  5. HealthCheck        — simple GET for monitoring
  6. DebugRoles         — temp: reads HR Approval Roles list and returns what was found
  7. DebugLists         — temp: checks all 6 HR lists for correct column configuration
  8. DebugLookups       — temp: lookup column audit — counts, redundant cols, duplicates
"""

import json
import logging
from urllib.parse import urlencode
from typing import Optional

import azure.functions as func
import requests as http

from orchestrator import ApprovalOrchestrator
from rejection_form import build_rejection_form, build_rejection_confirmed_page
from list_configs import LIST_CONFIGS, ListConfig
from signing import verify

logger = logging.getLogger(__name__)
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

_orchestrator: Optional[ApprovalOrchestrator] = None

def get_orchestrator() -> ApprovalOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ApprovalOrchestrator()
    return _orchestrator


# ── 1. Timer trigger ──────────────────────────────────────────────────────

def _bad_signature_response() -> func.HttpResponse:
    """Returned when an approval/rejection link fails HMAC verification."""
    return func.HttpResponse(
        _html_response(
            "Invalid or Expired Link",
            "This approval link could not be verified. It may have been altered, or "
            "it is no longer valid. Please use the most recent approval email, or "
            "contact HR if you need a new one.",
            error=True,
        ),
        status_code=403, mimetype="text/html",
    )

@app.function_name("PollNewRequests")
@app.timer_trigger(arg_name="timer", schedule="0 */5 * * * *", run_on_startup=False)
def poll_new_requests(timer: func.TimerRequest) -> None:
    logger.info("PollNewRequests timer fired")
    try:
        get_orchestrator().poll_all_lists()
    except Exception as e:
        logger.exception("Error during list poll: %s", e)


@app.function_name("StuckItemMonitor")
@app.timer_trigger(arg_name="timer", schedule="0 0 13 * * *", run_on_startup=False)
def stuck_item_monitor(timer: func.TimerRequest) -> None:
    """Daily digest of errored / stalled approval requests (see monitor.py)."""
    logger.info("StuckItemMonitor timer fired")
    try:
        import monitor
        monitor.scan_and_notify(get_orchestrator())
    except Exception as e:
        logger.exception("StuckItemMonitor error: %s", e)


@app.function_name("EscalationCheck")
@app.timer_trigger(arg_name="timer", schedule="0 30 13 * * *", run_on_startup=False)
def escalation_check(timer: func.TimerRequest) -> None:
    """Daily approval reminders (7/14d) + 30-day notice; non-destructive (see escalation.py)."""
    logger.info("EscalationCheck timer fired")
    try:
        import escalation
        escalation.run(get_orchestrator())
    except Exception as e:
        logger.exception("EscalationCheck error: %s", e)


# ── 2. Approval action ────────────────────────────────────────────────────

@app.function_name("ApprovalAction")
@app.route(route="approval-action", methods=["GET", "POST"], auth_level=func.AuthLevel.ANONYMOUS)
def approval_action(req: func.HttpRequest) -> func.HttpResponse:
    _src           = req.form if req.method == "POST" else req.params
    request_id     = (_src.get("request_id") or "").strip()
    approver_email = (_src.get("approver") or "").strip()
    action         = (_src.get("action") or "").strip().lower()
    list_key       = (_src.get("list_key") or "").strip()
    signature      = (_src.get("sig") or "").strip()

    if not all([request_id, approver_email, action]):
        return func.HttpResponse(
            _html_response("Invalid Request", "Missing required parameters.", error=True),
            status_code=400, mimetype="text/html",
        )

    if action not in ("approve", "reject"):
        return func.HttpResponse(
            _html_response("Invalid Action", f"'{action}' is not a valid action.", error=True),
            status_code=400, mimetype="text/html",
        )

    if not verify(request_id, approver_email, action, list_key, signature):
        logger.warning("Bad signature on approval link for request %s (action %s)",
                       request_id, action)
        return _bad_signature_response()

    if action == "reject":
        list_key = req.params.get("list_key", "").strip()
        params = urlencode({
            "request_id": request_id,
            "approver":   approver_email,
            "list_key":   list_key,
            "sig":        signature,
        })
        return func.HttpResponse(
            status_code=302,
            headers={"Location": f"/api/rejection-form?{params}"},
            body=b"",
        )

    if req.method != "POST":
        return func.HttpResponse(
            _confirm_approval_page(request_id, approver_email, list_key, signature),
            mimetype="text/html",
        )

    try:
        result = get_orchestrator().handle_approval_action(
            item_id=request_id,
            approver_email=approver_email,
            action="approve",
            comments="",
            list_key=list_key,
        )
    except Exception as e:
        logger.exception("Error processing approval for %s: %s", request_id, e)
        return func.HttpResponse(
            _html_response("Error", "An error occurred. Please contact IT.", error=True),
            status_code=500, mimetype="text/html",
        )

    error = result.get("error", "")
    if error:
        return func.HttpResponse(
            _html_response("Not Authorised", error, error=True),
            status_code=403, mimetype="text/html",
        )

    # Idempotent re-click: the step was already decided (duplicate or stale
    # email, or a second click). Show a friendly page instead of crashing.
    if result.get("message"):
        return func.HttpResponse(
            _html_response(
                "Already Recorded",
                "This step has already been recorded - no further action is needed.",
                success=True,
            ),
            mimetype="text/html",
        )

    if result.get("outcome") == "fully_approved":
        return func.HttpResponse(
            _html_response(
                "Fully Approved",
                "All approvals are complete. The requester and relevant parties have been notified.",
                success=True,
            ),
            mimetype="text/html",
        )

    if result.get("outcome") == "advanced":
        next_step = result.get("next_step", 0)
        try:
            human_step = int(next_step) + 1
        except (TypeError, ValueError):
            human_step = next_step
        return func.HttpResponse(
            _html_response(
                "Approved - Forwarded",
                f"Your approval has been recorded. The request has been forwarded to the next approver (step {human_step}).",
                success=True,
            ),
            mimetype="text/html",
        )

    # Fallback for any other outcome - acknowledge without crashing.
    return func.HttpResponse(
        _html_response("Recorded", "Your decision has been recorded.", success=True),
        mimetype="text/html",
    )


# ── 3. Rejection form — GET ───────────────────────────────────────────────

@app.function_name("RejectionFormGet")
@app.route(route="rejection-form", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def rejection_form_get(req: func.HttpRequest) -> func.HttpResponse:
    _src           = req.form if req.method == "POST" else req.params
    request_id     = (_src.get("request_id") or "").strip()
    approver_email = (_src.get("approver") or "").strip()
    list_key       = req.params.get("list_key", "").strip()
    signature      = req.params.get("sig", "").strip()

    if not all([request_id, approver_email, list_key]):
        return func.HttpResponse(
            _html_response("Invalid Request", "Missing required parameters.", error=True),
            status_code=400, mimetype="text/html",
        )

    if not verify(request_id, approver_email, "reject", list_key, signature):
        logger.warning("Bad signature on rejection-form GET for request %s", request_id)
        return _bad_signature_response()

    employee_name = ""
    request_type  = ""
    try:
        config = LIST_CONFIGS.get(list_key)
        if config:
            fields = get_orchestrator().sp.get_item(request_id)
            employee_name = fields.get(config.employee_name_col, "")
            request_type  = fields.get(config.request_type_col, "") if config.request_type_col else ""
    except Exception as e:
        logger.warning("Could not fetch request details for rejection form: %s", e)

    html = build_rejection_form(
        request_id=request_id,
        approver_email=approver_email,
        list_key=list_key,
        employee_name=employee_name,
        request_type=request_type,
        signature=signature,
    )
    return func.HttpResponse(html, mimetype="text/html")


# ── 4. Rejection form — POST ──────────────────────────────────────────────

@app.function_name("RejectionFormPost")
@app.route(route="rejection-form", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def rejection_form_post(req: func.HttpRequest) -> func.HttpResponse:
    try:
        form = req.form
        request_id     = form.get("request_id", "").strip()
        approver_email = form.get("approver", "").strip()
        list_key       = form.get("list_key", "").strip()
        comments       = form.get("comments", "").strip()
        signature      = form.get("sig", "").strip()
    except Exception:
        return func.HttpResponse(
            _html_response("Error", "Could not read form data.", error=True),
            status_code=400, mimetype="text/html",
        )

    if not all([request_id, approver_email, list_key]):
        return func.HttpResponse(
            _html_response("Invalid Request", "Missing required parameters.", error=True),
            status_code=400, mimetype="text/html",
        )

    if not verify(request_id, approver_email, "reject", list_key, signature):
        logger.warning("Bad signature on rejection-form POST for request %s", request_id)
        return _bad_signature_response()

    try:
        result = get_orchestrator().handle_approval_action(
            item_id=request_id,
            approver_email=approver_email,
            action="reject",
            comments=comments,
            list_key=list_key,
        )
    except Exception as e:
        logger.exception("Error processing rejection for %s: %s", request_id, e)
        return func.HttpResponse(
            _html_response("Error", "An error occurred. Please contact IT.", error=True),
            status_code=500, mimetype="text/html",
        )

    error = result.get("error", "")
    if error:
        return func.HttpResponse(
            _html_response("Not Authorised", error, error=True),
            status_code=403, mimetype="text/html",
        )

    return func.HttpResponse(
        build_rejection_confirmed_page(),
        mimetype="text/html",
    )


# ── 5. Health check ───────────────────────────────────────────────────────

@app.function_name("HealthCheck")
@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "ok", "service": "hr-approval-func"}),
        mimetype="application/json",
    )


# ── HTML response helper ──────────────────────────────────────────────────

def _confirm_approval_page(request_id: str, approver_email: str, list_key: str, signature: str) -> str:
    """Landing page shown when an Approve link is opened (GET). Records nothing;
    the decision is only saved when the user clicks the button, which POSTs.
    Prevents email link-scanners (e.g. Defender Safe Links) from auto-approving."""
    from html import escape
    rid, appr, lk, sg = escape(request_id), escape(approver_email), escape(list_key), escape(signature)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only">
<title>Confirm Approval &mdash; Stream-Flo HR</title></head>
<body style="font-family:'Arial Black','Segoe UI',Arial,sans-serif;background:#eef2f7;margin:0;padding:0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="min-height:100vh;"><tr><td align="center" valign="middle" style="padding:40px 16px;">
<table role="presentation" width="440" cellpadding="0" cellspacing="0" style="width:440px;max-width:440px;background:#ffffff;border-radius:12px;border:1px solid #e3e8ef;overflow:hidden;">
<tr><td style="background:#003366;padding:20px 28px;"><div style="color:#ffffff;font-size:16px;font-weight:800;">Stream-Flo USA &mdash; HR Approvals</div></td></tr>
<tr><td style="padding:28px;">
<div style="font-size:18px;color:#0f172a;font-weight:800;margin:0 0 10px;">Confirm your approval</div>
<div style="font-size:14px;color:#1e293b;line-height:1.5;">Click the button below to record your <strong>approval</strong> of this request. Your decision is only saved when you click &mdash; simply opening this page does nothing.</div>
<form method="POST" action="/api/approval-action" style="margin:24px 0 0;">
<input type="hidden" name="request_id" value="{rid}">
<input type="hidden" name="approver" value="{appr}">
<input type="hidden" name="action" value="approve">
<input type="hidden" name="list_key" value="{lk}">
<input type="hidden" name="sig" value="{sg}">
<button type="submit" style="font-family:'Arial Black','Segoe UI',Arial,sans-serif;background:#1a7a3c;color:#ffffff;border:none;border-radius:8px;padding:13px 30px;font-size:15px;font-weight:700;cursor:pointer;">Approve this request</button>
</form>
<div style="font-size:12px;color:#94a3b8;margin-top:18px;">Request ID: {rid}</div>
</td></tr></table>
</td></tr></table>
</body></html>"""

def _html_response(title: str, message: str, success: bool = True, error: bool = False) -> str:
    from html import escape
    title = escape(title)
    message = escape(message)
    if error:
        icon, color, bg = "&#9888;", "#c0392b", "#fdf0f0"
    elif success:
        icon, color, bg = "&#10003;", "#1a7a3c", "#f0fdf4"
    else:
        icon, color, bg = "&#8635;", "#7d3c00", "#fef9f0"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Stream-Flo HR</title>
<style>
  body {{font-family:Arial,sans-serif;background:#f5f5f5;display:flex;align-items:center;
         justify-content:center;min-height:100vh;margin:0}}
  .card {{background:#fff;border-radius:10px;padding:40px 48px;max-width:460px;
          text-align:center;border:1px solid #e0e0e0}}
  .icon {{width:56px;height:56px;border-radius:50%;background:{bg};display:flex;
          align-items:center;justify-content:center;font-size:24px;color:{color};margin:0 auto 20px}}
  h1 {{font-size:20px;color:#1a1a1a;margin:0 0 12px}}
  p {{font-size:14px;color:#555;line-height:1.6;margin:0}}
  .footer {{font-size:12px;color:#999;margin-top:24px;border-top:1px solid #eee;padding-top:16px}}
</style>
</head>
<body>
<div class="card">
  <div class="icon">{icon}</div>
  <h1>{title}</h1>
  <p>{message}</p>
  <div class="footer">Stream-Flo USA — HR Approval System<br>You may close this window.</div>
</div>
</body>
</html>"""