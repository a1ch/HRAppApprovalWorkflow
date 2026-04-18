"""
SharePoint list configurations for all 6 HR approval lists.

Site: https://streamflogroup.sharepoint.com/hrcp/hrst

Design principle: lists only store what the USER fills in on the form.
All approval chain roles (HR Manager, 2nd Level Manager, GM/Director etc.)
are resolved at runtime from Entra ID (manager chain) or the HR Approval
Roles list. No approval chain Person picker columns needed on the lists.

This keeps each list well under SharePoint's 12 lookup column limit.

Column names verified against actual SharePoint lists via /api/debug-lists.
Last verified: 2026-04-18, all lists OK.

Status column values vary per list:
  Most lists:           Pending, In Progress, Approved, Rejected, Error
  Offer Letters:        Pending, In Progress, Approved, Declined, Error
  Payroll Change:       Pending, In Progress, Approved, Declined, Error
  Workforce Req:        Pending, Approved, Declined  (no In Progress choice)
  rejected_status_value and in_progress_status_value handle the differences.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ListConfig:
    display_name: str           # SharePoint list display name
    list_path: str              # URL path segment e.g. Lists/Leave%20of%20Absence
    workflow_keys: list[str]    # workflows from approval_matrix.py this list covers

    # ─ Employee ──────────────────────────────────────────────────
    # employee_col  = Person picker column (used to get email for Entra lookup)
    # employee_name_col = plain text display name fallback
    employee_name_col: str
    employee_col: Optional[str] = None

    # ─ Initiator ───────────────────────────────────────────────
    # Person picker column for who submitted the form (used for InitiatorEmail)
    initiator_col: str = ""
    initiator_is_person: bool = False

    # ─ Metadata ───────────────────────────────────────────────
    request_type_col: Optional[str]   = None
    effective_date_col: Optional[str] = None
    notes_col: Optional[str]          = None
    url_col: Optional[str]            = None

    # ─ Status column ──────────────────────────────────────────
    status_col: str               = "Approval Status"
    pending_status_value: str     = "Pending"
    in_progress_status_value: str = "In Progress"
    approved_status_value: str    = "Approved"
    rejected_status_value: str    = "Rejected"
    error_status_value: str       = "Error"


LIST_CONFIGS: dict[str, ListConfig] = {

    "leave_of_absence": ListConfig(
        display_name="Leave of Absence",
        list_path="Lists/Leave%20of%20Absence",
        workflow_keys=["loa_personal", "loa_fmla", "loa_military"],
        employee_name_col="Employee Name",
        employee_col="Employee Name",       # Person picker — email used for Entra lookup
        initiator_col="Requested By",
        initiator_is_person=False,          # plain text on this list
        request_type_col="Absence Type",
        effective_date_col="Start Date",
        notes_col="Notes",
        status_col="Approval Status",
    ),

    "offer_letters": ListConfig(
        display_name="Offer Letters Request Form",
        list_path="Lists/Employee%20Offer%20Letters",
        workflow_keys=[
            "offer_backfill_budgeted", "offer_backfill_unbudgeted",
            "offer_new_budgeted", "offer_new_unbudgeted",
        ],
        employee_name_col="Applicant Name",
        employee_col=None,                  # external candidate — no Entra account
        initiator_col="Hiring Supervisor",
        initiator_is_person=True,
        request_type_col="Request Type",
        effective_date_col="Start Date",
        status_col="Approval Status",
        rejected_status_value="Declined",
        url_col="EOL URL",
    ),

    "payroll_change": ListConfig(
        display_name="Payroll Change Notice",
        list_path="Lists/Payroll%20Change%20Notification",
        workflow_keys=[
            "pcn_supervisor_change", "pcn_department_change", "pcn_location_change",
            "pcn_lateral_change", "pcn_salaried_promo", "pcn_hourly_promo",
            "pcn_salaried_rate_change", "pcn_hourly_rate_change",
            "pcn_rotation_with_pay", "pcn_rotation_no_pay",
        ],
        employee_name_col="Employee Name",
        employee_col="Employee Name",       # Person picker — email used for Entra lookup
        initiator_col="Requested By",
        initiator_is_person=True,
        request_type_col="Change Type",
        effective_date_col="Effective Date Of Change",
        notes_col="Comments",
        status_col="Approval status",       # lowercase 's' — exact SP column name
        rejected_status_value="Declined",
        url_col="PCN URL",
    ),

    "termination": ListConfig(
        display_name="Termination Form",
        list_path="Lists/Termination%20Form",
        workflow_keys=[
            "pcn_termination_discharge",
            "pcn_termination_resignation",
            "pcn_termination_retirement",
        ],
        employee_name_col="Employee Name",
        employee_col="Employee Name",       # Person picker — email used for Entra lookup
        initiator_col="Current Supervisor",
        initiator_is_person=True,
        request_type_col="Termination Type",
        effective_date_col="Effective Date of Change",  # lowercase 'o'
        notes_col="Additional Notes",
        status_col="Approval Status",
        url_col="TF URL",
    ),

    "workforce_requisition": ListConfig(
        display_name="Workforce Requisition Form",
        list_path="Lists/Workforce%20Requirement%20Form",
        workflow_keys=[
            "job_req_backfill_budgeted", "job_req_backfill_unbudgeted",
            "job_req_new_budgeted", "job_req_new_unbudgeted",
            "job_req_temp_budgeted", "job_req_temp_unbudgeted",
        ],
        employee_name_col="Replaced Employee",
        employee_col=None,                  # plain text on this list
        initiator_col="Requested By",
        initiator_is_person=True,
        request_type_col="Request Type",
        effective_date_col="Requested Date",
        notes_col="Screening Criteria",
        status_col="Approval Status Value",
        rejected_status_value="Declined",
        in_progress_status_value="Pending", # no In Progress choice on this list
    ),

    "promotion": ListConfig(
        display_name="Promotion Title Change With Pay",
        list_path="Lists/Promotion%20Title%20Change%20With%20Pay",
        workflow_keys=[
            "promo_salaried", "promo_hourly",
            "promo_salaried_rate", "promo_hourly_rate",
        ],
        employee_name_col="Employee",
        employee_col="Employee",            # Person picker — email used for Entra lookup
        initiator_col="Created By",
        initiator_is_person=True,
        request_type_col="Change Type",
        status_col="Approval Status",
    ),
}


def get_list_config(list_key: str) -> Optional[ListConfig]:
    return LIST_CONFIGS.get(list_key)


def get_config_for_workflow(workflow_key: str) -> Optional[tuple[str, ListConfig]]:
    for list_key, config in LIST_CONFIGS.items():
        if workflow_key in config.workflow_keys:
            return list_key, config
    return None
