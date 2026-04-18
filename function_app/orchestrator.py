"""
Approval orchestration engine.

Role resolution — two sources only:

  1. Entra manager chain (Direct Manager, 2nd Level Manager)
     Walked automatically from the employee's Entra profile.
     No columns needed on the request form.

  2. HR Approval Roles list (everything else)
     HR Manager, Payroll Manager, Benefits Specialist, HR Generalist,
     GM/Director, Executive, CEO, Hiring Manager.
     HR maintains this list — no code change needed when people change.

All approval chain Person picker columns have been removed from the
SharePoint lists. The lists now only store what the user fills in.
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
from entra_client import EntraClient
from hr_records_uploader import HRRecordsUploader
from hr_roles_client import HRRolesClient, VALID_ROLES
from list_configs import LIST_CONFIGS, ListConfig
from mail_sender import GraphMailSender
from pdf_generator import build_pdf_filename, generate_approval_pdf
from person_field import extract_person_email, extract_person_name
from sharepoint_client import SharePointClient

logger = logging.getLogger(__name__)

# Roles resolved by walking the Entra manager chain from the employee.
# level 0 = direct manager, level 1 = manager's manager.
ENTRA_CHAIN_ROLES: dict[str, int] = {
    "Direct Manager":    0,
    "2nd Level Manager": 1,
}


def resolve_role(
    role: str,
    employee_email: str,
    entra: EntraClient,
    roles_client: HRRolesClient,
) -> tuple[str, str]:
    """
    Resolve any approval role to (name, email).

    1. Direct Manager / 2nd Level Manager  →  Entra manager chain
    2. Everything else                      →  HR Approval Roles list
    """
    # 1. Entra manager chain
    if role in ENTRA_CHAIN_ROLES:
        level = ENTRA_CHAIN_ROLES[role]
        if not employee_email:
            raise ValueError(
                f"Cannot resolve '{role}' from Entra — no employee email on the request."
            )
        try:
            return entra.resolve_manager_role(employee_email, level=level)
        except ValueError as e:
            raise ValueError(
                f"Entra manager chain lookup failed for '{role}' "
                f"(employee {employee_email}, level {level}): {e}"
            ) from e

    # 2. HR Approval Roles list
    if role in VALID_ROLES:
        return roles_client.resolve_role(role)

    raise ValueError(
        f"Unknown role '{role}' — not in Entra chain roles or VALID_ROLES. "
        f"Check approval_matrix.py."
    )


class ApprovalOrchestrator:
    def __init__(self):
        self.sp           = SharePointClient()
        self.mailer       = GraphMailSender()
        self.uploader     = HRRecordsUploader()
        self.entra        = EntraClient()
        self.roles_client = HRRolesClient(self.sp)
        self.base_url     = os.environ.get("APPROVAL_BASE_URL", "").rstrip("/")

    # ── Entry points ──────────────────────────────────────────────────────

    def poll_all_lists(self) -> None:
        """Timer entry point — polls all 6 lists for Pending items."""
        for list_key, config in LIST_CONFIGS.items():
            try:
                pending = self.sp.get_pending_items_for_list(list_key, config)
                logger.info("List '%s': %d pending", list_key, len(pending))
                for fields in pending:
                    item_id = str(fields.get("id") or fields.get("ID", ""))
                    if not item_id:
                        logger.warning("Skipping item with no ID in '%s'", list_key)
                        continue
                    try:
                        self.handle_new_request(
                            item_id, list_key=list_key,
                            prefetched_fields=fields, config=config,
                        )
                    except Exception as e:
                        logger.exception("Error on item %s in '%s': %s", item_id, list_key, e)
            except Exception as e:
                logger.exception("Error polling '%s': %s", list_key, e)

    def handle_new_request(
        self,
        item_id: str,
        list_key: str = "",
        prefetched_fields: Optional[dict] = None,
        config: Optional[ListConfig] = None,
    ) -> None:
        fields       = prefetched_fields or self.sp.get_item(item_id)
        workflow_key = fields.get("WorkflowKey", "")
        workflow     = get_workflow(workflow_key)

        if not workflow:
            logger.error("Unknown WorkflowKey '%s' on item %s", workflow_key, item_id)
            self.sp.mark_error(
                item_id,
                f"Unknown workflow: {workflow_key}",
                list_display_name=config.display_name if config else None,
                config=config,
            )
            return

        logger.info("New request %s — %s", item_id, workflow.request_type)
        in_progress = config.in_progress_status_value if config else "In Progress"
        status_col  = config.status_col if config else "Approval Status"

        self.sp.update_item(
            item_id,
            {
                status_col:            in_progress,
                "CurrentApprovalStep": 0,
                "WorkflowCategory":    workflow.category.value,
            },
            list_display_name=config.display_name if config else None,
        )
        self._send_step_email(item_id, fields, workflow, step=0, previous=[], config=config)

    def handle_approval_action(
        self,
        item_id: str,
        approver_email: str,
        action: str,            # "approve" | "reject"
        comments: str = "",
        list_key: str = "",
    ) -> dict:
        config            = LIST_CONFIGS.get(list_key) if list_key else None
        list_display_name = config.display_name if config else None
        fields            = self.sp.get_item(item_id, list_display_name=list_display_name)
        workflow_key      = fields.get("WorkflowKey", "")
        workflow          = get_workflow(workflow_key)

        if not workflow:
            return {"error": "Workflow not found", "request_id": item_id}

        current_step   = int(fields.get("CurrentApprovalStep", 0))
        chain          = workflow.approval_chain + (["CEO"] if workflow.requires_ceo else [])
        employee_email = self._get_employee_email(fields, config)

        # Resolve who SHOULD be approving this step
        try:
            expected_name, expected_email = resolve_role(
                chain[current_step], employee_email, self.entra, self.roles_client
            )
        except ValueError as e:
            logger.error("Role resolution failed for step %d: %s", current_step, e)
            return {"error": str(e), "request_id": item_id}

        if approver_email.lower() != expected_email.lower():
            logger.warning(
                "Wrong approver %s for step %d (expected %s)",
                approver_email, current_step, expected_email,
            )
            return {"error": "Not the expected approver for this step", "request_id": item_id}

        existing = fields.get(f"ApproverStep{current_step}Decision", "")
        if existing:
            return {"message": f"Step {current_step} already {existing}", "request_id": item_id}

        self.sp.record_approval_decision(
            item_id=item_id,
            step=current_step,
            approver_name=expected_name,
            approver_email=approver_email,
            decision=action,
            comments=comments,
            list_display_name=list_display_name,
            config=config,
        )

        request_details = self._extract_request_details(fields, workflow, config)

        if action == "reject":
            self._handle_rejection(
                item_id, fields, workflow, expected_name,
                request_details, comments=comments, config=config,
            )
            return {"outcome": "rejected", "request_id": item_id, "rejected_by": expected_name}

        next_step = current_step + 1
        if next_step < len(chain):
            self.sp.advance_to_next_step(
                item_id, next_step,
                list_display_name=list_display_name,
                config=config,
            )
            previous = self._collect_previous_approvals(fields, current_step + 1)
            self._send_step_email(
                item_id, fields, workflow,
                step=next_step, previous=previous, config=config,
            )
            return {"outcome": "advanced", "request_id": item_id, "next_step": next_step}

        self._handle_full_approval(item_id, fields, workflow, request_details, config)
        return {"outcome": "fully_approved", "request_id": item_id}

    # ── Helpers ──────────────────────────────────────────────────────────

    def _get_employee_email(self, fields: dict, config: Optional[ListConfig] = None) -> str:
        """Extract employee email from the request. Used as starting point for Entra chain."""
        if config and config.employee_col:
            email = extract_person_email(fields, config.employee_col)
            if email:
                return email
        return (
            fields.get("EmployeeEmail", "")
            or fields.get("InitiatorEmail", "")
            or ""
        ).strip()

    def _send_step_email(
        self,
        item_id: str,
        fields: dict,
        workflow: ApprovalWorkflow,
        step: int,
        previous: list[dict],
        config: Optional[ListConfig] = None,
    ) -> None:
        chain          = workflow.approval_chain + (["CEO"] if workflow.requires_ceo else [])
        role           = chain[step]
        employee_email = self._get_employee_email(fields, config)

        try:
            name, email = resolve_role(role, employee_email, self.entra, self.roles_client)
        except ValueError as e:
            logger.error("Cannot send step %d email — role resolution failed: %s", step, e)
            return

        request_details = self._extract_request_details(fields, workflow, config)
        msg = build_approver_email(
            base_url=self.base_url,
            request_id=item_id,
            approver_name=name,
            approver_email=email,
            request_details=request_details,
            workflow_name=workflow.request_type,
            approval_chain=chain,
            current_step=step,
            previous_approvals=previous,
        )
        self.mailer.send(msg)
        logger.info("Sent step %d email to %s (%s)", step, name, email)

    def _handle_rejection(
        self,
        item_id: str,
        fields: dict,
        workflow: ApprovalWorkflow,
        rejected_by: str,
        request_details: dict,
        comments: str = "",
        config: Optional[ListConfig] = None,
    ) -> None:
        self.sp.mark_rejected(
            item_id, rejected_by,
            list_display_name=config.display_name if config else None,
            config=config,
        )
        initiator_email = fields.get("InitiatorEmail", "")
        if initiator_email:
            self.mailer.send(build_requester_email(
                requester_name=fields.get("InitiatorName", ""),
                requester_email=initiator_email,
                request_details=request_details,
                approved=False,
                rejected_by=rejected_by,
                rejection_comments=comments,
            ))
        logger.info("Request %s rejected by %s", item_id, rejected_by)

    def _handle_full_approval(
        self,
        item_id: str,
        fields: dict,
        workflow: ApprovalWorkflow,
        request_details: dict,
        config: Optional[ListConfig] = None,
    ) -> None:
        list_display_name = config.display_name if config else None
        self.sp.mark_fully_approved(item_id, list_display_name=list_display_name, config=config)
        updated             = self.sp.get_item(item_id, list_display_name=list_display_name)
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
            self.sp.update_item(item_id, {"ApprovalRecordURL": pdf_url}, list_display_name)
            logger.info("PDF saved: %s", pdf_url)
        except Exception as e:
            logger.error("PDF generation/upload failed for %s: %s", item_id, e)

        # Fan-out notify emails
        employee_email  = self._get_employee_email(fields, config)
        notify_messages = []
        for role in workflow.notify_roles:
            try:
                if role in ENTRA_CHAIN_ROLES:
                    name, email = self.entra.resolve_manager_role(
                        employee_email, level=ENTRA_CHAIN_ROLES[role]
                    )
                    entries = [(name, email)]
                else:
                    entries = self.roles_client.get_all_emails_for_role(role)
                    if not entries:
                        name, email = resolve_role(role, employee_email, self.entra, self.roles_client)
                        entries = [(name, email)]
                for name, email in entries:
                    notify_messages.append(build_notify_email(
                        notify_name=name,
                        notify_email=email,
                        request_details=request_details,
                        workflow_name=workflow.request_type,
                        notify_role=role,
                    ))
            except Exception as e:
                logger.warning("Notify email failed for role '%s': %s", role, e)

        self.mailer.send_batch(notify_messages)

        initiator_email = fields.get("InitiatorEmail", "")
        if initiator_email:
            self.mailer.send(build_requester_email(
                requester_name=fields.get("InitiatorName", ""),
                requester_email=initiator_email,
                request_details=request_details,
                approved=True,
                pdf_url=pdf_url,
            ))

        logger.info(
            "Request %s fully approved. PDF: %s. Notified: %s",
            item_id, pdf_url or "upload failed", workflow.notify_roles,
        )

    def _extract_request_details(
        self,
        fields: dict,
        workflow: ApprovalWorkflow,
        config: Optional[ListConfig] = None,
    ) -> dict:
        employee_name = ""
        if config and config.employee_col:
            employee_name = extract_person_name(fields, config.employee_col)
        if not employee_name and config:
            employee_name = fields.get(config.employee_name_col, "")
        if not employee_name:
            employee_name = fields.get("EmployeeName", "")

        effective_date = ""
        if config and config.effective_date_col:
            effective_date = fields.get(config.effective_date_col, "")

        notes = ""
        if config and config.notes_col:
            notes = fields.get(config.notes_col, "")

        return {
            "request_type":    workflow.request_type,
            "employee_name":   employee_name,
            "employee_email":  self._get_employee_email(fields, config),
            "employee_number": fields.get("EmployeeNumber", ""),
            "initiator_name":  fields.get("InitiatorName", ""),
            "submitted_date":  fields.get("Created", ""),
            "effective_date":  effective_date,
            "notes":           notes,
        }

    def _collect_previous_approvals(self, fields: dict, up_to_step: int) -> list[dict]:
        result = []
        for i in range(up_to_step):
            name = fields.get(f"ApproverStep{i}Name", "")
            if name:
                result.append({
                    "name":     name,
                    "role":     f"Step {i+1}",
                    "decision": fields.get(f"ApproverStep{i}Decision", ""),
                    "date":     fields.get(f"ApproverStep{i}Date", ""),
                    "comments": fields.get(f"ApproverStep{i}Comments", ""),
                })
        return result
