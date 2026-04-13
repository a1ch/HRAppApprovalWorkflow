"""
Tests for resolve_role and _resolve_dynamic_role in orchestrator.py.

Static role resolution now goes through HRRolesClient (SharePoint list),
so those tests use a FakeRolesClient instead of env vars.

Run: pytest tests/test_role_resolution.py -v
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

from orchestrator import resolve_role, _resolve_dynamic_role

FULL_FIELDS = {
    "DirectManagerName":       "Chris Hayslip",
    "DirectManagerEmail":      "chayslip@streamflo.com",
    "SecondLevelManagerName":  "Keith Haynes",
    "SecondLevelManagerEmail": "khaynes@streamflo.com",
    "HiringManagerName":       "Chris Hayslip",
    "HiringManagerEmail":      "chayslip@streamflo.com",
    "GMDirectorName":          "Quanah Gilmore",
    "GMDirectorEmail":         "qgilmore@streamflo.com",
    "ExecutiveName":           "Sean Wilcock",
    "ExecutiveEmail":          "swilcock@streamflo.com",
    "CEOName":                 "Mark McNeill",
    "CEOEmail":                "mmcneill@streamflo.com",
}

STATIC_ROLE_DATA = {
    "HR Manager":          ("Rae-Lynn Perkins",    "rlperkins@streamflo.com"),
    "Payroll Manager":     ("Gary Thedford",       "gthedford@streamflo.com"),
    "Benefits Specialist": ("Sandra Carrisalez",   "scarrisalez@streamflo.com"),
    "HR Generalist":       ("Tanya Parashar",      "tparashar@streamflo.com"),
}


class FakeRolesClient:
    def __init__(self, roles=None):
        self._roles = roles if roles is not None else dict(STATIC_ROLE_DATA)

    def resolve_role(self, role):
        if role not in self._roles:
            raise ValueError(f"No active entry for role '{role}' in HR Approval Roles list")
        return self._roles[role]

    def get_all_emails_for_role(self, role):
        if role not in self._roles:
            return []
        return [self._roles[role]]

    def invalidate_cache(self):
        pass


# ---------------------------------------------------------------------------
# Dynamic role resolution
# ---------------------------------------------------------------------------

class TestResolveDynamicRole:

    def test_direct_manager_resolves(self):
        name, email = _resolve_dynamic_role("Direct Manager", FULL_FIELDS)
        assert name == "Chris Hayslip"
        assert email == "chayslip@streamflo.com"

    def test_second_level_manager_resolves(self):
        name, email = _resolve_dynamic_role("2nd Level Manager", FULL_FIELDS)
        assert name == "Keith Haynes"
        assert email == "khaynes@streamflo.com"

    def test_hiring_manager_resolves(self):
        name, email = _resolve_dynamic_role("Hiring Manager", FULL_FIELDS)
        assert email == "chayslip@streamflo.com"

    def test_gm_director_resolves(self):
        name, email = _resolve_dynamic_role("GM/Director", FULL_FIELDS)
        assert name == "Quanah Gilmore"
        assert email == "qgilmore@streamflo.com"

    def test_executive_resolves(self):
        name, email = _resolve_dynamic_role("Executive", FULL_FIELDS)
        assert name == "Sean Wilcock"
        assert email == "swilcock@streamflo.com"

    def test_ceo_resolves(self):
        name, email = _resolve_dynamic_role("CEO", FULL_FIELDS)
        assert name == "Mark McNeill"
        assert email == "mmcneill@streamflo.com"

    def test_missing_email_raises(self):
        fields = dict(FULL_FIELDS)
        fields["GMDirectorEmail"] = ""
        with pytest.raises(ValueError, match="Missing email"):
            _resolve_dynamic_role("GM/Director", fields)

    def test_missing_field_entirely_raises(self):
        fields = {k: v for k, v in FULL_FIELDS.items() if "GMDirector" not in k}
        with pytest.raises(ValueError, match="Missing email"):
            _resolve_dynamic_role("GM/Director", fields)

    def test_non_dynamic_role_raises(self):
        with pytest.raises(ValueError, match="not a dynamic role"):
            _resolve_dynamic_role("HR Manager", FULL_FIELDS)


# ---------------------------------------------------------------------------
# Static role resolution via HRRolesClient
# ---------------------------------------------------------------------------

class TestStaticRoleViaRolesClient:

    def test_hr_manager_resolves(self):
        name, email = FakeRolesClient().resolve_role("HR Manager")
        assert email == "rlperkins@streamflo.com"
        assert name == "Rae-Lynn Perkins"

    def test_payroll_manager_resolves(self):
        _, email = FakeRolesClient().resolve_role("Payroll Manager")
        assert email == "gthedford@streamflo.com"

    def test_benefits_specialist_resolves(self):
        _, email = FakeRolesClient().resolve_role("Benefits Specialist")
        assert email == "scarrisalez@streamflo.com"

    def test_hr_generalist_resolves(self):
        _, email = FakeRolesClient().resolve_role("HR Generalist")
        assert email == "tparashar@streamflo.com"

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="No active entry"):
            FakeRolesClient().resolve_role("Unknown Role")

    def test_empty_roles_client_raises(self):
        with pytest.raises(ValueError):
            FakeRolesClient(roles={}).resolve_role("HR Manager")


# ---------------------------------------------------------------------------
# resolve_role — combined fallback logic
# ---------------------------------------------------------------------------

class TestResolveRole:

    def test_dynamic_role_resolved_from_fields(self):
        name, email = resolve_role("Direct Manager", FULL_FIELDS, FakeRolesClient())
        assert email == "chayslip@streamflo.com"

    def test_static_role_resolved_via_roles_client(self):
        name, email = resolve_role("HR Manager", {}, FakeRolesClient())
        assert email == "rlperkins@streamflo.com"
        assert name == "Rae-Lynn Perkins"

    def test_ceo_resolved_from_fields(self):
        name, email = resolve_role("CEO", FULL_FIELDS, FakeRolesClient())
        assert email == "mmcneill@streamflo.com"

    def test_missing_dynamic_email_raises(self):
        fields = dict(FULL_FIELDS)
        fields["CEOEmail"] = ""
        with pytest.raises(ValueError):
            resolve_role("CEO", fields, FakeRolesClient())

    def test_email_returned_as_is_from_fields(self):
        fields = dict(FULL_FIELDS)
        fields["GMDirectorEmail"] = "QGilmore@Streamflo.com"
        _, email = resolve_role("GM/Director", fields, FakeRolesClient())
        assert email == "QGilmore@Streamflo.com"

    def test_all_dynamic_roles_resolvable(self):
        dynamic_roles = [
            "Direct Manager", "2nd Level Manager", "Hiring Manager",
            "GM/Director", "Executive", "CEO",
        ]
        for role in dynamic_roles:
            name, email = resolve_role(role, FULL_FIELDS, FakeRolesClient())
            assert "@" in email, f"{role} resolved to invalid email: {email}"

    def test_all_static_roles_resolvable(self):
        static_roles = ["HR Manager", "Payroll Manager", "Benefits Specialist", "HR Generalist"]
        for role in static_roles:
            name, email = resolve_role(role, {}, FakeRolesClient())
            assert "@" in email, f"{role} resolved to invalid email: {email}"

    def test_no_roles_client_raises_for_static_role(self):
        with pytest.raises(ValueError, match="no HRRolesClient provided"):
            resolve_role("HR Manager", {}, None)

    def test_dynamic_role_does_not_need_roles_client(self):
        """Dynamic roles resolve from fields alone — no client needed."""
        name, email = resolve_role("Direct Manager", FULL_FIELDS, None)
        assert email == "chayslip@streamflo.com"
