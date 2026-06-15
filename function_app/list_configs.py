"""
SharePoint list configurations for all 6 HR approval lists.

Site: https://streamflogroup.sharepoint.com/hrcp/hrst

Design principle: lists only store what the USER fills in on the form.
All approval-chain approvers (HR Manager, 2nd Level Manager, GM/Director etc.)
are ENTERED ON THE FORM as plain-text "Display Name <email>" person-text
columns (e.g. HRManagerText) by the HR Service Center SPFx app, and the
function resolves them straight from those columns. (See orchestrator.py.)

  IMPORTANT: do not delete the *Text approver columns from these lists — the
  function reads them to know who approves each step.

Field-name note: Microsoft Graph returns list item `fields` keyed by each
column's INTERNAL name (spaces -> _x0020_, and truncated to 32 chars), NOT the
friendly display name. So every *_col below must be the internal name, or the
lookup silently returns "".

Status column values vary per list:
  Most lists:           Pending, In Progress, Approved, Rejected, Error
  Offer Letters:        Pending, In Progress, Approved, Declined, Error
  Payroll Change:       Pending, In Progress, Approved, Declined, Error
  Promotion:            Pending, In Progress, Approved, Declined, Error
  Workforce Req:        Pending, Approved, Declined  (no In Progress choice)
  rejected_status_value and in_progress_status_value handle the differences.

Column names verified against actual SharePoint lists via /api/debug-lists
and the SPFx schema (schema.ts) internal names.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ListConfig:
    display_name: str           # SharePoint list display name
    list_path: str              # URL path segment e.g. Lists/Leave%20of%20Absence
    workflow_keys: list[str]    # workflows from approval_matrix.py this list covers

    # - Employee -------------------------------------------------
    # employee_col  = Person picker column (used to get email for Entra lookup)
    # employee_name_col = plain text display name fallback
    employee_name_col: str
    employee_col: Optional[str] = None

    # - Initiator ------------------------------------------------
    # Person picker column for who submitted the form (used for InitiatorEmail)
    initiator_col: str = ""
    initiator_is_person: bool = False

    # - Metadata (INTERNAL field names - see module docstring) --
    request_type_col: Optional[str]   = None
    effective_date_col: Optional[str] = None
    notes_col: Optional[str]          = None
    url_col: Optional[str]            = None

    # - Status column --------------------------------------------
    status_col: str               = "Approval Status"
    status_filter_field: Optional[str] = None   # exact internal name for OData $filter (overrides space-encoding)
    pending_status_value: str     = "Pending"
    in_progress_status_value: str = "In Progress"
    approved_status_value: str    = "Approved"
    rejected_status_value: str    = "Rejected"
    error_status_value: str       = "Error"

    @property
    def status_internal(self) -> str:
        """Internal field name of the status column (for OData filter and field writes)."""
        return self.status_filter_field or self.status_col.replace(" ", "_x0020_")


LIST_CONFIGS: dict[str, ListConfig] = {

    "leave_of_absence": ListConfig(
        display_name="Leave of Absence",
        list_path="Lists/Leave%20of%20Absence",
        workflow_keys=["loa_personal", "loa_fmla", "loa_military"],
        employee_name_col="EmployeeName",
        employee_col=None,                  # employee entered as text (EmployeeNameText)
        initiator_col="Requested By",
        initiator_is_person=False,
        request_type_col="Absence_x0020_Type",
        effective_date_col="Start_x0020_Date",
        notes_col="Title",                  # LOA "Notes" is stored in the Title field
        status_col="Approval Status",
    ),

    "offer_letters": ListConfig(
        display_name="Offer Letters Request Form",
        list_path="Lists/Employee%20Offer%20Letters",
        workflow_keys=[
            "offer_backfill_budgeted", "offer_backfill_unbudgeted",
            "offer_new_budgeted", "offer_new_unbudgeted",
        ],
        employee_name_col="Applicant_x0020_Name",
        employee_col=None,                  # external candidate - no Entra account
        initiator_col="Hiring Supervisor",
        initiator_is_person=True,
        request_type_col="Request_x0020_Type",
        effective_date_col="Start_x0020_Date",
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
        employee_name_col="EmployeeName",
        employee_col=None,                  # employee entered as text (EmployeeNameText)
        initiator_col="Requested By",
        initiator_is_person=True,
        request_type_col=None,              # derived from field changes; no single column
        effective_date_col="Effective_x0020_Date_x0020_Of_x0",
        notes_col=None,
        status_col="Approval status",       # lowercase 's' - exact SP column name
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
        employee_name_col="EmployeeName",
        employee_col=None,                  # employee entered as text (EmployeeNameText)
        initiator_col="Direct Manager",
        initiator_is_person=True,
        request_type_col="Termination_x0020_Type",
        effective_date_col="Effective_x0020_Date_x0020_of_x0",  # lowercase 'o'
        notes_col="Additional_x0020_Notes",
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
        employee_name_col="ReplacedEmployee",
        employee_col=None,                  # plain text on this list
        initiator_col="Requested By",
        initiator_is_person=True,
        request_type_col="Position_x0020_Status",
        effective_date_col="Requested_x0020_Date",
        notes_col="Screening_x0020_Criteria",
        status_col="Approval Status Value",
        status_filter_field="Approval_x0020_Status_x0020_Valu",  # SP truncated internal name (32 chars)
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
        employee_name_col="EmployeeName",
        employee_col=None,                  # employee entered as text (EmployeeNameText)
        initiator_col="Requested By",
        initiator_is_person=False,
        request_type_col="Change_x0020_Type",
        effective_date_col="Effective_x0020_Date_x0020_of_x0",
        notes_col=None,
        status_col="Approval Status",
        rejected_status_value="Declined",
    ),

}


def get_list_config(list_key: str) -> Optional[ListConfig]:
    return LIST_CONFIGS.get(list_key)


def get_config_for_workflow(workflow_key: str) -> Optional[tuple[str, ListConfig]]:
    for list_key, config in LIST_CONFIGS.items():
        if workflow_key in config.workflow_keys:
            return list_key, config
    return None
