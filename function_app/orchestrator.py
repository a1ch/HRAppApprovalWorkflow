"""
Approval orchestration engine.
Handles the full lifecycle: trigger → sequential approval chain → notifications → completion.
Stateless — all state lives in SharePoint. Safe to retry.
"""

import logging
import os
from typing import Optional

from approval_matrix import ApprovalWorkflow, get_workflow
from email_templates import (
    build_approver_email,
    build_notify_email,
    build_requester_email,
)
from hr_records_uploader import HRRecordsUploader
from hr_roles_client import HRRolesClient
from mail_sender import GraphMailSender
from pdf_generator import build_pdf_filename, generate_approval_pdf
from sharepoint_client import SharePointClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role resolution
#
# Two categories of role:
#   Dynamic — person is named on the request form itself (Direct Manager,
#             2nd Level Manager, Hiring Manager, GM/Director, Executive, CEO).
#             Resolved from the SharePoint item fields.
#
#   Static  — organisational roles managed by HR (HR Manager, Payroll Manager,
#             Benefits Specialist, HR Generalist).
#             Resolved from the HR Approval Roles SharePoint list via HRRolesClient.
# ---------------------------------------------------------------------------

DYNAMIC_ROLE_FIELD_MAP = {
    "Direct Manager":    ("DirectManagerName",     "DirectManagerEmail"),
    "2nd Level Manager": ("SecondLevelManagerName", "SecondLevelManagerEmail"),
    "Hiring Manager":    ("HiringManagerName",      "HiringManagerEmail"),
    "GM/Director":       ("GMDirectorName",         "GMDirectorEmail"),
    "Executive":         ("ExecutiveName",           "ExecutiveEmail"),
    "CEO":               ("CEOName",                 "CEOEmail"),
}


def _resolve_dynamic_role(role: str, request_fields: dict) -> tuple[str, str]:
    """Resolve a role whose person is recorded on the request itself."""
    if role not in DYNAMIC_ROLE_FIELD_MAP:
        raise ValueError(f"'{role}' is not a dynamic role")
    name_field, email_field = DYNAMIC_ROLE_FIELD_MAP[role]
    name  = request_fields.get(name_field, role)
    email = request_fields.get(email_field, "")
    if not email:
        raise ValueError(f"Missing email for dynamic role '{role}' in request fields")
    return name, email


def resolve_role(
    role: str,
    request_fields: dict,
    roles_client: Optional[HRRolesClient] = None,
) -> tuple[str, str]:
    """
    Resolve any role to (name, email).

    Order of resolution:
      1. Dynamic — look up from request fields (no network call)
      2. Static  — look up from HR Approval Roles list via HRRolesClient
    """
    # 1. Try dynamic first
    if role in DYNAMIC_ROLE_FIELD_MAP:
        try:
            return _resolve_dynamic_role(role, request_fields)
        except ValueError as e:
            logger.warning("Dynamic role resolution failed for '%s': %s", role, e)

    # 2. Fall back to HR Approval Roles list
    if roles_client is not None:
        return roles_client.resolve_role(role)

    raise ValueError(
        f"Cannot resolve role '{role}': not a dynamic role and no HRRolesClient provided"
    )


