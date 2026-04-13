"""
Tests for resolve_role, _resolve_static_role, and _resolve_dynamic_role in orchestrator.py
and build_pdf_filename in pdf_generator.py.

Run: pytest tests/test_role_resolution.py tests/test_pdf_filename.py -v
"""

import sys
import os
import types
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../function_app"))

for _mod in ("msal", "requests", "azure", "azure.functions"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
_req_exc = types.ModuleType("requests.exceptions")
_req_exc.HTTPError = type("HTTPError", (Exception,), {})
sys.modules["requests.exceptions"] = _req_exc

from orchestrator import resolve_role, _resolve_static_role, _resolve_dynamic_role

ROLE_ENV = {
    "EMAIL_HR_MANAGER":          "rlperkins@streamflo.com",
    "EMAIL_PAYROLL_MANAGER":     "gthedford@streamflo.com",
    "EMAIL_BENEFITS_SPECIALIST": "scarrisalez@streamflo.com",
    "EMAIL_HR_GENERALIST":       "tparashar@streamflo.com",
}

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


# ---------------------------------------------------------------------------
# Static role resolution
# ---------------------------------------------------------------------------

class TestResolveStaticRole:

    def test_hr_manager_resolves(self):
        with patch.dict(os.environ, ROLE_ENV):
            name, email = _resolve_static_role("HR Manager")
        assert email == "rlperkins@streamflo.com"
        assert name == "HR Manager"

    def test_payroll_manager_resolves(self):
        with patch.dict(os.environ, ROLE_ENV):
            name, email = _resolve_static_role("Payroll Manager")
        assert email == "gthedford@streamflo.com"

    def test_benefits_specialist_resolves(self):
        with patch.dict(os.environ, ROLE_ENV):
            name, email = _resolve_static_role("Benefits Specialist")
        assert email == "scarrisalez@streamflo.com"

    def test_hr_generalist_resolves(self):
        with patch.dict(os.environ, ROLE_ENV):
            name, email = _resolve_static_role("HR Generalist")
        assert email == "tparashar@streamflo.com"

    def test_unknown_static_role_raises(self):
        with patch.dict(os.environ, ROLE_ENV):
            with pytest.raises(ValueError, match="No static mapping"):
                _resolve_static_role("Unknown Role")

    def test_missing_env_var_uses_fallback_email(self):
        """If env var not set, falls back to role.lower@streamflo.com."""
        with patch.dict(os.environ, {}, clear=True):
            name, email = _resolve_static_role("HR Manager")
        assert "hr.manager" in email


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

    def test_unknown_dynamic_role_falls_back_to_static(self):
        """A role not in the dynamic map falls through to static resolution."""
        with patch.dict(os.environ, ROLE_ENV):
            name, email = _resolve_dynamic_role("HR Manager", FULL_FIELDS)
        assert email == "rlperkins@streamflo.com"


# ---------------------------------------------------------------------------
# resolve_role — combined fallback logic
# ---------------------------------------------------------------------------

class TestResolveRole:

    def test_dynamic_role_resolved_first(self):
        with patch.dict(os.environ, ROLE_ENV):
            name, email = resolve_role("Direct Manager", FULL_FIELDS)
        assert email == "chayslip@streamflo.com"

    def test_static_role_resolved_when_not_in_dynamic_map(self):
        with patch.dict(os.environ, ROLE_ENV):
            name, email = resolve_role("HR Manager", FULL_FIELDS)
        assert email == "rlperkins@streamflo.com"

    def test_ceo_resolved_from_fields(self):
        with patch.dict(os.environ, ROLE_ENV):
            name, email = resolve_role("CEO", FULL_FIELDS)
        assert email == "mmcneill@streamflo.com"

    def test_missing_dynamic_email_raises(self):
        fields = dict(FULL_FIELDS)
        fields["CEOEmail"] = ""
        with patch.dict(os.environ, ROLE_ENV):
            with pytest.raises(ValueError):
                resolve_role("CEO", fields)

    def test_case_insensitive_email_not_required(self):
        """resolve_role returns the email as-is from the fields."""
        fields = dict(FULL_FIELDS)
        fields["GMDirectorEmail"] = "QGilmore@Streamflo.com"
        with patch.dict(os.environ, ROLE_ENV):
            _, email = resolve_role("GM/Director", fields)
        assert email == "QGilmore@Streamflo.com"

    def test_all_dynamic_roles_resolvable(self):
        """Every role that can appear in a workflow chain resolves without error."""
        dynamic_roles = [
            "Direct Manager", "2nd Level Manager", "Hiring Manager",
            "GM/Director", "Executive", "CEO",
        ]
        with patch.dict(os.environ, ROLE_ENV):
            for role in dynamic_roles:
                name, email = resolve_role(role, FULL_FIELDS)
                assert "@" in email, f"{role} resolved to invalid email: {email}"

    def test_all_static_roles_resolvable(self):
        static_roles = ["HR Manager", "Payroll Manager", "Benefits Specialist", "HR Generalist"]
        with patch.dict(os.environ, ROLE_ENV):
            for role in static_roles:
                name, email = resolve_role(role, {})
                assert "@" in email, f"{role} resolved to invalid email: {email}"
