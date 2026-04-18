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

logger = logging.getLogger(__name__)
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

_orchestrator: Optional[ApprovalOrchestrator] = None

def get_orchestrator() -> ApprovalOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ApprovalOrchestrator()
    return _orchestrator


# ── 1. Timer trigger ──────────────────────────────────────────────────────

@app.function_name("PollNewRequests")
@app.timer_trigger(arg_name="timer", schedule="0 */5 * * * *", run_on_startup=False)
def poll_new_requests(timer: func.TimerRequest) -> None:
    logger.info("PollNewRequests timer fired")
    try:
        get_orchestrator().poll_all_lists()
    except Exception as e:
        logger.exception("Error during list poll: %s", e)


# ── 2. Approval action ────────────────────────────────────────────────────

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

    try:
        result = get_orchestrator().handle_approval_action(
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


# ── 3. Rejection form — GET ───────────────────────────────────────────────

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
    )
    return func.HttpResponse(html, mimetype="text/html")


# ── 4. Rejection form — POST ──────────────────────────────────────────────

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


# ── 6. Debug roles ────────────────────────────────────────────────────────
# TODO: remove before going live

@app.function_name("DebugRoles")
@app.route(route="debug-roles", methods=["GET"])
def debug_roles(req: func.HttpRequest) -> func.HttpResponse:
    try:
        orch = get_orchestrator()
        orch.roles_client.invalidate_cache()
        orch.roles_client._load_cache()
        cache = orch.roles_client._cache
        return func.HttpResponse(
            json.dumps({
                "status": "ok",
                "roles_found": sorted(cache.keys()),
                "total_entries": sum(len(v) for v in cache.values()),
                "detail": {
                    role: [{"name": e["name"], "email": e["email"], "company": e.get("company", "")} for e in entries]
                    for role, entries in sorted(cache.items())
                },
            }, indent=2),
            mimetype="application/json",
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"status": "error", "message": str(e)}),
            status_code=500, mimetype="application/json",
        )


# ── 7. Debug lists ────────────────────────────────────────────────────────
# Fetches each list's actual columns from Graph and checks them against
# what list_configs.py expects. Returns a per-list pass/fail report.
# TODO: remove before going live

@app.function_name("DebugLists")
@app.route(route="debug-lists", methods=["GET"])
def debug_lists(req: func.HttpRequest) -> func.HttpResponse:
    try:
        orch  = get_orchestrator()
        sp    = orch.sp
        graph = "https://graph.microsoft.com/v1.0"
        site_id = sp._get_site_id()
        headers = sp._headers()

        report = {}
        overall_ok = True

        for list_key, config in LIST_CONFIGS.items():
            result = _check_list(graph, site_id, headers, list_key, config)
            if not result["list_found"] or result["missing_columns"]:
                overall_ok = False
            report[list_key] = result

        return func.HttpResponse(
            json.dumps({
                "overall": "OK" if overall_ok else "ISSUES FOUND",
                "site_id": site_id,
                "lists": report,
            }, indent=2),
            mimetype="application/json",
        )
    except Exception as e:
        return func.HttpResponse(
            json.dumps({"status": "error", "message": str(e)}),
            status_code=500, mimetype="application/json",
        )