class ApprovalOrchestrator:
    def __init__(self):
        self.sp           = SharePointClient()
        self.mailer       = GraphMailSender()
        self.uploader     = HRRecordsUploader()
        self.roles_client = HRRolesClient(self.sp)
        self.base_url     = os.environ.get("APPROVAL_BASE_URL", "").rstrip("/")

    # ── Entry points ──────────────────────────────────────────────────────

    def handle_new_request(self, item_id: str) -> None:
        fields       = self.sp.get_item(item_id)
        workflow_key = fields.get("WorkflowKey", "")
        workflow     = get_workflow(workflow_key)

        if not workflow:
            logger.error("Unknown workflow key '%s' for item %s", workflow_key, item_id)
            self.sp.update_item(item_id, {
                "Status": "Error",
                "ErrorMessage": f"Unknown workflow: {workflow_key}",
            })
            return

        logger.info("New request %s: %s", item_id, workflow.request_type)
        self.sp.update_item(item_id, {
            "Status": "In Progress",
            "CurrentApprovalStep": 0,
            "WorkflowCategory": workflow.category.value,
        })
        self._send_approver_email(item_id, fields, workflow, step=0, previous_approvals=[])

    def handle_approval_action(
        self,
        item_id: str,
        approver_email: str,
        action: str,        # "approve" | "reject"
        comments: str = "",
        list_key: str = "",
    ) -> dict:
        """
        Called when an approver clicks Approve or Reject (after entering comments).
        Returns a dict with outcome info for the HTTP response.
        """
        fields       = self.sp.get_item(item_id)
        workflow_key = fields.get("WorkflowKey", "")
        workflow     = get_workflow(workflow_key)

        if not workflow:
            return {"error": "Workflow not found", "request_id": item_id}

        current_step = int(fields.get("CurrentApprovalStep", 0))
        chain = workflow.approval_chain
        if workflow.requires_ceo:
            chain = chain + ["CEO"]

        expected_role = chain[current_step]
        expected_name, expected_email = resolve_role(
            expected_role, fields, self.roles_client
        )

        if approver_email.lower() != expected_email.lower():
            logger.warning(
                "Unexpected approver %s for step %d (expected %s)",
                approver_email, current_step, expected_email,
            )
            return {"error": "Not the expected approver for this step", "request_id": item_id}

        existing_decision = fields.get(f"ApproverStep{current_step}Decision", "")
        if existing_decision:
            return {
                "message": f"Step {current_step} already recorded as {existing_decision}",
                "request_id": item_id,
            }

        self.sp.record_approval_decision(
            item_id=item_id,
            step=current_step,
            approver_name=expected_name,
            approver_email=approver_email,
            decision=action,
            comments=comments,
        )

        request_details = self._extract_request_details(fields, workflow)

        if action == "reject":
            self._handle_rejection(
                item_id, fields, workflow, expected_name, request_details,
                comments=comments,
            )
            return {"outcome": "rejected", "request_id": item_id, "rejected_by": expected_name}

        next_step = current_step + 1
        if next_step < len(chain):
            self.sp.advance_to_next_step(item_id, next_step)
            previous_approvals = self._collect_previous_approvals(fields, current_step + 1)
            self._send_approver_email(
                item_id, fields, workflow, step=next_step,
                previous_approvals=previous_approvals,
            )
            return {"outcome": "advanced", "request_id": item_id, "next_step": next_step}
        else:
            self._handle_full_approval(item_id, fields, workflow, request_details)
            return {"outcome": "fully_approved", "request_id": item_id}

    # ── Internal helpers ──────────────────────────────────────────────────

    def _send_approver_email(
        self,
        item_id: str,
        fields: dict,
        workflow: ApprovalWorkflow,
        step: int,
        previous_approvals: list[dict],
    ) -> None:
        chain = workflow.approval_chain + (["CEO"] if workflow.requires_ceo else [])
        role  = chain[step]
        name, email = resolve_role(role, fields, self.roles_client)
        request_details = self._extract_request_details(fields, workflow)

        msg = build_approver_email(
            base_url=self.base_url,
            request_id=item_id,
            approver_name=name,
            approver_email=email,
            request_details=request_details,
            workflow_name=workflow.request_type,
            approval_chain=chain,
            current_step=step,
            previous_approvals=previous_approvals,
        )
        self.mailer.send(msg)
        logger.info("Sent step %d approval request to %s (%s)", step, name, email)

    def _handle_rejection(
        self,
        item_id: str,
        fields: dict,
        workflow: ApprovalWorkflow,
        rejected_by: str,
        request_details: dict,
        comments: str = "",
    ) -> None:
        self.sp.mark_rejected(item_id, rejected_by)
        initiator_name  = fields.get("InitiatorName", "")
        initiator_email = fields.get("InitiatorEmail", "")
        if initiator_email:
            msg = build_requester_email(
                requester_name=initiator_name,
                requester_email=initiator_email,
                request_details=request_details,
                approved=False,
                rejected_by=rejected_by,
                rejection_comments=comments,
            )
            self.mailer.send(msg)
        logger.info("Request %s rejected by %s. Comments: %s", item_id, rejected_by, comments)

    def _handle_full_approval(
        self,
        item_id: str,
        fields: dict,
        workflow: ApprovalWorkflow,
        request_details: dict,
    ) -> None:
        self.sp.mark_fully_approved(item_id)
        updated             = self.sp.get_item(item_id)
        fully_approved_date = updated.get("FullyApprovedDate", "")

        chain     = workflow.approval_chain + (["CEO"] if workflow.requires_ceo else [])
        approvals = self._collect_previous_approvals(fields, len(chain))

        pdf_url = ""
        try:
            pdf_bytes = generate_approval_pdf(
                request_details=request_details,
                workflow_name=workflow.request_type,
                workflow_category=workflow.category.value,
                approvals=approvals,
                notify_roles=workflow.notify_roles,
                fully_approved_date=fully_approved_date,
                request_id=item_id,
            )
            filename = build_pdf_filename(
                employee_name=request_details.get("employee_name", "Unknown"),
                request_type=workflow.request_type,
                approved_date=fully_approved_date,
            )
            pdf_url = self.uploader.upload_pdf(
                pdf_bytes=pdf_bytes,
                filename=filename,
                approved_date=fully_approved_date,
            )
            self.sp.update_item(item_id, {"ApprovalRecordURL": pdf_url})
            logger.info("Approval PDF saved to HR Records: %s", pdf_url)
        except Exception as e:
            logger.error("PDF generation/upload failed for %s: %s", item_id, e)

        # Notify roles — fan out to ALL active people for each role
        notify_messages: list = []
        for role in workflow.notify_roles:
            try:
                entries = self.roles_client.get_all_emails_for_role(role)
                if not entries:
                    # Fall back to dynamic resolution (e.g. Payroll Manager on request)
                    name, email = resolve_role(role, fields, None)
                    entries = [(name, email)]
                for name, email in entries:
                    msg = build_notify_email(
                        notify_name=name,
                        notify_email=email,
                        request_details=request_details,
                        workflow_name=workflow.request_type,
                        notify_role=role,
                    )
                    notify_messages.append(msg)
            except Exception as e:
                logger.warning("Could not build notify email for role '%s': %s", role, e)

        self.mailer.send_batch(notify_messages)

        initiator_name  = fields.get("InitiatorName", "")
        initiator_email = fields.get("InitiatorEmail", "")
        if initiator_email:
            msg = build_requester_email(
                requester_name=initiator_name,
                requester_email=initiator_email,
                request_details=request_details,
                approved=True,
                pdf_url=pdf_url,
            )
            self.mailer.send(msg)

        logger.info(
            "Request %s fully approved. PDF: %s. Notified roles: %s",
            item_id, pdf_url or "upload failed", workflow.notify_roles,
        )

    def _extract_request_details(self, fields: dict, workflow: ApprovalWorkflow) -> dict:
        return {
            "request_type":    workflow.request_type,
            "employee_name":   fields.get("EmployeeName", ""),
            "employee_number": fields.get("EmployeeNumber", ""),
            "initiator_name":  fields.get("InitiatorName", ""),
            "submitted_date":  fields.get("Created", ""),
            "effective_date":  fields.get("EffectiveDate", ""),
            "notes":           fields.get("RequestNotes", ""),
        }

    def _collect_previous_approvals(self, fields: dict, up_to_step: int) -> list[dict]:
        result = []
        for i in range(up_to_step):
            name     = fields.get(f"ApproverStep{i}Name", "")
            decision = fields.get(f"ApproverStep{i}Decision", "")
            date     = fields.get(f"ApproverStep{i}Date", "")
            comments = fields.get(f"ApproverStep{i}Comments", "")
            if name:
                result.append({
                    "name":     name,
                    "role":     f"Step {i+1}",
                    "decision": decision,
                    "date":     date,
                    "comments": comments,
                })
        return result
