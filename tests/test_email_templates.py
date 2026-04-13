"""
Direct unit tests for email_templates.py.

Tests each builder function in isolation — no orchestrator, no mocks needed.

Run: pytest tests/test_email_templates.py -v
"""

import sys
import os
import types
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../function_app"))

for _mod in ("msal", "requests", "azure", "azure.functions"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
_req_exc = types.ModuleType("requests.exceptions")
_req_exc.HTTPError = type("HTTPError", (Exception,), {})
sys.modules["requests.exceptions"] = _req_exc

from email_templates import (
    build_approver_email,
    build_notify_email,
    build_requester_email,
    EmailMessage,
)

# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

BASE_URL    = "https://streamflo-hr-func.azurewebsites.net"
REQUEST_ID  = "item-1042"
CHAIN_3     = ["HR Manager", "2nd Level Manager", "GM/Director"]

REQUEST_DETAILS = {
    "request_type":    "Backfill – Budgeted",
    "employee_name":   "John Smith",
    "employee_number": "1003500",
    "initiator_name":  "Chris Hayslip",
    "submitted_date":  "2026-04-12T09:00:00+00:00",
    "effective_date":  "2026-05-01",
    "notes":           "Replacing departing service tech in Midland.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def approver_email(step=0, chain=None, previous=None):
    return build_approver_email(
        base_url=BASE_URL,
        request_id=REQUEST_ID,
        approver_name="Rae-Lynn Perkins",
        approver_email="rlperkins@streamflo.com",
        request_details=REQUEST_DETAILS,
        workflow_name="Backfill – Budgeted",
        approval_chain=chain or CHAIN_3,
        current_step=step,
        previous_approvals=previous or [],
    )


# ===========================================================================
# build_approver_email
# ===========================================================================

class TestApproverEmailStructure:

    def test_returns_email_message(self):
        msg = approver_email()
        assert isinstance(msg, EmailMessage)

    def test_to_is_approver_email(self):
        msg = approver_email()
        assert msg.to == "rlperkins@streamflo.com"

    def test_subject_contains_request_type(self):
        msg = approver_email()
        assert "Backfill" in msg.subject

    def test_subject_contains_employee_name(self):
        msg = approver_email()
        assert "John Smith" in msg.subject

    def test_subject_says_action_required(self):
        msg = approver_email()
        assert "Action required" in msg.subject

    def test_body_html_contains_approver_name(self):
        msg = approver_email()
        assert "Rae-Lynn Perkins" in msg.body_html

    def test_body_html_contains_employee_name(self):
        msg = approver_email()
        assert "John Smith" in msg.body_html

    def test_body_html_contains_initiator(self):
        msg = approver_email()
        assert "Chris Hayslip" in msg.body_html

    def test_body_html_contains_notes(self):
        msg = approver_email()
        assert "Midland" in msg.body_html

    def test_body_html_contains_request_id(self):
        msg = approver_email()
        assert REQUEST_ID in msg.body_html

    def test_body_html_has_approve_button(self):
        msg = approver_email()
        assert "btn-approve" in msg.body_html
        assert "Approve" in msg.body_html

    def test_body_html_has_reject_button(self):
        msg = approver_email()
        assert "btn-reject" in msg.body_html
        assert "Reject" in msg.body_html

    def test_body_html_is_valid_html(self):
        msg = approver_email()
        assert msg.body_html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in msg.body_html

    def test_plain_text_body_not_empty(self):
        msg = approver_email()
        assert len(msg.body_text) > 50

    def test_plain_text_has_approve_link(self):
        msg = approver_email()
        assert "approve" in msg.body_text.lower()
        assert BASE_URL in msg.body_text

    def test_plain_text_has_reject_link(self):
        msg = approver_email()
        assert "reject" in msg.body_text.lower()


class TestApproverEmailLinks:

    def test_approve_url_contains_action_approve(self):
        msg = approver_email()
        assert "action=approve" in msg.body_html

    def test_reject_url_contains_action_reject(self):
        msg = approver_email()
        assert "action=reject" in msg.body_html

    def test_links_contain_request_id(self):
        msg = approver_email()
        assert f"request_id={REQUEST_ID}" in msg.body_html

    def test_links_contain_approver_email(self):
        msg = approver_email()
        assert "rlperkins%40streamflo.com" in msg.body_html or "rlperkins@streamflo.com" in msg.body_html

    def test_links_point_to_base_url(self):
        msg = approver_email()
        assert BASE_URL in msg.body_html


class TestApproverEmailChain:

    def test_shows_current_step_awaiting(self):
        msg = approver_email(step=0)
        assert "Awaiting your decision" in msg.body_html

    def test_pending_roles_shown_for_later_steps(self):
        msg = approver_email(step=0)
        assert "Pending" in msg.body_html

    def test_step_1_shows_step_0_as_approved(self):
        previous = [{"name": "Rae-Lynn Perkins", "role": "HR Manager",
                     "decision": "Approved", "date": "2026-04-12T10:00:00+00:00", "comments": ""}]
        msg = build_approver_email(
            base_url=BASE_URL,
            request_id=REQUEST_ID,
            approver_name="Keith Haynes",
            approver_email="khaynes@streamflo.com",
            request_details=REQUEST_DETAILS,
            workflow_name="Backfill – Budgeted",
            approval_chain=CHAIN_3,
            current_step=1,
            previous_approvals=previous,
        )
        assert "dot-done" in msg.body_html
        assert "Rae-Lynn Perkins" in msg.body_html

    def test_step_counter_in_body(self):
        msg = approver_email(step=0)
        assert "step 1 of 3" in msg.body_html

    def test_step_2_shows_step_2_of_3(self):
        msg = approver_email(step=1)
        assert "step 2 of 3" in msg.body_html

    def test_no_previous_approvals_no_approved_by_row(self):
        msg = approver_email(step=0, previous=[])
        assert "Approved by:" not in msg.body_html

    def test_previous_approvals_shown(self):
        previous = [{"name": "Rae-Lynn Perkins", "role": "HR Manager",
                     "decision": "Approved", "date": "2026-04-12T10:00:00+00:00", "comments": ""}]
        msg = approver_email(step=1, previous=previous)
        assert "Approved by:" in msg.body_html


class TestApproverEmailEdgeCases:

    def test_empty_notes_no_notes_row(self):
        details = {**REQUEST_DETAILS, "notes": ""}
        msg = build_approver_email(
            base_url=BASE_URL, request_id=REQUEST_ID,
            approver_name="Rae-Lynn Perkins", approver_email="rlperkins@streamflo.com",
            request_details=details, workflow_name="Backfill – Budgeted",
            approval_chain=CHAIN_3, current_step=0, previous_approvals=[],
        )
        assert "Notes:" not in msg.body_html

    def test_single_step_chain(self):
        msg = build_approver_email(
            base_url=BASE_URL, request_id=REQUEST_ID,
            approver_name="Rae-Lynn Perkins", approver_email="rlperkins@streamflo.com",
            request_details=REQUEST_DETAILS, workflow_name="Quick Approval",
            approval_chain=["HR Manager"], current_step=0, previous_approvals=[],
        )
        assert "step 1 of 1" in msg.body_html

    def test_long_employee_name_doesnt_break(self):
        details = {**REQUEST_DETAILS, "employee_name": "Jean-Baptiste Villeneuve-Thibodeau III"}
        msg = build_approver_email(
            base_url=BASE_URL, request_id=REQUEST_ID,
            approver_name="Rae-Lynn Perkins", approver_email="rlperkins@streamflo.com",
            request_details=details, workflow_name="Backfill – Budgeted",
            approval_chain=CHAIN_3, current_step=0, previous_approvals=[],
        )
        assert "Jean-Baptiste Villeneuve-Thibodeau III" in msg.body_html
        assert "Jean-Baptiste Villeneuve-Thibodeau III" in msg.subject

    def test_four_step_chain(self):
        chain = ["HR Manager", "2nd Level Manager", "GM/Director", "CEO"]
        msg = build_approver_email(
            base_url=BASE_URL, request_id=REQUEST_ID,
            approver_name="Mark McNeill", approver_email="mmcneill@streamflo.com",
            request_details=REQUEST_DETAILS, workflow_name="New Position – Unbudgeted",
            approval_chain=chain, current_step=3, previous_approvals=[
                {"name": "Rae-Lynn Perkins", "role": "HR Manager", "decision": "Approved",
                 "date": "2026-04-12T10:00:00+00:00", "comments": ""},
                {"name": "Keith Haynes", "role": "2nd Level Manager", "decision": "Approved",
                 "date": "2026-04-12T11:00:00+00:00", "comments": ""},
                {"name": "Quanah Gilmore", "role": "GM/Director", "decision": "Approved",
                 "date": "2026-04-12T12:00:00+00:00", "comments": ""},
            ],
        )
        assert "step 4 of 4" in msg.body_html
        assert "Awaiting your decision" in msg.body_html


# ===========================================================================
# build_notify_email
# ===========================================================================

class TestNotifyEmailStructure:

    def _make(self, **kwargs):
        defaults = dict(
            notify_name="Sandra Carrisalez",
            notify_email="scarrisalez@streamflo.com",
            request_details=REQUEST_DETAILS,
            workflow_name="Backfill – Budgeted",
            notify_role="Benefits Specialist",
        )
        defaults.update(kwargs)
        return build_notify_email(**defaults)

    def test_returns_email_message(self):
        assert isinstance(self._make(), EmailMessage)

    def test_to_is_notify_email(self):
        assert self._make().to == "scarrisalez@streamflo.com"

    def test_subject_starts_with_fyi(self):
        assert self._make().subject.startswith("FYI:")

    def test_subject_contains_request_type(self):
        assert "Backfill" in self._make().subject

    def test_subject_contains_employee_name(self):
        assert "John Smith" in self._make().subject

    def test_body_contains_notify_name(self):
        assert "Sandra Carrisalez" in self._make().body_html

    def test_body_contains_employee_name(self):
        assert "John Smith" in self._make().body_html

    def test_body_contains_fully_approved(self):
        assert "Fully Approved" in self._make().body_html

    def test_body_has_no_action_required_banner(self):
        assert "notification only" in self._make().body_html.lower() or \
               "no action" in self._make().body_html.lower()

    def test_body_has_no_approve_button(self):
        # btn-approve exists in the shared CSS block, so verify no action links in the body
        assert "approval-action" not in self._make().body_html

    def test_body_shows_notify_role(self):
        assert "Benefits Specialist" in self._make().body_html

    def test_effective_date_shown(self):
        assert "2026-05-01" in self._make().body_html

    def test_no_effective_date_row_when_blank(self):
        details = {**REQUEST_DETAILS, "effective_date": ""}
        msg = self._make(request_details=details)
        assert "Effective date:" not in msg.body_html

    def test_plain_text_says_no_action_required(self):
        assert "No action required" in self._make().body_text

    def test_plain_text_has_employee_name(self):
        assert "John Smith" in self._make().body_text

    def test_html_is_valid(self):
        msg = self._make()
        assert msg.body_html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in msg.body_html


# ===========================================================================
# build_requester_email — approved
# ===========================================================================

class TestRequesterEmailApproved:

    def _make(self, **kwargs):
        defaults = dict(
            requester_name="Chris Hayslip",
            requester_email="chayslip@streamflo.com",
            request_details=REQUEST_DETAILS,
            approved=True,
            pdf_url="https://streamflogroup.sharepoint.com/hrcp/hrst/HR%20Records/2026/04/approval.pdf",
        )
        defaults.update(kwargs)
        return build_requester_email(**defaults)

    def test_returns_email_message(self):
        assert isinstance(self._make(), EmailMessage)

    def test_to_is_requester_email(self):
        assert self._make().to == "chayslip@streamflo.com"

    def test_subject_says_approved(self):
        assert "approved" in self._make().subject.lower()

    def test_subject_does_not_say_rejected(self):
        assert "rejected" not in self._make().subject.lower()

    def test_subject_contains_request_type(self):
        assert "backfill" in self._make().subject.lower()

    def test_body_contains_requester_name(self):
        assert "Chris Hayslip" in self._make().body_html

    def test_body_shows_fully_approved(self):
        assert "Fully Approved" in self._make().body_html

    def test_body_has_pdf_link(self):
        assert "HR%20Records" in self._make().body_html

    def test_body_has_view_pdf_link_text(self):
        assert "approval record" in self._make().body_html.lower()

    def test_no_rejection_reason_shown(self):
        # rejection-reason is a CSS class in the shared style block; check the visible label instead
        assert "Reason for rejection" not in self._make().body_html

    def test_plain_text_says_approved(self):
        assert "approved" in self._make().body_text.lower()

    def test_plain_text_has_pdf_url(self):
        assert "HR%20Records" in self._make().body_text

    def test_approved_without_pdf_url_still_works(self):
        msg = self._make(pdf_url="")
        assert isinstance(msg, EmailMessage)
        assert "approved" in msg.subject.lower()
        assert "View approval record PDF" not in msg.body_html


# ===========================================================================
# build_requester_email — rejected
# ===========================================================================

class TestRequesterEmailRejected:

    def _make(self, **kwargs):
        defaults = dict(
            requester_name="Chris Hayslip",
            requester_email="chayslip@streamflo.com",
            request_details=REQUEST_DETAILS,
            approved=False,
            rejected_by="Rae-Lynn Perkins",
            rejection_comments="Q2 headcount freeze in effect.",
        )
        defaults.update(kwargs)
        return build_requester_email(**defaults)

    def test_subject_says_rejected(self):
        assert "rejected" in self._make().subject.lower()

    def test_subject_does_not_say_approved(self):
        assert "approved" not in self._make().subject.lower()

    def test_body_shows_rejected_status(self):
        assert "Rejected" in self._make().body_html

    def test_body_shows_rejected_by(self):
        assert "Rae-Lynn Perkins" in self._make().body_html

    def test_rejection_comments_in_body(self):
        assert "Q2 headcount freeze" in self._make().body_html

    def test_rejection_reason_block_present(self):
        assert "rejection-reason" in self._make().body_html

    def test_no_pdf_link_on_rejection(self):
        assert "View approval record PDF" not in self._make().body_html

    def test_plain_text_says_rejected(self):
        assert "rejected" in self._make().body_text.lower()

    def test_plain_text_has_rejection_reason(self):
        assert "Q2 headcount freeze" in self._make().body_text

    def test_no_rejection_comments_no_reason_block(self):
        msg = self._make(rejection_comments="")
        # rejection-reason is a CSS class in the shared style block; check the visible label instead
        assert "Reason for rejection" not in msg.body_html

    def test_rejected_by_in_message(self):
        assert "Rae-Lynn Perkins" in self._make().body_html
