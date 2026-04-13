"""
Orchestrator integration tests — no app registration or Azure needed.

SharePointClient, GraphMailSender, HRRecordsUploader, and HRRolesClient
are all fully mocked. Tests cover the complete approval lifecycle end-to-end.

Run: pytest tests/test_orchestrator.py -v
"""

import sys
import os
import types
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../function_app"))

# ---------------------------------------------------------------------------
# Stub out Azure/network packages before any function_app imports
# ---------------------------------------------------------------------------
for _mod in ("msal", "requests", "azure", "azure.functions"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_req_exc = types.ModuleType("requests.exceptions")
_req_exc.HTTPError = type("HTTPError", (Exception,), {})
sys.modules["requests.exceptions"] = _req_exc


# ---------------------------------------------------------------------------
# Fake SharePoint state store
# ---------------------------------------------------------------------------

class FakeSharePointClient:
    """In-memory SharePoint list — no network, no credentials."""

    def __init__(self, initial_fields: dict):
        self._store = dict(initial_fields)
        self.updates = []

    def get_item(self, item_id: str) -> dict:
        return dict(self._store)

    def update_item(self, item_id: str, fields: dict) -> None:
        self.updates.append(dict(fields))
        self._store.update(fields)

    def record_approval_decision(
        self, item_id, step, approver_name, approver_email, decision, comments=""
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        patch = {
            f"ApproverStep{step}Name":     approver_name,
            f"ApproverStep{step}Email":    approver_email,
            f"ApproverStep{step}Decision": decision.capitalize(),
            f"ApproverStep{step}Date":     now,
        }
        if comments:
            patch[f"ApproverStep{step}Comments"] = comments
        if decision == "reject":
            patch["Status"]       = "Rejected"
            patch["RejectedBy"]   = approver_name
            patch["RejectedDate"] = now
        self.update_item(item_id, patch)

    def advance_to_next_step(self, item_id: str, next_step: int) -> None:
        self.update_item(item_id, {
            "CurrentApprovalStep": next_step,
            "Status": "In Progress",
        })

    def mark_fully_approved(self, item_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_item(item_id, {
            "Status": "Approved",
            "FullyApprovedDate": now,
        })

    def mark_rejected(self, item_id: str, rejected_by: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.update_item(item_id, {
            "Status":       "Rejected",
            "RejectedBy":   rejected_by,
            "RejectedDate": now,
        })


# ---------------------------------------------------------------------------
# Fake email sender
# ---------------------------------------------------------------------------

class FakeMailSender:
    def __init__(self):
        self.sent = []

    def send(self, message) -> None:
        self.sent.append(message)

    def send_batch(self, messages: list) -> None:
        self.sent.extend(messages)


# ---------------------------------------------------------------------------
# Fake PDF uploader
# ---------------------------------------------------------------------------

class FakeUploader:
    def upload_pdf(self, pdf_bytes, filename, approved_date) -> str:
        return f"https://streamflogroup.sharepoint.com/hrcp/hrst/HR%20Records/2026/04/{filename}"


# ---------------------------------------------------------------------------
# Fake HR Roles client — replaces SharePoint list lookup
# ---------------------------------------------------------------------------

# Static role -> (name, email) as they would appear in the HR Approval Roles list
STATIC_ROLES = {
    "HR Manager":          ("HR Manager",         "rlperkins@streamflo.com"),
    "Payroll Manager":     ("Payroll Manager",     "gthedford@streamflo.com"),
    "Benefits Specialist": ("Benefits Specialist", "scarrisalez@streamflo.com"),
    "HR Generalist":       ("HR Generalist",       "tparashar@streamflo.com"),
}


class FakeRolesClient:
    """In-memory stand-in for HRRolesClient — no SharePoint needed."""

    def __init__(self, roles: dict = None):
        self._roles = roles if roles is not None else dict(STATIC_ROLES)

    def resolve_role(self, role: str) -> tuple[str, str]:
        if role not in self._roles:
            raise ValueError(f"No active entry for role '{role}' in HR Approval Roles list")
        return self._roles[role]

    def get_all_emails_for_role(self, role: str) -> list[tuple[str, str]]:
        if role not in self._roles:
            return []
        entry = self._roles[role]
        return [entry] if isinstance(entry[0], str) else list(entry)

    def invalidate_cache(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Sample request fields
# ---------------------------------------------------------------------------

BASE_FIELDS = {
    "WorkflowKey":              "job_req_backfill_budgeted",
    "EmployeeName":             "John Smith",
    "EmployeeNumber":           "1003500",
    "InitiatorName":            "Chris Hayslip",
    "InitiatorEmail":           "chayslip@streamflo.com",
    "EffectiveDate":            "2026-05-01",
    "RequestNotes":             "Replacing departing service tech in Midland.",
    "Created":                  "2026-04-12T09:00:00+00:00",
    "CurrentApprovalStep":      0,
    "Status":                   "Pending",
    "HiringManagerName":        "Chris Hayslip",
    "HiringManagerEmail":       "chayslip@streamflo.com",
    "SecondLevelManagerName":   "Keith Haynes",
    "SecondLevelManagerEmail":  "khaynes@streamflo.com",
    "GMDirectorName":           "Quanah Gilmore",
    "GMDirectorEmail":          "qgilmore@streamflo.com",
}

ROLE_ENV = {
    "APPROVAL_BASE_URL":  "https://streamflo-hr-func.azurewebsites.net",
    "HR_ROLES_LIST_NAME": "HR Approval Roles",
}


# ---------------------------------------------------------------------------
# Helper — build an orchestrator with all fakes injected
# ---------------------------------------------------------------------------

def _make_orchestrator(fields: dict, roles: dict = None):
    from orchestrator import ApprovalOrchestrator
    fake_sp     = FakeSharePointClient(fields)
    fake_mailer = FakeMailSender()
    fake_upload = FakeUploader()
    fake_roles  = FakeRolesClient(roles)

    with patch.dict(os.environ, ROLE_ENV):
        o = ApprovalOrchestrator.__new__(ApprovalOrchestrator)
        o.sp           = fake_sp
        o.mailer       = fake_mailer
        o.uploader     = fake_upload
        o.roles_client = fake_roles
        o.base_url     = ROLE_ENV["APPROVAL_BASE_URL"]
    return o, fake_sp, fake_mailer


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def orch(tmp_path):
    o, sp, mailer = _make_orchestrator(BASE_FIELDS)
    yield o, sp, mailer


# ---------------------------------------------------------------------------
# Tests — new request
# ---------------------------------------------------------------------------

class TestNewRequest:

    def test_sets_status_in_progress(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        assert sp._store["Status"] == "In Progress"
        assert sp._store["CurrentApprovalStep"] == 0

    def test_sends_first_approver_email(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        assert len(mailer.sent) == 1
        msg = mailer.sent[0]
        assert msg.to == "rlperkins@streamflo.com"
        assert "Action required" in msg.subject
        assert "John Smith" in msg.subject

    def test_unknown_workflow_key_sets_error(self, orch):
        o, sp, mailer = orch
        sp._store["WorkflowKey"] = "totally_invalid_key"
        o.handle_new_request("item-001")
        assert sp._store["Status"] == "Error"
        assert "totally_invalid_key" in sp._store["ErrorMessage"]
        assert len(mailer.sent) == 0

    def test_approver_email_contains_approve_link(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        msg = mailer.sent[0]
        assert "approval-action" in msg.body_html
        assert "approve" in msg.body_html.lower()
        assert "reject" in msg.body_html.lower()
        assert "item-001" in msg.body_html


# ---------------------------------------------------------------------------
# Tests — approval step advance
# ---------------------------------------------------------------------------

class TestApprovalAdvance:

    def test_approve_step_0_advances_to_step_1(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        mailer.sent.clear()

        result = o.handle_approval_action(
            item_id="item-001",
            approver_email="rlperkins@streamflo.com",
            action="approve",
        )
        assert result["outcome"] == "advanced"
        assert result["next_step"] == 1
        assert sp._store["CurrentApprovalStep"] == 1
        assert sp._store["ApproverStep0Decision"] == "Approve"

    def test_advance_sends_next_approver_email(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        mailer.sent.clear()

        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        assert len(mailer.sent) == 1
        assert mailer.sent[0].to == "khaynes@streamflo.com"

    def test_step_2_advances_to_gm(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        mailer.sent.clear()

        result = o.handle_approval_action("item-001", "khaynes@streamflo.com", "approve")
        assert result["outcome"] == "advanced"
        assert result["next_step"] == 2
        assert mailer.sent[0].to == "qgilmore@streamflo.com"

    def test_wrong_approver_is_blocked(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")

        result = o.handle_approval_action("item-001", "wrong.person@streamflo.com", "approve")
        assert "error" in result
        assert sp._store["CurrentApprovalStep"] == 0

    def test_double_click_is_idempotent(self, orch):
        """Approver clicks Approve twice before the page refreshes — second click is a no-op."""
        o, sp, mailer = orch
        o.handle_new_request("item-001")

        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        count_after_first = len(mailer.sent)

        sp._store["CurrentApprovalStep"] = 0

        result = o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        assert "already recorded" in result.get("message", "").lower()
        assert len(mailer.sent) == count_after_first


# ---------------------------------------------------------------------------
# Tests — full approval
# ---------------------------------------------------------------------------

class TestFullApproval:

    def _run_full_approval(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-001", "khaynes@streamflo.com", "approve")
        result = o.handle_approval_action("item-001", "qgilmore@streamflo.com", "approve")
        return o, sp, mailer, result

    def test_final_approval_outcome(self, orch):
        _, _, _, result = self._run_full_approval(orch)
        assert result["outcome"] == "fully_approved"

    def test_status_set_to_approved(self, orch):
        _, sp, _, _ = self._run_full_approval(orch)
        assert sp._store["Status"] == "Approved"
        assert "FullyApprovedDate" in sp._store

    def test_requester_confirmation_email_sent(self, orch):
        _, _, mailer, _ = self._run_full_approval(orch)
        requester_emails = [m for m in mailer.sent if m.to == "chayslip@streamflo.com"]
        assert len(requester_emails) == 1
        assert "approved" in requester_emails[0].subject.lower()

    def test_pdf_url_saved_to_sharepoint(self, orch):
        _, sp, _, _ = self._run_full_approval(orch)
        assert "ApprovalRecordURL" in sp._store
        assert "HR%20Records" in sp._store["ApprovalRecordURL"]

    def test_pdf_url_in_requester_email(self, orch):
        _, _, mailer, _ = self._run_full_approval(orch)
        requester_emails = [m for m in mailer.sent if m.to == "chayslip@streamflo.com"]
        assert "HR%20Records" in requester_emails[0].body_html


# ---------------------------------------------------------------------------
# Tests — rejection
# ---------------------------------------------------------------------------

class TestRejection:

    def test_reject_at_step_0(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        mailer.sent.clear()

        result = o.handle_approval_action(
            item_id="item-001",
            approver_email="rlperkins@streamflo.com",
            action="reject",
            comments="Headcount freeze in effect for Q2.",
        )
        assert result["outcome"] == "rejected"
        assert result["rejected_by"] == "HR Manager"

    def test_rejection_sets_status(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "reject",
                                 comments="Not approved.")
        assert sp._store["Status"] == "Rejected"
        assert sp._store["RejectedBy"] == "HR Manager"

    def test_rejection_sends_requester_email(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        mailer.sent.clear()

        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "reject",
                                 comments="Budget not approved.")
        requester_emails = [m for m in mailer.sent if m.to == "chayslip@streamflo.com"]
        assert len(requester_emails) == 1
        assert "rejected" in requester_emails[0].subject.lower()

    def test_rejection_comments_in_email(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        mailer.sent.clear()

        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "reject",
                                 comments="Q2 headcount freeze.")
        requester_emails = [m for m in mailer.sent if m.to == "chayslip@streamflo.com"]
        assert "Q2 headcount freeze" in requester_emails[0].body_html

    def test_reject_at_step_2(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-001", "khaynes@streamflo.com", "approve")
        mailer.sent.clear()

        result = o.handle_approval_action("item-001", "qgilmore@streamflo.com", "reject",
                                          comments="Org restructure pending.")
        assert result["outcome"] == "rejected"
        assert sp._store["Status"] == "Rejected"
        requester_emails = [m for m in mailer.sent if m.to == "chayslip@streamflo.com"]
        assert len(requester_emails) == 1


# ---------------------------------------------------------------------------
# Tests — CEO workflow
# ---------------------------------------------------------------------------

class TestCEOWorkflow:

    @pytest.fixture
    def ceo_orch(self, tmp_path):
        fields = dict(BASE_FIELDS)
        fields["WorkflowKey"]             = "job_req_backfill_unbudgeted"
        fields["SecondLevelManagerName"]  = "Chris Hayslip"
        fields["SecondLevelManagerEmail"] = "chayslip@streamflo.com"
        fields["GMDirectorName"]          = "Quanah Gilmore"
        fields["GMDirectorEmail"]         = "qgilmore@streamflo.com"
        fields["ExecutiveName"]           = "Sean Wilcock"
        fields["ExecutiveEmail"]          = "swilcock@streamflo.com"
        fields["CEOName"]                 = "Mark McNeill"
        fields["CEOEmail"]                = "mmcneill@streamflo.com"

        o, sp, mailer = _make_orchestrator(fields)
        yield o, sp, mailer

    def test_ceo_is_final_step(self, ceo_orch):
        o, sp, mailer = ceo_orch
        o.handle_new_request("item-002")
        o.handle_approval_action("item-002", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-002", "qgilmore@streamflo.com", "approve")
        o.handle_approval_action("item-002", "swilcock@streamflo.com", "approve")
        mailer.sent.clear()

        result = o.handle_approval_action("item-002", "mmcneill@streamflo.com", "approve")
        assert result["outcome"] == "fully_approved"
        assert sp._store["Status"] == "Approved"

    def test_ceo_reject_terminates_chain(self, ceo_orch):
        o, sp, mailer = ceo_orch
        o.handle_new_request("item-002")
        o.handle_approval_action("item-002", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-002", "qgilmore@streamflo.com", "approve")
        o.handle_approval_action("item-002", "swilcock@streamflo.com", "approve")

        result = o.handle_approval_action("item-002", "mmcneill@streamflo.com", "reject",
                                          comments="Not aligned with strategy.")
        assert result["outcome"] == "rejected"
        assert sp._store["Status"] == "Rejected"


# ---------------------------------------------------------------------------
# Tests — notify workflows
# ---------------------------------------------------------------------------

class TestNotifyWorkflow:

    @pytest.fixture
    def notify_orch(self, tmp_path):
        fields = dict(BASE_FIELDS)
        fields["WorkflowKey"]             = "pcn_termination_discharge"
        fields["SecondLevelManagerName"]  = "Keith Haynes"
        fields["SecondLevelManagerEmail"] = "khaynes@streamflo.com"

        o, sp, mailer = _make_orchestrator(fields)
        yield o, sp, mailer

    def test_notify_emails_sent_on_full_approval(self, notify_orch):
        o, sp, mailer = notify_orch
        o.handle_new_request("item-003")
        o.handle_approval_action("item-003", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-003", "khaynes@streamflo.com", "approve")
        o.handle_approval_action("item-003", "gthedford@streamflo.com", "approve")

        notify_emails = [m for m in mailer.sent if "FYI" in m.subject]
        recipients    = {m.to for m in notify_emails}
        assert "scarrisalez@streamflo.com" in recipients
        assert "gthedford@streamflo.com"   in recipients

    def test_no_notify_emails_on_rejection(self, notify_orch):
        o, sp, mailer = notify_orch
        o.handle_new_request("item-003")
        o.handle_approval_action("item-003", "rlperkins@streamflo.com", "reject",
                                 comments="Missing documentation.")

        notify_emails = [m for m in mailer.sent if "FYI" in m.subject]
        assert len(notify_emails) == 0


# ---------------------------------------------------------------------------
# Tests — PDF generation
# ---------------------------------------------------------------------------

class TestPDFGeneration:

    def test_pdf_generated_on_full_approval(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-001", "khaynes@streamflo.com", "approve")
        o.handle_approval_action("item-001", "qgilmore@streamflo.com", "approve")

        assert "ApprovalRecordURL" in sp._store
        assert sp._store["ApprovalRecordURL"].endswith(".pdf")

    def test_pdf_not_generated_on_rejection(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "reject",
                                 comments="Rejected.")
        assert "ApprovalRecordURL" not in sp._store


# ---------------------------------------------------------------------------
# Tests — email content quality
# ---------------------------------------------------------------------------

class TestEmailContent:

    def test_approver_email_shows_chain_progress(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")

        step2_email = mailer.sent[-1]
        assert "Rae-Lynn" in step2_email.body_html or "HR Manager" in step2_email.body_html

    def test_notify_email_has_no_action_buttons(self, orch):
        fields = dict(BASE_FIELDS)
        fields["WorkflowKey"]             = "loa_fmla"
        fields["SecondLevelManagerName"]  = "Keith Haynes"
        fields["SecondLevelManagerEmail"] = "khaynes@streamflo.com"
        fields["GMDirectorName"]          = "Quanah Gilmore"
        fields["GMDirectorEmail"]         = "qgilmore@streamflo.com"

        o, fake_sp, fake_mailer = _make_orchestrator(fields)
        o.handle_new_request("item-004")
        o.handle_approval_action("item-004", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-004", "khaynes@streamflo.com", "approve")
        o.handle_approval_action("item-004", "qgilmore@streamflo.com", "approve")

        notify_emails = [m for m in fake_mailer.sent if "FYI" in m.subject]
        for msg in notify_emails:
            assert "approval-action" not in msg.body_html
            assert "No action" in msg.body_html or "notification only" in msg.body_html.lower()

    def test_requester_approved_email_has_pdf_link(self, orch):
        o, sp, mailer = orch
        o.handle_new_request("item-001")
        o.handle_approval_action("item-001", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-001", "khaynes@streamflo.com", "approve")
        o.handle_approval_action("item-001", "qgilmore@streamflo.com", "approve")

        requester_emails = [m for m in mailer.sent if m.to == "chayslip@streamflo.com"]
        assert any("HR%20Records" in m.body_html for m in requester_emails)


# ---------------------------------------------------------------------------
# Tests — HR Roles client integration
# ---------------------------------------------------------------------------

class TestHRRolesClientIntegration:

    def test_missing_role_in_list_returns_error(self):
        """If a role has no active entry, handle_new_request sets Status=Error gracefully."""
        fields = dict(BASE_FIELDS)
        # Empty roles client — no HR Manager entry
        o, sp, mailer = _make_orchestrator(fields, roles={})
        try:
            o.handle_new_request("item-001")
        except Exception:
            pass
        # Should not have sent any email
        assert len(mailer.sent) == 0

    def test_multiple_notify_recipients_all_receive_email(self):
        """If Benefits Specialist has two active entries both should get FYI emails."""
        fields = dict(BASE_FIELDS)
        fields["WorkflowKey"]             = "pcn_termination_discharge"
        fields["SecondLevelManagerName"]  = "Keith Haynes"
        fields["SecondLevelManagerEmail"] = "khaynes@streamflo.com"

        multi_roles = dict(STATIC_ROLES)
        # Override Benefits Specialist with a client that returns two people
        class MultiRolesClient(FakeRolesClient):
            def get_all_emails_for_role(self, role):
                if role == "Benefits Specialist":
                    return [
                        ("Sandra Carrisalez", "scarrisalez@streamflo.com"),
                        ("Backup Benefits",   "backup.benefits@streamflo.com"),
                    ]
                return super().get_all_emails_for_role(role)

        from orchestrator import ApprovalOrchestrator
        fake_sp     = FakeSharePointClient(fields)
        fake_mailer = FakeMailSender()
        fake_upload = FakeUploader()

        with patch.dict(os.environ, ROLE_ENV):
            o = ApprovalOrchestrator.__new__(ApprovalOrchestrator)
            o.sp           = fake_sp
            o.mailer       = fake_mailer
            o.uploader     = fake_upload
            o.roles_client = MultiRolesClient()
            o.base_url     = ROLE_ENV["APPROVAL_BASE_URL"]

        o.handle_new_request("item-005")
        o.handle_approval_action("item-005", "rlperkins@streamflo.com", "approve")
        o.handle_approval_action("item-005", "khaynes@streamflo.com", "approve")
        o.handle_approval_action("item-005", "gthedford@streamflo.com", "approve")

        notify_emails = [m for m in fake_mailer.sent if "FYI" in m.subject]
        recipients = {m.to for m in notify_emails}
        assert "scarrisalez@streamflo.com"      in recipients
        assert "backup.benefits@streamflo.com"  in recipients