def _check_list(graph: str, site_id: str, headers: dict, list_key: str, config: ListConfig) -> dict:
    """
    Fetch a list's actual columns from Graph and compare against what
    list_configs.py expects. Returns a dict with the check results.
    """
    result = {
        "display_name": config.display_name,
        "list_found": False,
        "list_id": None,
        "actual_columns": [],
        "expected_columns": [],
        "missing_columns": [],
        "present_columns": [],
        "column_types": {},
        "error": None,
    }

    # Find the list by display name
    try:
        r = http.get(f"{graph}/sites/{site_id}/lists", headers=headers, timeout=30)
        r.raise_for_status()
        lists = r.json().get("value", [])
        list_id = None
        for lst in lists:
            if lst["displayName"].lower() == config.display_name.lower():
                list_id = lst["id"]
                break

        if not list_id:
            result["error"] = f"List '{config.display_name}' not found on site. Available: {[l['displayName'] for l in lists]}"
            return result

        result["list_found"] = True
        result["list_id"] = list_id
    except Exception as e:
        result["error"] = f"Failed to fetch lists: {e}"
        return result

    # Fetch the list's columns
    try:
        r = http.get(f"{graph}/sites/{site_id}/lists/{list_id}/columns", headers=headers, timeout=30)
        r.raise_for_status()
        columns = r.json().get("value", [])
        # Build a map of displayName -> column type info
        col_map = {}
        for col in columns:
            name = col.get("displayName", "")
            col_type = _get_col_type(col)
            col_map[name] = col_type
        result["actual_columns"] = sorted(col_map.keys())
        result["column_types"] = col_map
    except Exception as e:
        result["error"] = f"Failed to fetch columns: {e}"
        return result

    # Build the list of columns we expect from list_configs
    expected = _get_expected_columns(config)
    result["expected_columns"] = sorted(expected)

    # Check which are present and which are missing
    missing = []
    present = []
    for col in expected:
        if col in col_map:
            present.append({"column": col, "type": col_map[col]})
        else:
            # Try case-insensitive match and report the closest real name
            real_name = next(
                (k for k in col_map if k.lower() == col.lower()), None
            )
            if real_name:
                present.append({
                    "column": col,
                    "type": col_map[real_name],
                    "note": f"Found as '{real_name}' (case mismatch — update list_configs.py)",
                })
            else:
                missing.append(col)

    result["missing_columns"] = missing
    result["present_columns"] = present

    return result


def _get_col_type(col: dict) -> str:
    """Return a human-readable column type string from a Graph column definition."""
    if col.get("personOrGroup"):
        allow_multiple = col["personOrGroup"].get("allowMultipleSelection", False)
        return "Person (multi)" if allow_multiple else "Person"
    if col.get("choice"):
        choices = col["choice"].get("choices", [])
        return f"Choice ({', '.join(choices[:4])}{'...' if len(choices) > 4 else ''})"
    if col.get("boolean"):
        return "Yes/No"
    if col.get("dateTime"):
        return "DateTime"
    if col.get("number"):
        return "Number"
    if col.get("lookup"):
        return "Lookup"
    if col.get("text"):
        multiline = col["text"].get("allowMultipleLines", False)
        return "Multiline text" if multiline else "Single line text"
    if col.get("calculated"):
        return "Calculated"
    return "Unknown"


def _get_expected_columns(config: ListConfig) -> list[str]:
    """
    Return the list of column display names the app needs to read/write
    for a given list config, based on all non-None column references.
    """
    cols = set()

    # Core columns always needed
    cols.add(config.status_col)
    cols.add(config.employee_name_col)
    if config.employee_col:
        cols.add(config.employee_col)
    if config.initiator_col:
        cols.add(config.initiator_col)
    if config.request_type_col:
        cols.add(config.request_type_col)
    if config.effective_date_col:
        cols.add(config.effective_date_col)
    if config.notes_col:
        cols.add(config.notes_col)
    if config.url_col:
        cols.add(config.url_col)

    # Approval chain columns
    for attr in [
        "direct_manager_col", "second_level_manager_col", "hr_manager_col",
        "gm_director_col", "executive_col", "ceo_col", "hiring_manager_col",
        "payroll_manager_col", "benefits_specialist_col", "hr_generalist_col",
    ]:
        val = getattr(config, attr, None)
        if val:
            cols.add(val)

    # Workflow columns the app writes back
    cols.add("WorkflowKey")
    cols.add("CurrentApprovalStep")
    cols.add("WorkflowCategory")
    cols.add("InitiatorName")
    cols.add("InitiatorEmail")
    cols.add("EmployeeEmail")
    cols.add("ApprovalRecordURL")

    return sorted(cols)


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
