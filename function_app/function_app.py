"""
Azure Function App entry points.

Functions:
  1. sp_trigger        — fires when a new SharePoint list item is created
  2. approval_action   — approver clicks Approve in their email (records immediately)
  3. rejection_form_get — approver clicks Reject — shows a form to enter reason
  4. rejection_form_post — processes the rejection form submission
  5. health_check      — simple GET for monitoring
"""

import json
import logging
from urllib.parse import urlencode

import azure.functions as func

from orchestrator import ApprovalOrchestrator
from rejection_form import build_rejection_form, build_rejection_confirmed_page

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
    for change in changes:
        item_id = str(change.item_id)
        logger.info("New SharePoint item detected: %s", item_id)
        try:
            orchestrator.handle_new_request(item_id)
        except Exception as e:
            logger.exception("Error handling new request %s: %s", item_id, e)


# ── 2. Approval action — Approve only ─────────────────────────────────────
# Reject now goes to rejection_form_get instead

@app.function_name("ApprovalAction")
@app.route(route="approval-action", methods=["GET", "POST"])
def approval_action(req: func.HttpRequest) -> func.HttpResponse:
    request_id     = req.params.get("request_id", "").strip()
    approver_email = req.params.get("approver", "").strip()
    action         = req.params.get("action", "").strip().lower()

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

    # Reject — redirect to the comment form instead of processing immediately
    if action == "reject":
        list_key = req.params.get("list_key", "").strip()
        params = urlencode({
            "request_id": request_id,
            "approver":   approver_email,
            "list_key":   list_key,
        })
        return func.HttpResponse(
            status_code=302,
            headers={"Location": f"/api/rejection-form?{params}"},
            body=b"",
        )

    # Approve — process immediately
    try:
        result = orchestrator.handle_approval_action(
            item_id=request_id,
            approver_email=approver_email,
            action="approve",
            comments="",
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

    if result.get("outcome") == "fully_approved":
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


# ── 3. Rejection form — GET (show the form) ───────────────────────────────

@app.function_name("RejectionFormGet")
@app.route(route="rejection-form", methods=["GET"])
def rejection_form_get(req: func.HttpRequest) -> func.HttpResponse:
    request_id     = req.params.get("request_id", "").strip()
    approver_email = req.params.get("approver", "").strip()
    list_key       = req.params.get("list_key", "").strip()

    if not all([request_id, approver_email, list_key]):
        return func.HttpResponse(
            _html_response("Invalid Request", "Missing required parameters.", error=True),
            status_code=400, mimetype="text/html",
        )

    # Fetch request details to show on the form
    employee_name = ""
    request_type  = ""
    try:
        from list_configs import LIST_CONFIGS
        config = LIST_CONFIGS.get(list_key)
        if config:
            fields = orchestrator.sp.get_item(config.list_path, request_id)
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
    )
    return func.HttpResponse(html, mimetype="text/html")


# ── 4. Rejection form — POST (process the submission) ─────────────────────

@app.function_name("RejectionFormPost")
@app.route(route="rejection-form", methods=["POST"])
def rejection_form_post(req: func.HttpRequest) -> func.HttpResponse:
    try:
        form = req.form
        request_id     = form.get("request_id", "").strip()
        approver_email = form.get("approver", "").strip()
        list_key       = form.get("list_key", "").strip()
        comments       = form.get("comments", "").strip()
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

    try:
        result = orchestrator.handle_approval_action(
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

def _html_response(title: str, message: str, success: bool = True, error: bool = False) -> str:
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
