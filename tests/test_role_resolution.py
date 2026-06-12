"""
Tests for the form-only resolve_role / parse_person_text.

Every approver email now comes from the request form's *Text column
("Display Name <email>"). There is no Entra chain or HR Approval Roles list
fallback — the form is the single source of truth.

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

from orchestrator import resolve_role, parse_person_text, ROLE_TEXT_FIELD

FORM_FIELDS = {
    "DirectManagerText":      "Chris Hayslip <chayslip@streamflo.com>",
    "SecondLevelManagerText": "Keith Haynes <khaynes@streamflo.com>",
    "HiringSupervisorText":   "Chris Hayslip <chayslip@streamflo.com>",
    "HRManagerText":          "Rae-Lynn Perkins <rlperkins@streamflo.com>",
    "GMDirectorText":         "Quanah Gilmore <qgilmore@streamflo.com>",
    "ExecutiveText":          "Sean Wilcock <swilcock@streamflo.com>",
    "CEOText":                "Mark McNeill <mmcneill@streamflo.com>",
    "PayrollManagerText":     "Gary Thedford <gthedford@streamflo.com>",
    "BenefitsSpecialistText": "Sandra Carrisalez <scarrisalez@streamflo.com>",
    "HRGeneralistText":       "Tanya Parashar <tparashar@streamflo.com>",
}


class TestParsePersonText:
    def test_name_and_email(self):
        assert parse_person_text("Jane Smith <jsmith@streamflo.com>") == ("Jane Smith", "jsmith@streamflo.com")

    def test_bare_email(self):
        assert parse_person_text("jsmith@streamflo.com") == ("jsmith@streamflo.com", "jsmith@streamflo.com")

    def test_name_only(self):
        assert parse_person_text("Jane Smith") == ("Jane Smith", "")

    def test_blank(self):
        assert parse_person_text("") == ("", "")
        assert parse_person_text(None) == ("", "")

    def test_legacy_person_dict(self):
        assert parse_person_text({"Title": "Jane", "Email": "j@x.com"}) == ("Jane", "j@x.com")


class TestResolveRole:
    @pytest.mark.parametrize("role,email", [
        ("Direct Manager",      "chayslip@streamflo.com"),
        ("2nd Level Manager",   "khaynes@streamflo.com"),
        ("Hiring Manager",      "chayslip@streamflo.com"),
        ("HR Manager",          "rlperkins@streamflo.com"),
        ("GM/Director",         "qgilmore@streamflo.com"),
        ("Executive",           "swilcock@streamflo.com"),
        ("CEO",                 "mmcneill@streamflo.com"),
        ("Payroll Manager",     "gthedford@streamflo.com"),
        ("Benefits Specialist", "scarrisalez@streamflo.com"),
        ("HR Generalist",       "tparashar@streamflo.com"),
    ])
    def test_role_resolves_from_form(self, role, email):
        name, got = resolve_role(role, FORM_FIELDS)
        assert got == email
        assert name

    def test_every_chain_role_has_a_column(self):
        for role in ["Direct Manager", "2nd Level Manager", "Hiring Manager", "HR Manager",
                     "GM/Director", "Executive", "CEO", "Payroll Manager",
                     "Benefits Specialist", "HR Generalist"]:
            assert role in ROLE_TEXT_FIELD

    def test_email_case_preserved(self):
        fields = dict(FORM_FIELDS)
        fields["GMDirectorText"] = "Q Gilmore <QGilmore@Streamflo.com>"
        assert resolve_role("GM/Director", fields)[1] == "QGilmore@Streamflo.com"

    def test_missing_value_raises(self):
        fields = dict(FORM_FIELDS)
        fields["HRManagerText"] = ""
        with pytest.raises(ValueError, match="Missing approver email"):
            resolve_role("HR Manager", fields)

    def test_missing_column_raises(self):
        fields = {k: v for k, v in FORM_FIELDS.items() if k != "HRManagerText"}
        with pytest.raises(ValueError, match="Missing approver email"):
            resolve_role("HR Manager", fields)

    def test_unknown_role_raises(self):
        with pytest.raises(ValueError, match="no approver column"):
            resolve_role("Wizard", FORM_FIELDS)
