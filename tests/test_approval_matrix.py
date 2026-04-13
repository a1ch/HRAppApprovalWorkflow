"""
Unit tests for approval_matrix.py.

Tests all 24 workflow definitions, get_workflow(), get_workflows_by_category(),
and structural rules from the approval matrix spreadsheet.

Run: pytest tests/test_approval_matrix.py -v
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

from approval_matrix import (
    WORKFLOWS,
    ApprovalWorkflow,
    RequestCategory,
    get_workflow,
    get_workflows_by_category,
)

# ---------------------------------------------------------------------------
# All expected workflow keys
# ---------------------------------------------------------------------------

ALL_WORKFLOW_KEYS = [
    # Job Requisition
    "job_req_backfill_budgeted",
    "job_req_backfill_unbudgeted",
    "job_req_new_budgeted",
    "job_req_new_unbudgeted",
    "job_req_temp_budgeted",
    "job_req_temp_unbudgeted",
    # Payroll Change Notice
    "pcn_supervisor_change",
    "pcn_department_change",
    "pcn_location_change",
    "pcn_lateral_change",
    "pcn_salaried_promo",
    "pcn_hourly_promo",
    "pcn_salaried_rate_change",
    "pcn_hourly_rate_change",
    "pcn_rotation_with_pay",
    "pcn_rotation_no_pay",
    "pcn_termination_discharge",
    "pcn_termination_resignation",
    "pcn_termination_retirement",
    # Leave of Absence
    "loa_personal",
    "loa_fmla",
    "loa_military",
    # Candidate Offer Letter
    "offer_backfill_budgeted",
    "offer_backfill_unbudgeted",
    "offer_new_budgeted",
    "offer_new_unbudgeted",
    # Promotion / Title Change with Pay
    "promo_salaried",
    "promo_hourly",
    "promo_salaried_rate",
    "promo_hourly_rate",
]

# ===========================================================================
# WORKFLOWS dict — completeness
# ===========================================================================

class TestWorkflowsCompleteness:

    def test_all_expected_keys_present(self):
        missing = [k for k in ALL_WORKFLOW_KEYS if k not in WORKFLOWS]
        assert missing == [], f"Missing workflow keys: {missing}"

    def test_no_unexpected_keys(self):
        extra = [k for k in WORKFLOWS if k not in ALL_WORKFLOW_KEYS]
        assert extra == [], f"Unexpected workflow keys not in test list: {extra}"

    def test_total_workflow_count(self):
        assert len(WORKFLOWS) == len(ALL_WORKFLOW_KEYS)

    def test_all_values_are_approval_workflow_instances(self):
        for key, wf in WORKFLOWS.items():
            assert isinstance(wf, ApprovalWorkflow), f"{key} is not an ApprovalWorkflow"


# ===========================================================================
# Every workflow — structural validity
# ===========================================================================

class TestEveryWorkflowIsValid:

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_has_non_empty_request_type(self, key):
        assert WORKFLOWS[key].request_type.strip(), f"{key} has empty request_type"

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_has_non_empty_initiator_role(self, key):
        assert WORKFLOWS[key].initiator_role.strip(), f"{key} has empty initiator_role"

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_approval_chain_not_empty(self, key):
        assert len(WORKFLOWS[key].approval_chain) >= 1, f"{key} has empty approval_chain"

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_approval_chain_has_no_blank_roles(self, key):
        for role in WORKFLOWS[key].approval_chain:
            assert role.strip(), f"{key} has a blank role in approval_chain"

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_notify_roles_is_list(self, key):
        assert isinstance(WORKFLOWS[key].notify_roles, list), \
            f"{key} notify_roles is not a list"

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_requires_ceo_is_bool(self, key):
        assert isinstance(WORKFLOWS[key].requires_ceo, bool), \
            f"{key} requires_ceo is not a bool"

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_category_is_valid_enum(self, key):
        assert isinstance(WORKFLOWS[key].category, RequestCategory), \
            f"{key} category is not a RequestCategory enum"


# ===========================================================================
# get_workflow()
# ===========================================================================

class TestGetWorkflow:

    def test_returns_workflow_for_valid_key(self):
        wf = get_workflow("job_req_backfill_budgeted")
        assert isinstance(wf, ApprovalWorkflow)

    def test_returns_none_for_unknown_key(self):
        assert get_workflow("totally_fake_key") is None

    def test_returns_none_for_empty_string(self):
        assert get_workflow("") is None

    def test_returns_none_for_similar_but_wrong_key(self):
        assert get_workflow("job_req_backfill") is None

    def test_returns_correct_workflow(self):
        wf = get_workflow("pcn_termination_discharge")
        assert wf.request_type == "Termination – Discharge"

    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_all_keys_resolve(self, key):
        assert get_workflow(key) is not None, f"get_workflow('{key}') returned None"


# ===========================================================================
# get_workflows_by_category()
# ===========================================================================

class TestGetWorkflowsByCategory:

    def test_job_requisition_returns_correct_count(self):
        results = get_workflows_by_category(RequestCategory.JOB_REQUISITION)
        assert len(results) == 6

    def test_payroll_change_returns_correct_count(self):
        results = get_workflows_by_category(RequestCategory.PAYROLL_CHANGE)
        assert len(results) == 13

    def test_leave_of_absence_returns_correct_count(self):
        results = get_workflows_by_category(RequestCategory.LEAVE_OF_ABSENCE)
        assert len(results) == 3

    def test_offer_letter_returns_correct_count(self):
        results = get_workflows_by_category(RequestCategory.OFFER_LETTER)
        assert len(results) == 4

    def test_promotion_returns_correct_count(self):
        results = get_workflows_by_category(RequestCategory.PROMOTION)
        assert len(results) == 4

    def test_all_results_match_category(self):
        for cat in RequestCategory:
            results = get_workflows_by_category(cat)
            for key, wf in results.items():
                assert wf.category == cat, \
                    f"{key} returned in {cat} but has category {wf.category}"

    def test_all_categories_covered(self):
        total = sum(
            len(get_workflows_by_category(cat)) for cat in RequestCategory
        )
        assert total == len(WORKFLOWS)

    def test_returns_dict(self):
        result = get_workflows_by_category(RequestCategory.JOB_REQUISITION)
        assert isinstance(result, dict)

    def test_dict_values_are_approval_workflows(self):
        for wf in get_workflows_by_category(RequestCategory.LEAVE_OF_ABSENCE).values():
            assert isinstance(wf, ApprovalWorkflow)


# ===========================================================================
# Business rules from the approval matrix
# ===========================================================================

class TestApprovalMatrixRules:

    # Unbudgeted / new positions require CEO sign-off
    def test_job_req_backfill_unbudgeted_requires_ceo(self):
        assert WORKFLOWS["job_req_backfill_unbudgeted"].requires_ceo is True

    def test_job_req_new_budgeted_requires_ceo(self):
        assert WORKFLOWS["job_req_new_budgeted"].requires_ceo is True

    def test_job_req_new_unbudgeted_requires_ceo(self):
        assert WORKFLOWS["job_req_new_unbudgeted"].requires_ceo is True

    def test_pcn_salaried_promo_requires_ceo(self):
        assert WORKFLOWS["pcn_salaried_promo"].requires_ceo is True

    def test_pcn_salaried_rate_change_requires_ceo(self):
        assert WORKFLOWS["pcn_salaried_rate_change"].requires_ceo is True

    def test_promo_salaried_requires_ceo(self):
        assert WORKFLOWS["promo_salaried"].requires_ceo is True

    def test_promo_salaried_rate_requires_ceo(self):
        assert WORKFLOWS["promo_salaried_rate"].requires_ceo is True

    # Budgeted backfill and hourly changes do NOT require CEO
    def test_job_req_backfill_budgeted_no_ceo(self):
        assert WORKFLOWS["job_req_backfill_budgeted"].requires_ceo is False

    def test_pcn_hourly_promo_no_ceo(self):
        assert WORKFLOWS["pcn_hourly_promo"].requires_ceo is False

    def test_promo_hourly_no_ceo(self):
        assert WORKFLOWS["promo_hourly"].requires_ceo is False

    # Terminations notify Benefits and Payroll
    def test_termination_discharge_notifies_benefits(self):
        assert "Benefits Specialist" in WORKFLOWS["pcn_termination_discharge"].notify_roles

    def test_termination_discharge_notifies_payroll(self):
        assert "Payroll Manager" in WORKFLOWS["pcn_termination_discharge"].notify_roles

    def test_termination_resignation_notifies_benefits(self):
        assert "Benefits Specialist" in WORKFLOWS["pcn_termination_resignation"].notify_roles

    def test_termination_retirement_notifies_payroll(self):
        assert "Payroll Manager" in WORKFLOWS["pcn_termination_retirement"].notify_roles

    # Leave of Absence notifies Benefits and Payroll
    def test_loa_fmla_notifies_benefits(self):
        assert "Benefits Specialist" in WORKFLOWS["loa_fmla"].notify_roles

    def test_loa_military_notifies_payroll(self):
        assert "Payroll Manager" in WORKFLOWS["loa_military"].notify_roles

    # Lateral change gets HR Generalist, not Benefits
    def test_lateral_change_notifies_hr_generalist(self):
        assert "HR Generalist" in WORKFLOWS["pcn_lateral_change"].notify_roles

    # Job requisitions have no notify roles (HR handles internally)
    def test_job_req_backfill_budgeted_no_notify(self):
        assert WORKFLOWS["job_req_backfill_budgeted"].notify_roles == []

    def test_job_req_temp_budgeted_no_notify(self):
        assert WORKFLOWS["job_req_temp_budgeted"].notify_roles == []

    # HR Manager is always first in the approval chain
    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_hr_manager_is_first_approver(self, key):
        chain = WORKFLOWS[key].approval_chain
        assert chain[0] == "HR Manager", \
            f"{key} has '{chain[0]}' as first approver, expected 'HR Manager'"

    # All chains have at least 2 approvers
    @pytest.mark.parametrize("key", ALL_WORKFLOW_KEYS)
    def test_chain_has_at_least_two_approvers(self, key):
        assert len(WORKFLOWS[key].approval_chain) >= 2, \
            f"{key} has fewer than 2 approvers in chain"

    # Offer letters notify Benefits and Payroll
    def test_offer_backfill_budgeted_notifies_benefits(self):
        assert "Benefits Specialist" in WORKFLOWS["offer_backfill_budgeted"].notify_roles

    def test_offer_new_budgeted_notifies_payroll(self):
        assert "Payroll Manager" in WORKFLOWS["offer_new_budgeted"].notify_roles
