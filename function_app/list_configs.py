"""
SharePoint list configurations for all 6 HR approval lists.
Maps exact SharePoint column names to the approval chain roles.

Site: https://streamflogroup.sharepoint.com/hrcp/hrst
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ListConfig:
    display_name: str           # SharePoint list display name
    list_path: str              # URL path segment e.g. Lists/Leave%20of%20Absence
    workflow_keys: list[str]    # which workflows from approval_matrix.py this list covers

    # Column name mappings — exact internal SharePoint names
    employee_name_col: str      # Person or text col for employee
    initiator_col: str          # who submitted the request
    initiator_is_person: bool   # True = Person col, False = text col

    # Approval chain person columns — None if not on this list
    direct_manager_col: Optional[str]       = None
    second_level_manager_col: Optional[str] = None
    hr_manager_col: Optional[str]           = None
    gm_director_col: Optional[str]          = None
    executive_col: Optional[str]            = None
    ceo_col: Optional[str]                  = None
    hiring_manager_col: Optional[str]       = None
    payroll_manager_col: Optional[str]      = None
    benefits_specialist_col: Optional[str]  = None

    # Notify-only columns
    notify_cols: dict[str, str]             = field(default_factory=dict)

    # Key metadata columns for PDF / email
    request_type_col: Optional[str]        = None
    effective_date_col: Optional[str]       = None
    notes_col: Optional[str]               = None
    status_col: str                         = "Approval Status"
    url_col: Optional[str]                  = None


LIST_CONFIGS: dict[str, ListConfig] = {

    "leave_of_absence": ListConfig(
        display_name="Leave of Absence",
        list_path="Lists/Leave%20of%20Absence",
        workflow_keys=["loa_personal","loa_fmla","loa_military"],
        employee_name_col="Employee Name",
        initiator_col="Requested By",
        initiator_is_person=False,
        direct_manager_col="Direct Manager",
        second_level_manager_col="2nd Level Manager",
        hr_manager_col="HR Manager",
        gm_director_col="GM Director",
        payroll_manager_col="Payroll Manager",
        benefits_specialist_col="Benefits Specialist",
        notify_cols={"Benefits Specialist":"Benefits Specialist","Payroll Manager":"Payroll Manager"},
        request_type_col="Absence Type",
        effective_date_col="Start Date",
        notes_col="Notes",
        status_col="Approval Status",
    ),

    "offer_letters": ListConfig(
        display_name="Offer Letters Request Form",
        list_path="Lists/Employee%20Offer%20Letters",
        workflow_keys=["offer_backfill_budgeted","offer_backfill_unbudgeted","offer_new_budgeted","offer_new_unbudgeted"],
        employee_name_col="Applicant Name",
        initiator_col="Hiring Supervisor",
        initiator_is_person=True,
        hiring_manager_col="Hiring Supervisor",
        second_level_manager_col="Manager's Manager",
        hr_manager_col="HR Manager",
        gm_director_col="GM Director",
        executive_col=None,
        notify_cols={"Benefits Specialist":None,"Payroll Manager":None},
        request_type_col="Request Type",
        effective_date_col="Start Date",
        notes_col=None,
        status_col="Approval Status",
        url_col="EOL URL",
    ),

    "payroll_change": ListConfig(
        display_name="Payroll Change Notice",
        list_path="Lists/Payroll%20Change%20Notification",
        workflow_keys=["pcn_supervisor_change","pcn_department_change","pcn_location_change","pcn_lateral_change","pcn_salaried_promo","pcn_hourly_promo","pcn_salaried_rate_change","pcn_hourly_rate_change","pcn_rotation_with_pay","pcn_rotation_no_pay"],
        employee_name_col="Employee Name",
        initiator_col="Requested By",
        initiator_is_person=True,
        direct_manager_col="Current Supervisor",
        second_level_manager_col=None,
        hr_manager_col=None,
        payroll_manager_col=None,
        notify_cols={"Payroll Manager":None,"Benefits Specialist":None,"HR Generalist":None},
        request_type_col="Change Type",
        effective_date_col="Effective Date Of Change",
        notes_col="Comments",
        status_col="Approval status",
        url_col="PCN URL",
    ),

    "termination": ListConfig(
        display_name="Termination Form",
        list_path="Lists/Termination%20Form",
        workflow_keys=["pcn_termination_discharge","pcn_termination_resignation","pcn_termination_retirement"],
        employee_name_col="Employee Name",
        initiator_col="Current Supervisor",
        initiator_is_person=True,
        direct_manager_col="Current Supervisor",
        second_level_manager_col=None,
        hr_manager_col=None,
        payroll_manager_col=None,
        notify_cols={"Benefits Specialist":None,"Payroll Manager":None},
        request_type_col="Termination Type",
        effective_date_col="Effective Date of Change",
        notes_col="Additional Notes",
        status_col="Approval Status",
        url_col="TF URL",
    ),

    "workforce_requisition": ListConfig(
        display_name="Workforce Requisition Form",
        list_path="Lists/Workforce%20Requirement%20Form",
        workflow_keys=["job_req_backfill_budgeted","job_req_backfill_unbudgeted","job_req_new_budgeted","job_req_new_unbudgeted","job_req_temp_budgeted","job_req_temp_unbudgeted"],
        employee_name_col="Replaced Employee",
        initiator_col="Requested By",
        initiator_is_person=True,
        hiring_manager_col="Hiring Supervisor",
        second_level_manager_col="Manager's Manager",
        hr_manager_col="HR Manager",
        gm_director_col="GM Director",
        executive_col="Executive",
        ceo_col="CEO",
        notify_cols={},
        request_type_col="Request Type",
        effective_date_col="Requested Date",
        notes_col="Screening Criteria",
        status_col="Approval Status Value",
    ),

    "promotion": ListConfig(
        display_name="Promotion Title Change With Pay",
        list_path="Lists/Promotion%20Title%20Change%20With%20Pay",
        workflow_keys=["promo_salaried","promo_hourly","promo_salaried_rate","promo_hourly_rate"],
        employee_name_col="Employee",
        initiator_col="Created By",
        initiator_is_person=True,
        hr_manager_col="HR Manager",
        gm_director_col="GM Director",
        executive_col="Executive",
        notify_cols={"Payroll Manager":None},
        request_type_col="Change Type",
        effective_date_col=None,
        notes_col=None,
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


PERSON_COL_ROLE_MAP = {
    "Direct Manager":     "direct_manager_col",
    "2nd Level Manager":  "second_level_manager_col",
    "Hiring Manager":     "hiring_manager_col",
    "HR Manager":         "hr_manager_col",
    "GM/Director":        "gm_director_col",
    "Executive":          "executive_col",
    "CEO":                "ceo_col",
    "Payroll Manager":    "payroll_manager_col",
    "Benefits Specialist":"benefits_specialist_col",
}
