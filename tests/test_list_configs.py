"""
Tests for list_configs.py and approval_matrix.py coverage.

Verifies:
- All 30 workflows are covered by exactly one list config
- Every workflow key in approval_matrix.py maps to a list config
- Every list config has required columns defined
- Approval chain roles used in each workflow have a matching column on the list
- No workflow key is orphaned or duplicated across lists
- All 6 list paths are valid SharePoint URL segments
- PERSON_COL_ROLE_MAP covers every role used in any workflow chain

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

from approval_matrix import WORKFLOWS, RequestCategory
from list_configs import LIST_CONFIGS, PERSON_COL_ROLE_MAP, get_config_for_workflow, get_list_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def all_workflow_keys():
    return set(WORKFLOWS.keys())

def all_covered_keys():
    covered = set()
    for config in LIST_CONFIGS.values():
        covered.update(config.workflow_keys)
    return covered

def chain_roles(wf):
    """Full approval chain roles for a workflow including CEO if required."""
    roles = list(wf.approval_chain)
    if wf.requires_ceo:
        roles.append("CEO")
    return roles


# ---------------------------------------------------------------------------
# Coverage — every workflow maps to a list
# ---------------------------------------------------------------------------

class TestWorkflowCoverage:

    def test_all_workflow_keys_covered_by_a_list(self):
        missing = all_workflow_keys() - all_covered_keys()
        assert missing == set(), f"Workflows not covered by any list config: {missing}"

    def test_no_extra_workflow_keys_in_lists(self):
        """No list config references a workflow key that doesn't exist in approval_matrix."""
        extra = all_covered_keys() - all_workflow_keys()
        assert extra == set(), f"List configs reference non-existent workflow keys: {extra}"

    def test_no_workflow_key_in_multiple_lists(self):
        """Each workflow should belong to exactly one list."""
        seen = {}
        for list_key, config in LIST_CONFIGS.items():
            for wf_key in config.workflow_keys:
                if wf_key in seen:
                    assert False, f"Workflow '{wf_key}' appears in both '{seen[wf_key]}' and '{list_key}'"
                seen[wf_key] = list_key

    def test_total_workflow_count(self):
        assert len(WORKFLOWS) == 30, f"Expected 30 workflows, got {len(WORKFLOWS)}"

    def test_total_covered_count_matches(self):
        assert len(all_covered_keys()) == len(all_workflow_keys()), \
            "Number of covered workflow keys doesn't match total workflows"


# ---------------------------------------------------------------------------
# List config structure
# ---------------------------------------------------------------------------

class TestListConfigStructure:

    def test_all_six_lists_present(self):
        expected = {"leave_of_absence", "offer_letters", "payroll_change",
                    "termination", "workforce_requisition", "promotion"}
        assert set(LIST_CONFIGS.keys()) == expected

    def test_all_lists_have_display_name(self):
        for key, config in LIST_CONFIGS.items():
            assert config.display_name, f"{key}: missing display_name"

    def test_all_lists_have_list_path(self):
        for key, config in LIST_CONFIGS.items():
            assert config.list_path.startswith("Lists/"), \
                f"{key}: list_path should start with 'Lists/', got '{config.list_path}'"

    def test_all_lists_have_employee_name_col(self):
        for key, config in LIST_CONFIGS.items():
            assert config.employee_name_col, f"{key}: missing employee_name_col"

    def test_all_lists_have_initiator_col(self):
        for key, config in LIST_CONFIGS.items():
            assert config.initiator_col, f"{key}: missing initiator_col"

    def test_all_lists_have_status_col(self):
        for key, config in LIST_CONFIGS.items():
            assert config.status_col, f"{key}: missing status_col"

    def test_all_list_paths_url_encoded(self):
        """List paths with spaces should use %20 encoding."""
        for key, config in LIST_CONFIGS.items():
            assert " " not in config.list_path, \
                f"{key}: list_path contains spaces, should use %20: '{config.list_path}'"

    def test_all_lists_have_at_least_one_workflow_key(self):
        for key, config in LIST_CONFIGS.items():
            assert len(config.workflow_keys) > 0, f"{key}: no workflow keys defined"


# ---------------------------------------------------------------------------
# Role-to-column mapping per list
# ---------------------------------------------------------------------------

class TestRoleColumnMapping:

    def _get_col_for_role(self, config, role: str):
        """Look up the column name on a config for a given approval chain role."""
        attr = PERSON_COL_ROLE_MAP.get(role)
        if attr is None:
            return None
        return getattr(config, attr, None)

    def test_every_chain_role_has_column_on_its_list(self):
        """
        For each workflow, every role in the approval chain should have
        a corresponding column defined on that list's config.
        """
        failures = []
        for wf_key, wf in WORKFLOWS.items():
            result = get_config_for_workflow(wf_key)
            assert result is not None, f"No list config found for {wf_key}"
            list_key, config = result

            for role in chain_roles(wf):
                col = self._get_col_for_role(config, role)
                if col is None:
                    failures.append(
                        f"Workflow '{wf_key}' on list '{list_key}': "
                        f"role '{role}' has no column defined"
                    )

        assert failures == [], "Missing role columns:\n" + "\n".join(failures)

    def test_notify_roles_have_column_or_env_fallback(self):
        """
        Notify roles should either have a column on the list
        or be a static role resolvable via env vars (HR Manager, Payroll Manager, etc.)
        """
        static_roles = {"HR Manager", "Payroll Manager", "Benefits Specialist", "HR Generalist"}
        failures = []

        for wf_key, wf in WORKFLOWS.items():
            result = get_config_for_workflow(wf_key)
            assert result is not None
            list_key, config = result

            for role in wf.notify_roles:
                col = self._get_col_for_role(config, role)
                if col is None and role not in static_roles:
                    failures.append(
                        f"Workflow '{wf_key}' on list '{list_key}': "
                        f"notify role '{role}' has no column and is not a static role"
                    )

        assert failures == [], "Missing notify role columns:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# PERSON_COL_ROLE_MAP completeness
