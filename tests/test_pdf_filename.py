"""
Tests for build_pdf_filename in pdf_generator.py.

Run: pytest tests/test_pdf_filename.py -v
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

from pdf_generator import build_pdf_filename


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

class TestBuildPdfFilenameBasic:

    def test_returns_pdf_extension(self):
        name = build_pdf_filename("John Smith", "Backfill – Budgeted", "2026-04-11T16:45:00+00:00")
        assert name.endswith(".pdf")

    def test_starts_with_approval_record(self):
        name = build_pdf_filename("John Smith", "Backfill – Budgeted", "2026-04-11T16:45:00+00:00")
        assert name.startswith("ApprovalRecord_")

    def test_contains_date(self):
        name = build_pdf_filename("John Smith", "Backfill – Budgeted", "2026-04-11T16:45:00+00:00")
        assert "20260411" in name

    def test_no_spaces_in_filename(self):
        name = build_pdf_filename("John Smith", "Backfill – Budgeted", "2026-04-11T16:45:00+00:00")
        assert " " not in name

    def test_format_is_approvalrecord_emp_req_date(self):
        name = build_pdf_filename("John Smith", "Backfill – Budgeted", "2026-04-11T16:45:00+00:00")
        parts = name.replace(".pdf", "").split("_")
        assert parts[0] == "ApprovalRecord"
        assert len(parts) == 4   # ApprovalRecord _ emp _ req _ date


# ---------------------------------------------------------------------------
# Employee name handling
# ---------------------------------------------------------------------------

class TestEmployeeName:

    def test_spaces_removed(self):
        name = build_pdf_filename("John Smith", "Backfill", "2026-04-11T16:45:00+00:00")
        assert "JohnSmith" in name or "Johnsmith" in name.lower()

    def test_long_name_truncated(self):
        long_name = "Bartholomew Alexandros Christodoulou-Papadimitriou"
        name = build_pdf_filename(long_name, "Backfill", "2026-04-11T16:45:00+00:00")
        parts = name.replace(".pdf", "").split("_")
        emp_part = parts[1]
        assert len(emp_part) <= 20

    def test_single_name(self):
        name = build_pdf_filename("Prince", "Backfill", "2026-04-11T16:45:00+00:00")
        assert name.endswith(".pdf")
        assert "Prince" in name

    def test_special_characters_stripped(self):
        name = build_pdf_filename("O'Brien, Sean", "Backfill", "2026-04-11T16:45:00+00:00")
        assert "'" not in name
        assert "," not in name

    def test_hyphenated_name(self):
        name = build_pdf_filename("Mary-Jane Watson", "Backfill", "2026-04-11T16:45:00+00:00")
        assert " " not in name
        assert name.endswith(".pdf")


# ---------------------------------------------------------------------------
# Request type handling
# ---------------------------------------------------------------------------

class TestRequestType:

    def test_em_dash_stripped(self):
        name = build_pdf_filename("John Smith", "Backfill – Budgeted", "2026-04-11T16:45:00+00:00")
        assert "–" not in name

    def test_slash_stripped(self):
        name = build_pdf_filename("John Smith", "LOA/FMLA", "2026-04-11T16:45:00+00:00")
        assert "/" not in name

    def test_long_request_type_truncated(self):
        long_type = "Salaried Promotional Position Change Outside Merit Cycle With Additional Details"
        name = build_pdf_filename("John Smith", long_type, "2026-04-11T16:45:00+00:00")
        parts = name.replace(".pdf", "").split("_")
        req_part = parts[2]
        assert len(req_part) <= 25

    def test_spaces_removed_from_request_type(self):
        name = build_pdf_filename("John Smith", "Supervisor Change", "2026-04-11T16:45:00+00:00")
        assert " " not in name

    def test_all_workflow_types_produce_valid_filename(self):
        request_types = [
            "Backfill – Budgeted",
            "Backfill – Unbudgeted",
            "New Position – Budgeted",
            "Temp/Contract Labor Requisition – Budgeted",
            "Salaried Promotional Position Change – Outside Merit Cycle",
            "LOA/FMLA",
            "Military LOA",
            "Termination – Discharge",
            "Termination – Resignation",
            "Termination – Retirement",
            "Candidate Offer Letter – Backfill Budgeted",
        ]
        for req_type in request_types:
            name = build_pdf_filename("John Smith", req_type, "2026-04-11T16:45:00+00:00")
            assert name.endswith(".pdf"), f"Bad filename for '{req_type}': {name}"
            assert " " not in name, f"Spaces in filename for '{req_type}': {name}"
            assert "–" not in name, f"Em dash in filename for '{req_type}': {name}"
            assert "/" not in name, f"Slash in filename for '{req_type}': {name}"


# ---------------------------------------------------------------------------
# Date handling
# ---------------------------------------------------------------------------

class TestDateHandling:

    def test_iso_datetime_with_timezone(self):
        name = build_pdf_filename("John Smith", "Backfill", "2026-04-11T16:45:00+00:00")
        assert "20260411" in name

    def test_iso_datetime_with_z(self):
        name = build_pdf_filename("John Smith", "Backfill", "2026-04-11T16:45:00Z")
        assert "20260411" in name

    def test_different_dates(self):
        name1 = build_pdf_filename("John Smith", "Backfill", "2026-01-15T10:00:00+00:00")
        name2 = build_pdf_filename("John Smith", "Backfill", "2026-12-31T10:00:00+00:00")
        assert "20260115" in name1
        assert "20261231" in name2

    def test_invalid_date_falls_back_gracefully(self):
        """Bad date string should not raise — falls back to today's date."""
        name = build_pdf_filename("John Smith", "Backfill", "not-a-date")
        assert name.endswith(".pdf")
        assert "ApprovalRecord_" in name

    def test_empty_date_falls_back_gracefully(self):
        name = build_pdf_filename("John Smith", "Backfill", "")
        assert name.endswith(".pdf")

    def test_none_like_empty_string_date(self):
        name = build_pdf_filename("John Smith", "Backfill", "")
        assert " " not in name


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------

class TestFilenameUniqueness:

    def test_different_employees_produce_different_filenames(self):
        name1 = build_pdf_filename("John Smith", "Backfill", "2026-04-11T16:45:00+00:00")
        name2 = build_pdf_filename("Jane Doe", "Backfill", "2026-04-11T16:45:00+00:00")
        assert name1 != name2

    def test_different_request_types_produce_different_filenames(self):
        name1 = build_pdf_filename("John Smith", "Backfill – Budgeted", "2026-04-11T16:45:00+00:00")
        name2 = build_pdf_filename("John Smith", "Termination – Discharge", "2026-04-11T16:45:00+00:00")
        assert name1 != name2

    def test_different_dates_produce_different_filenames(self):
        name1 = build_pdf_filename("John Smith", "Backfill", "2026-04-11T16:45:00+00:00")
        name2 = build_pdf_filename("John Smith", "Backfill", "2026-05-20T16:45:00+00:00")
        assert name1 != name2
