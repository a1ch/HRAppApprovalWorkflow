"""
Tests for approval matrix and email templates.
Run: pytest tests/
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../function_app"))

from approval_matrix import WORKFLOWS, get_workflow, get_workflows_by_category, RequestCategory
from email_templates import (
    build_approver_email,
    build_notify_email,
    build_requester_email,
)


# ── Matrix tests ──────────────────────────────────────────────────────────

def test_all_workflows_have_required_fields():
    for key, wf in WORKFLOWS.items():
        assert wf.category, f"{key}: missing category"
        assert wf.request_type, f"{key}: missing request_type"
        assert wf.initiator_role, f"{key}: missing initiator_role"
        assert len(wf.approval_chain) >= 1, f"{key}: approval_chain is empty"


def test_workflow_count():
    assert len(WORKFLOWS) == 30, f"Expected 30 workflows, got {len(WORKFLOWS)}"


def test_get_workflow_known_key():
    wf = get_workflow("job_req_backfill_budgeted")
    assert wf is not None
    assert wf.request_type == "Backfill – Budgeted"
    assert wf.initiator_role == "Hiring Manager"
    assert wf.approval_chain == ["HR Manager", "2nd Level Manager", "GM/Director"]


def test_get_workflow_unknown_key():
    assert get_workflow("nonexistent_key") is None


def test_ceo_workflows():
    ceo_required = [k for k, v in WORKFLOWS.items() if v.requires_ceo]
    # CEO approval required for salaried, unbudgeted, or new budgeted positions
    for key in ceo_required:
        wf = WORKFLOWS[key]
        assert any(x in wf.request_type.lower() for x in ["salaried", "unbudgeted", "new position"]), (
            f"{key}: requires_ceo=True but unexpected type: {wf.request_type}"
        )


def test_termination_workflows_have_notify():
    terminations = [k for k in WORKFLOWS if "termination" in k]
    assert len(terminations) == 3
    for key in terminations:
        wf = WORKFLOWS[key]
        assert "Benefits Specialist" in wf.notify_roles
        assert "Payroll Manager" in wf.notify_roles


def test_get_workflows_by_category():
    loa = get_workflows_by_category(RequestCategory.LEAVE_OF_ABSENCE)
    assert len(loa) == 3
    for wf in loa.values():
        assert wf.category == RequestCategory.LEAVE_OF_ABSENCE


# ── Email template tests ──────────────────────────────────────────────────

SAMPLE_DETAILS = {
    "request_type": "Backfill – Budgeted",
    "employee_name": "John Smith",
    "initiator_name": "Chris Hayslip",
    "submitted_date": "2025-01-15",
    "notes": "",
}


def test_approver_email_contains_links():
    wf = get_workflow("job_req_backfill_budgeted")
    msg = build_approver_email(
        base_url="https://example.azurewebsites.net",
        request_id="item-123",
        approver_name="Rae-Lynn Perkins",
        approver_email="rlperkins@streamflo.com",
        request_details=SAMPLE_DETAILS,
        workflow_name=wf.request_type,
        approval_chain=wf.approval_chain,
        current_step=0,
        previous_approvals=[],
    )
    assert "approve" in msg.body_html.lower()
    assert "reject" in msg.body_html.lower()
    assert "item-123" in msg.body_html
    assert "rlperkins%40streamflo.com" in msg.body_html  # URL-encoded in href
    assert msg.to == "rlperkins@streamflo.com"
    assert "Action required" in msg.subject


def test_approver_email_shows_chain_progress():
    wf = get_workflow("job_req_backfill_budgeted")
    msg = build_approver_email(
        base_url="https://example.azurewebsites.net",
        request_id="item-456",
        approver_name="Keith Haynes",
        approver_email="khaynes@streamflo.com",
        request_details=SAMPLE_DETAILS,
        workflow_name=wf.request_type,
        approval_chain=wf.approval_chain,
        current_step=1,
        previous_approvals=[{"name": "Rae-Lynn Perkins", "role": "HR Manager", "decision": "Approved", "date": "2025-01-15"}],
    )
    assert "Rae-Lynn Perkins" in msg.body_html
    assert "step 2 of 3" in msg.body_html.lower()


def test_notify_email_no_action_links():
    wf = get_workflow("pcn_termination_discharge")
    msg = build_notify_email(
        notify_name="Benefits Specialist",
        notify_email="scarrisalez@streamflo.com",
        request_details=SAMPLE_DETAILS,
        workflow_name=wf.request_type,
        notify_role="Benefits Specialist",
    )
    assert "approval-action" not in msg.body_html
    assert "No action" in msg.body_html or "notification only" in msg.body_html.lower()
    assert "FYI" in msg.subject


def test_requester_approved_email():
    msg = build_requester_email(
        requester_name="Chris Hayslip",
        requester_email="chayslip@streamflo.com",
        request_details=SAMPLE_DETAILS,
        approved=True,
    )
    assert "approved" in msg.subject.lower()
    assert "chayslip@streamflo.com" == msg.to


def test_requester_rejected_email():
    msg = build_requester_email(
        requester_name="Chris Hayslip",
        requester_email="chayslip@streamflo.com",
        request_details=SAMPLE_DETAILS,
        approved=False,
        rejected_by="Quanah Gilmore",
    )
    assert "rejected" in msg.subject.lower()
    assert "Quanah Gilmore" in msg.body_html
