"""
HR Approval Matrix — Stream-Flo USA
Source: Approval_Matrix spreadsheet
All 24 workflows with sequential approval chains, notify lists, and email templates.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class RequestCategory(str, Enum):
    JOB_REQUISITION = "Job Requisition"
    PAYROLL_CHANGE = "Payroll Change Notice"
    LEAVE_OF_ABSENCE = "Leave of Absence"
    OFFER_LETTER = "Candidate Offer Letter"
    PROMOTION = "Promotion/Title Change with Pay"


@dataclass
class ApprovalWorkflow:
    category: RequestCategory
    request_type: str
    initiator_role: str          # role label, resolved to real person at runtime
    approval_chain: list[str]    # ordered list of approver roles
    notify_roles: list[str]      # parallel notify-only (no action required)
    requires_ceo: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# All 24 workflows from the matrix
# ---------------------------------------------------------------------------

WORKFLOWS: dict[str, ApprovalWorkflow] = {

    # ── Job Requisition ────────────────────────────────────────────────────
    "job_req_backfill_budgeted": ApprovalWorkflow(
        category=RequestCategory.JOB_REQUISITION,
        request_type="Backfill – Budgeted",
        initiator_role="Hiring Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "GM/Director"],
        notify_roles=[],
    ),
    "job_req_backfill_unbudgeted": ApprovalWorkflow(
        category=RequestCategory.JOB_REQUISITION,
        request_type="Backfill – Unbudgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=[],
        requires_ceo=True,
    ),
    "job_req_new_budgeted": ApprovalWorkflow(
        category=RequestCategory.JOB_REQUISITION,
        request_type="New Position – Budgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=[],
        requires_ceo=True,
    ),
    "job_req_new_unbudgeted": ApprovalWorkflow(
        category=RequestCategory.JOB_REQUISITION,
        request_type="New Position – Unbudgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=[],
        requires_ceo=True,
    ),
    "job_req_temp_budgeted": ApprovalWorkflow(
        category=RequestCategory.JOB_REQUISITION,
        request_type="Temp/Contract Labor Requisition – Budgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=[],
    ),
    "job_req_temp_unbudgeted": ApprovalWorkflow(
        category=RequestCategory.JOB_REQUISITION,
        request_type="Temp/Contract Labor Requisition – Unbudgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=[],
    ),

    # ── Payroll Change Notice ──────────────────────────────────────────────
    "pcn_supervisor_change": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Supervisor Change",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "Payroll Manager"],
        notify_roles=["Payroll Manager"],
    ),
    "pcn_department_change": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Department Change",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "Payroll Manager"],
        notify_roles=["Payroll Manager"],
    ),
    "pcn_location_change": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Location Change",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "GM/Director"],
        notify_roles=["Payroll Manager"],
    ),
    "pcn_lateral_change": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Lateral Position Change",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "Payroll Manager"],
        notify_roles=["HR Generalist"],
        notes="Assignment Letter to be issued",
    ),
    "pcn_salaried_promo": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Salaried Promotional Position Change – Outside Merit Cycle",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
        requires_ceo=True,
    ),
    "pcn_hourly_promo": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Hourly Promotional Position Change – Outside Merit Cycle",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "pcn_salaried_rate_change": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Salaried Rate Change – Outside Merit Cycle (no position change)",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
        requires_ceo=True,
    ),
    "pcn_hourly_rate_change": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Hourly Rate Change – Outside Merit Cycle (no position change)",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "pcn_rotation_with_pay": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Rotation or Shift Change with Pay Change",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "pcn_rotation_no_pay": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Rotation or Shift Change without Pay Change",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "Payroll Manager"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "pcn_termination_discharge": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Termination – Discharge",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "Payroll Manager"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "pcn_termination_resignation": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Termination – Resignation",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "Payroll Manager"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "pcn_termination_retirement": ApprovalWorkflow(
        category=RequestCategory.PAYROLL_CHANGE,
        request_type="Termination – Retirement",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "Payroll Manager"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),

    # ── Leave of Absence ──────────────────────────────────────────────────
    "loa_personal": ApprovalWorkflow(
        category=RequestCategory.LEAVE_OF_ABSENCE,
        request_type="Personal LOA",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "GM/Director"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "loa_fmla": ApprovalWorkflow(
        category=RequestCategory.LEAVE_OF_ABSENCE,
        request_type="LOA/FMLA",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "GM/Director"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "loa_military": ApprovalWorkflow(
        category=RequestCategory.LEAVE_OF_ABSENCE,
        request_type="Military LOA",
        initiator_role="Direct Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "GM/Director"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),

    # ── Candidate Offer Letter ─────────────────────────────────────────────
    "offer_backfill_budgeted": ApprovalWorkflow(
        category=RequestCategory.OFFER_LETTER,
        request_type="Candidate Offer Letter – Backfill Budgeted",
        initiator_role="Hiring Manager",
        approval_chain=["HR Manager", "2nd Level Manager", "GM/Director"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "offer_backfill_unbudgeted": ApprovalWorkflow(
        category=RequestCategory.OFFER_LETTER,
        request_type="Candidate Offer Letter – Backfill Unbudgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "offer_new_budgeted": ApprovalWorkflow(
        category=RequestCategory.OFFER_LETTER,
        request_type="Candidate Offer Letter – New Position Budgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),
    "offer_new_unbudgeted": ApprovalWorkflow(
        category=RequestCategory.OFFER_LETTER,
        request_type="Candidate Offer Letter – New Position Unbudgeted",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Benefits Specialist", "Payroll Manager"],
    ),

    # ── Promotion / Title Change with Pay ──────────────────────────────────
    "promo_salaried": ApprovalWorkflow(
        category=RequestCategory.PROMOTION,
        request_type="Salaried Promotional Position Change – Outside Merit Cycle",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Payroll Manager"],
        requires_ceo=True,
    ),
    "promo_hourly": ApprovalWorkflow(
        category=RequestCategory.PROMOTION,
        request_type="Hourly Promotional Position Change – Outside Merit Cycle",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Payroll Manager"],
    ),
    "promo_salaried_rate": ApprovalWorkflow(
        category=RequestCategory.PROMOTION,
        request_type="Salaried Rate Change – Outside Merit Cycle (no position change)",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Payroll Manager"],
        requires_ceo=True,
    ),
    "promo_hourly_rate": ApprovalWorkflow(
        category=RequestCategory.PROMOTION,
        request_type="Hourly Rate Change – Outside Merit Cycle (no position change)",
        initiator_role="2nd Level Manager",
        approval_chain=["HR Manager", "GM/Director", "Executive"],
        notify_roles=["Payroll Manager"],
    ),
}


def get_workflow(workflow_key: str) -> Optional[ApprovalWorkflow]:
    return WORKFLOWS.get(workflow_key)


def get_workflows_by_category(category: RequestCategory) -> dict[str, ApprovalWorkflow]:
    return {k: v for k, v in WORKFLOWS.items() if v.category == category}