# ---------------------------------------------------------------------------

class TestPersonColRoleMap:

    def test_all_chain_roles_in_map(self):
        """Every role that appears in any workflow's approval chain should be in PERSON_COL_ROLE_MAP."""
        all_roles = set()
        for wf in WORKFLOWS.values():
            all_roles.update(wf.approval_chain)
            if wf.requires_ceo:
                all_roles.add("CEO")

        missing = all_roles - set(PERSON_COL_ROLE_MAP.keys())
        assert missing == set(), f"Roles used in chains but missing from PERSON_COL_ROLE_MAP: {missing}"

    def test_all_notify_roles_in_map(self):
        """Every role that appears in any notify_roles list should be in PERSON_COL_ROLE_MAP."""
        all_notify = set()
        for wf in WORKFLOWS.values():
            all_notify.update(wf.notify_roles)

        missing = all_notify - set(PERSON_COL_ROLE_MAP.keys())
        assert missing == set(), f"Notify roles missing from PERSON_COL_ROLE_MAP: {missing}"


# ---------------------------------------------------------------------------
# get_config_for_workflow helper
# ---------------------------------------------------------------------------

class TestGetConfigForWorkflow:

    def test_returns_correct_list_for_known_key(self):
        result = get_config_for_workflow("job_req_backfill_budgeted")
        assert result is not None
        list_key, config = result
        assert list_key == "workforce_requisition"
        assert config.display_name == "Workforce Requisition Form"

    def test_returns_correct_list_for_termination(self):
        result = get_config_for_workflow("pcn_termination_discharge")
        assert result is not None
        list_key, config = result
        assert list_key == "termination"

    def test_returns_correct_list_for_loa(self):
        result = get_config_for_workflow("loa_fmla")
        assert result is not None
        list_key, config = result
        assert list_key == "leave_of_absence"

    def test_returns_correct_list_for_promotion(self):
        result = get_config_for_workflow("promo_salaried")
        assert result is not None
        list_key, config = result
        assert list_key == "promotion"

    def test_returns_none_for_unknown_key(self):
        result = get_config_for_workflow("completely_made_up_key")
        assert result is None

    def test_get_list_config_returns_correct_config(self):
        config = get_list_config("termination")
        assert config is not None
        assert config.display_name == "Termination Form"

    def test_get_list_config_returns_none_for_unknown(self):
        assert get_list_config("nonexistent_list") is None


# ---------------------------------------------------------------------------
# Category coverage — all 5 categories have workflows and lists
# ---------------------------------------------------------------------------

class TestCategoryCoverage:

    def test_all_categories_have_workflows(self):
        for cat in RequestCategory:
            wfs = [wf for wf in WORKFLOWS.values() if wf.category == cat]
            assert len(wfs) > 0, f"Category {cat.value} has no workflows"

    def test_job_requisition_on_workforce_list(self):
        from approval_matrix import RequestCategory
        jrq_keys = [k for k, v in WORKFLOWS.items() if v.category == RequestCategory.JOB_REQUISITION]
        for key in jrq_keys:
            result = get_config_for_workflow(key)
            assert result is not None
            list_key, _ = result
            assert list_key == "workforce_requisition", \
                f"Job req workflow '{key}' should be on workforce_requisition, got '{list_key}'"

    def test_loa_on_leave_list(self):
        from approval_matrix import RequestCategory
        loa_keys = [k for k, v in WORKFLOWS.items() if v.category == RequestCategory.LEAVE_OF_ABSENCE]
        for key in loa_keys:
            result = get_config_for_workflow(key)
            assert result is not None
            list_key, _ = result
            assert list_key == "leave_of_absence", \
                f"LOA workflow '{key}' should be on leave_of_absence, got '{list_key}'"

    def test_offer_letters_on_offer_list(self):
        from approval_matrix import RequestCategory
        offer_keys = [k for k, v in WORKFLOWS.items() if v.category == RequestCategory.OFFER_LETTER]
        for key in offer_keys:
            result = get_config_for_workflow(key)
            assert result is not None
            list_key, _ = result
            assert list_key == "offer_letters", \
                f"Offer letter workflow '{key}' should be on offer_letters, got '{list_key}'"

    def test_promotion_on_promotion_list(self):
        from approval_matrix import RequestCategory
        promo_keys = [k for k, v in WORKFLOWS.items() if v.category == RequestCategory.PROMOTION]
        for key in promo_keys:
            result = get_config_for_workflow(key)
            assert result is not None
            list_key, _ = result
            assert list_key == "promotion", \
                f"Promotion workflow '{key}' should be on promotion list, got '{list_key}'"

    def test_payroll_change_split_across_two_lists(self):
        """PCN workflows are split between payroll_change and termination lists."""
        from approval_matrix import RequestCategory
        pcn_keys = [k for k, v in WORKFLOWS.items() if v.category == RequestCategory.PAYROLL_CHANGE]
        list_keys = set()
        for key in pcn_keys:
            result = get_config_for_workflow(key)
            assert result is not None
            list_keys.add(result[0])
        assert "payroll_change" in list_keys
        assert "termination" in list_keys
