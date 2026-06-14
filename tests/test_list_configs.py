"""
Tests for list_configs.py against the CURRENT form-driven model.

The approval engine no longer uses Entra/HR-Roles resolution or per-role Person
columns, so PERSON_COL_ROLE_MAP is gone. Approvers come from the request form's
*Text columns (see test_role_resolution.py). The Promotion list was removed from
LIST_CONFIGS (no SPFx form submits to it), so the poller covers 5 lists.

Key regression coverage:
- status_internal returns the real SharePoint INTERNAL field name (not the
  display name) — this is what every status WRITE and the poll $filter use.
  A display-name key ("Approval Status") 400s on Graph; the internal name
  ("Approval_x0020_Status", or the truncated Workforce one) is required.

Run: pytest tests/test_list_configs.py -v
"""

import sys
import os
import types
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../function_app"))

for _mod in ("msal", "requests", "azure", "azure.functions"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
_req_exc = types.ModuleType("requests.exceptions")
_req_exc.HTTPError = type("HTTPError", (Exception,), {})
sys.modules["requests.exceptions"] = _req_exc

import pytest
from approval_matrix import WORKFLOWS, RequestCategory
from list_configs import LIST_CONFIGS, get_config_for_workflow, get_list_config


EXPECTED_LISTS = {
    "leave_of_absence", "offer_letters", "payroll_change",
    "termination", "workforce_requisition",
}

# Workflows intentionally NOT covered by any list (no SPFx form / removed from poller)
PROMO_KEYS = {k for k, v in WORKFLOWS.items() if v.category == RequestCategory.PROMOTION}


def all_covered_keys():
    covered = set()
    for config in LIST_CONFIGS.values():
        covered.update(config.workflow_keys)
    return covered


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class TestListConfigStructure:

    def test_exactly_five_lists(self):
        assert set(LIST_CONFIGS.keys()) == EXPECTED_LISTS

    def test_promotion_not_in_configs(self):
        assert "promotion" not in LIST_CONFIGS

    def test_required_fields_present(self):
        for key, c in LIST_CONFIGS.items():
            assert c.display_name, f"{key}: missing display_name"
            assert c.list_path.startswith("Lists/"), f"{key}: bad list_path"
            assert " " not in c.list_path, f"{key}: list_path must be URL-encoded"
            assert c.employee_name_col, f"{key}: missing employee_name_col"
            assert c.status_col, f"{key}: missing status_col"
            assert c.workflow_keys, f"{key}: no workflow keys"


# ---------------------------------------------------------------------------
# status_internal — the field name used for writes and the poll $filter
# (regression for the "Approval Status" display-name 400 bug)
# ---------------------------------------------------------------------------

class TestStatusInternal:

    EXPECTED = {
        "leave_of_absence":      "Approval_x0020_Status",
        "offer_letters":         "Approval_x0020_Status",
        "payroll_change":        "Approval_x0020_status",        # lowercase 's'
        "termination":           "Approval_x0020_Status",
        "workforce_requisition": "Approval_x0020_Status_x0020_Valu",  # SP-truncated to 32 chars
    }

    def test_status_internal_matches_expected(self):
        for key, expected in self.EXPECTED.items():
            assert LIST_CONFIGS[key].status_internal == expected, \
                f"{key}: status_internal={LIST_CONFIGS[key].status_internal!r}, expected {expected!r}"

    def test_status_internal_never_contains_spaces(self):
        # A space in the field key is exactly what made Graph PATCH/$filter 400.
        for key, c in LIST_CONFIGS.items():
            assert " " not in c.status_internal, f"{key}: status_internal has a space"

    def test_workforce_uses_explicit_filter_field(self):
        # Naive space-encoding would give ...Value (wrong); SP truncated to ...Valu.
        wf = LIST_CONFIGS["workforce_requisition"]
        assert wf.status_filter_field == "Approval_x0020_Status_x0020_Valu"
        assert wf.status_internal == wf.status_filter_field


# ---------------------------------------------------------------------------
# Workflow coverage
# ---------------------------------------------------------------------------

class TestWorkflowCoverage:

    def test_all_non_promo_workflows_covered(self):
        non_promo = set(WORKFLOWS.keys()) - PROMO_KEYS
        missing = non_promo - all_covered_keys()
        assert missing == set(), f"Uncovered workflows: {missing}"

    def test_promo_workflows_not_covered(self):
        # Promotion has no form/list; these must NOT be polled.
        assert all_covered_keys().isdisjoint(PROMO_KEYS)

    def test_no_phantom_workflow_keys(self):
        extra = all_covered_keys() - set(WORKFLOWS.keys())
        assert extra == set(), f"Configs reference non-existent workflows: {extra}"

    def test_no_key_in_two_lists(self):
        seen = {}
        for list_key, c in LIST_CONFIGS.items():
            for wf in c.workflow_keys:
                assert wf not in seen, f"'{wf}' in both {seen.get(wf)} and {list_key}"
                seen[wf] = list_key


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestRouting:

    @pytest.mark.parametrize("wf_key,list_key", [
        ("job_req_backfill_budgeted", "workforce_requisition"),
        ("loa_fmla",                  "leave_of_absence"),
        ("offer_new_budgeted",        "offer_letters"),
        ("pcn_supervisor_change",     "payroll_change"),
        ("pcn_termination_discharge", "termination"),
    ])
    def test_routes_to_expected_list(self, wf_key, list_key):
        result = get_config_for_workflow(wf_key)
        assert result is not None
        assert result[0] == list_key

    def test_promo_routes_to_nothing(self):
        for k in PROMO_KEYS:
            assert get_config_for_workflow(k) is None

    def test_unknown_returns_none(self):
        assert get_config_for_workflow("made_up_key") is None
        assert get_list_config("made_up_list") is None

    def test_pcn_split_across_two_lists(self):
        pcn = [k for k, v in WORKFLOWS.items() if v.category == RequestCategory.PAYROLL_CHANGE]
        lists = {get_config_for_workflow(k)[0] for k in pcn if get_config_for_workflow(k)}
        assert {"payroll_change", "termination"} <= lists
