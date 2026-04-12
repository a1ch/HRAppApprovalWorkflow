"""
Azure Function App entry points.

Functions:
  1. sp_trigger        — fires when a new SharePoint list item is created
  2. approval_action   — HTTP endpoint approvers click from their email
  3. health_check      — simple GET for monitoring
"""

import json
import logging

import azure.functions as func

from orchestrator import ApprovalOrchestrator

logger = logging.getLogger(__name__)
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
orchestrator = ApprovalOrchestrator()


# ── 1. SharePoint trigger ─────────────────────────────────────────────────

@app.function_name("SharePointNewRequest")
@app.sp_change_feed_trigger(
    arg_name="changes",
    connection="SharePointConnection",
    list_id="%SP_LIST_NAME%",
    event_type="created",
)
def sp_trigger(changes: func.SPChangeInput) -> None:
    """
    Fires automatically when a new item is added to the HR Approvals SharePoint list.
    Kicks off the approval chain for that request.
    """
    for change in changes:
        item_id = str(change.item_id)
        logger.info("New SharePoint item detected: %s", item_id)
        try:
            orchestrator.handle_new_request(item_id)
        except Exception as e:
            logger.exception("Error handling new request %s: %s", item_id, e)


# ── 2. Approval action (approver clicks Approve / Reject link) ────────────

@app.function_name("ApprovalAction")
@app.route(route="approval-action", methods=["GET", "POST"])
def approval_action(req: func.HttpRequest) -> func.HttpResponse:
    """
    Called when an approver clicks Approve or Reject in their email.
    Query params: request_id, approver, action
    Optional body JSON: { "comments": "..." }
    """
    request_id = req.params.get("request_id", "").strip()
    approver_email = req.params.get("approver", "").strip()
    action = req.params.get("action", "").strip().lower()

    if not all([request_id, approver_email, action]):
        return func.HttpResponse(
            _html_response("Invalid Request", "Missing required parameters.", error=True),
            status_code=400,
            mimetype="text/html",
        )

    if action not in ("approve", "reject"):
        return func.HttpResponse(
            _html_response("Invalid Action", f"'{action}' is not a valid action.", error=True),
            status_code=400,
            mimetype="text/html",
        )

    comments = ""
    try:
        body = req.get_json()
        comments = body.get("comments", "")
    except Exception:
        pass

    try:
        result = orchestrator.handle_approval_action(
            item_id=request_id,
            approver_email=approver_email,
            action=action,
            comments=comments,
        )
    except Exception as e:
        logger.exception("Error processing approval action for %s: %s", request_id, e)
        return func.HttpResponse(
            _html_response("Error", "An error occurred processing your decision. Please contact IT.", error=True),
            status_code=500,
            mimetype="text/html",
        )

    outcome = result.get("outcome", "")
    error = result.get("error", "")

    if error:
        return func.HttpResponse(
            _html_response("Not Authorised", error, error=True),
            status_code=403,
            mimetype="text/html",
        )

    if action == "reject":
        return func.HttpResponse(
            _html_response(
                "Request Rejected",
                "Your decision has been recorded. The requester has been notified.",
                success=False,
            ),
            mimetype="text/html",
        )

    if outcome == "fully_approved":
        return func.HttpResponse(
            _html_response(
                "Fully Approved",
                "All approvals are complete. The requester and relevant parties have been notified.",
                success=True,
            ),
            mimetype="text/html",
        )

    next_step = result.get("next_step", "?")
    return func.HttpResponse(
        _html_response(
            "Approved — Forwarded",
            f"Your approval has been recorded. The request has been forwarded to the next approver (step {next_step + 1}).",
            success=True,
        ),
        mimetype="text/html",
    )


# ── 3. Health check ───────────────────────────────────────────────────────

@app.function_name("HealthCheck")
@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"status": "ok", "service": "hr-approval-func"}),
        mimetype="application/json",
    )


# ── HTML response helper ──────────────────────────────────────────────────

def _html_response(title: str, message: str, success: bool = True, error: bool = False) -> str:
    if error:
        icon = "&#9888;"
        color = "#c0392b"
        bg = "#fdf0f0"
    elif success:
        icon = "&#10003;"
        color = "#1a7a3c"
        bg = "#f0fdf4"
    else:
        icon = "&#8635;"
        color = "#7d3c00"
        bg = "#fef9f0"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Stream-Flo HR</title>
<style>
  body {{font-family:Arial,sans-serif;background:#f5f5f5;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
  .card {{background:#fff;border-radius:10px;padding:40px 48px;max-width:460px;text-align:center;border:1px solid #e0e0e0}}
  .icon {{width:56px;height:56px;border-radius:50%;background:{bg};display:flex;align-items:center;justify-content:center;font-size:24px;color:{color};margin:0 auto 20px}}
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
