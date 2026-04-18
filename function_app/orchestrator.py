"""
Approval orchestration engine.
Handles the full lifecycle: trigger -> sequential approval chain -> notifications -> completion.
Stateless -- all state lives in SharePoint. Safe to retry.

Role resolution order:
  1. Entra manager chain  -- Direct Manager, 2nd Level Manager (walked from employee)
  2. HR Approval Roles list -- HR Manager, Payroll Manager, Benefits Specialist, HR Generalist
  3. Request form fields  -- GM/Director, Executive, CEO (still on form as fallback)
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
from hr_roles_client import HRRolesClient
from list_configs import LIST_CONFIGS, ListConfig
from mail_sender import GraphMailSender
from pdf_generator import build_pdf_filename, generate_approval_pdf
from person_field import extract_person_email, extract_person_name
from sharepoint_client import SharePointClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

ENTRA_CHAIN_ROLES: dict[str, int] = {
    "Direct Manager":    0,
    "2nd Level Manager": 1,
}

FORM_FIELD_ROLES: dict[str, tuple[str, str]] = {
    "GM/Director":    ("GMDirectorName",    "GMDirectorEmail"),
    "Executive":      ("ExecutiveName",     "ExecutiveEmail"),
    "CEO":            ("CEOName",           "CEOEmail"),
    "Hiring Manager": ("HiringManagerName", "HiringManagerEmail"),
}


def resolve_role(
    role: str,
    request_fields: dict,
    employee_email: str,
    entra: EntraClient,
    roles_client: HRRolesClient,
    config: Optional[ListConfig] = None,
) -> tuple[str, str]:
    """
    Resolve any approval role to (name, email).

    Resolution order:
      1. Entra manager chain (Direct Manager, 2nd Level Manager)
      2. Person picker column on the request form (GM/Director, Executive, CEO, Hiring Manager)
         using the column name from list_configs if available
      3. HR Roles list fallback
    """
    # 1. Entra manager chain
    if role in ENTRA_CHAIN_ROLES and employee_email:
        level = ENTRA_CHAIN_ROLES[role]
        try:
            return entra.resolve_manager_role(employee_email, level=level)
        except ValueError as e:
            logger.warning(
                "Entra chain resolution failed for '%s' (level %d, employee %s): %s — "
                "falling back to form fields / HR Roles list",
                role, level, employee_email, e,
            )

    # 2. Form Person picker columns — try config-based col name first, then generic
    from list_configs import PERSON_COL_ROLE_MAP
    if config:
        attr = PERSON_COL_ROLE_MAP.get(role)
        if attr:
            col_name = getattr(config, attr, None)
            if col_name:
                name  = extract_person_name(request_fields, col_name)
                email = extract_person_email(request_fields, col_name)
                if email:
                    return name or role, email

    # Fallback: try generic text fields (GMDirectorName/Email etc.)
    if role in FORM_FIELD_ROLES:
        name_field, email_field = FORM_FIELD_ROLES[role]
        name  = request_fields.get(name_field, "").strip()
        email = request_fields.get(email_field, "").strip()
        if not email:
            base_col = name_field.replace("Name", "")
            email = extract_person_email(request_fields, base_col)
        if not name:
            base_col = name_field.replace("Name", "")
            name = extract_person_name(request_fields, base_col)
        if email:
            return name or role, email
        logger.debug("Form field empty for role '%s', falling back to HR Roles list", role)

    # 3. HR Roles list
    return roles_client.resolve_role(role)


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
        for list_key, config in LIST_CONFIGS.items():
            try:
                pending = self.sp.get_pending_items_for_list(list_key, config)
                logger.info("List '%s': %d pending item(s)", list_key, len(pending))
                for fields in pending:
                    item_id = str(fields.get("id") or fields.get("ID", ""))
                    if not item_id:
                        logger.warning("Skipping item with no ID in list '%s'", list_key)
                        continue
                    try:
                        self.handle_new_request(
                            item_id, list_key=list_key,
                            prefetched_fields=fields, config=config,
                        )
                    except Exception as e:
                        logger.exception(
                            "Error handling item %s in list '%s': %s", item_id, list_key, e
                        )
            except Exception as e:
                logger.exception("Error polling list '%s': %s", list_key, e)

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
            logger.error("Unknown workflow key '%s' for item %s", workflow_key, item_id)
            self.sp.mark_error(
                item_id,
                f"Unknown workflow: {workflow_key}",
                list_display_name=config.display_name if config else None,
                config=config,
            )
            return

        logger.info("New request %s: %s", item_id, workflow.request_type)

        # Use per-list in_progress status value
        in_progress_val = config.in_progress_status_value if config else "In Progress"
        status_col      = config.status_col if config else "Approval Status"

        self.sp.update_item(item_id, {
            status_col:            in_progress_val,
            "CurrentApprovalStep": 0,
            "WorkflowCategory":    workflow.category.value,
        }, list_display_name=config.display_name if config else None)

        self._send_approver_email(
            item_id, fields, workflow, step=0,
            previous_approvals=[], config=config,
        )

    def handle_approval_action(
        self,
        item_id: str,
        approver_email: str,
        action: str,
        comments: str = "",
        list_key: str = "",
    ) -> dict:
        config       = LIST_CONFIGS.get(list_key) if list_key else None
        fields       = self.sp.get_item(item_id, list_display_name=config.display_name if config else None)
        workflow_key = fields.get("WorkflowKey", "")
        workflow     = get_workflow(workflow_key)

        if not workflow:
            return {"error": "Workflow not found", "request_id": item_id}

        current_step   = int(fields.get("CurrentApprovalStep", 0))
        chain          = workflow.approval_chain + (["CEO"] if workflow.requires_ceo else [])
        employee_email = self._get_employee_email(fields, config)

        expected_role = chain[current_step]
        expected_name, expected_email = resolve_role(
            expected_role, fields, employee_email, self.entra, self.roles_client, config
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

        list_display_name = config.display_name if config else None

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
                item_id, fields, workflow, expected_name, request_details,
                comments=comments, config=config,
            )
            return {"outcome": "rejected", "request_id": item_id, "rejected_by": expected_name}

        next_step = current_step + 1
        if next_step < len(chain):
            self.sp.advance_to_next_step(
                item_id, next_step,
                list_display_name=list_display_name,
                config=config,
            )
            previous_approvals = self._collect_previous_approvals(fields, current_step + 1)
            self._send_approver_email(
                item_id, fields, workflow, step=next_step,
                previous_approvals=previous_approvals, config=config,
            )
            return {"outcome": "advanced", "request_id": item_id, "next_step": next_step}
        else:
            self._handle_full_approval(item_id, fields, workflow, request_details, config)
            return {"outcome": "fully_approved", "request_id": item_id}

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_employee_email(self, fields: dict, config: Optional[ListConfig] = None) -> str:
        if config and config.employee_col:
            email = extract_person_email(fields, config.employee_col)
            if email:
                return email
        return (
            fields.get("EmployeeEmail", "")
            or fields.get("InitiatorEmail", "")
            or ""
        ).strip()

    def _send_approver_email(
        self,
        item_id: str,
        fields: dict,
        workflow: ApprovalWorkflow,
        step: int,
        previous_approvals: list[dict],
        config: Optional[ListConfig] = None,
    ) -> None:
        chain = workflow.approval_chain + (["CEO"] if workflow.requires_ceo else [])
        role  = chain[step]
        employee_email = self._get_employee_email(fields, config)
        name, email = resolve_role(
            role, fields, employee_email, self.entra, self.roles_client, config
        )
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
        config: Optional[ListConfig] = None,
    ) -> None:
        list_display_name = config.display_name if config else None
        self.sp.mark_rejected(
            item_id, rejected_by,
            list_display_name=list_display_name,
            config=config,
        )
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
        self.sp.mark_fully_approved(
            item_id,
            list_display_name=list_display_name,
            config=config,
        )
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
            logger.info("Approval PDF saved: %s", pdf_url)
        except Exception as e:
            logger.error("PDF generation/upload failed for %s: %s", item_id, e)

        # Notify roles
        notify_messages: list = []
        employee_email = self._get_employee_email(fields, config)
        for role in workflow.notify_roles:
            try:
                if role in ENTRA_CHAIN_ROLES and employee_email:
                    level = ENTRA_CHAIN_ROLES[role]
                    name, email = self.entra.resolve_manager_role(employee_email, level=level)
                    entries = [(name, email)]
                else:
                    entries = self.roles_client.get_all_emails_for_role(role)
                    if not entries:
                        name, email = resolve_role(
                            role, fields, employee_email, self.entra, self.roles_client, config
                        )
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

        employee_email = self._get_employee_email(fields, config)

        # Effective date — use config col name if available
        effective_date = ""
        if config and config.effective_date_col:
            effective_date = fields.get(config.effective_date_col, "")
        if not effective_date:
            effective_date = fields.get("EffectiveDate", "")

        # Notes — use config col name if available
        notes = ""
        if config and config.notes_col:
            notes = fields.get(config.notes_col, "")

        return {
            "request_type":    workflow.request_type,
            "employee_name":   employee_name,
            "employee_email":  employee_email,
            "employee_number": fields.get("EmployeeNumber", ""),
            "initiator_name":  fields.get("InitiatorName", ""),
            "submitted_date":  fields.get("Created", ""),
            "effective_date":  effective_date,
            "notes":           notes,
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
