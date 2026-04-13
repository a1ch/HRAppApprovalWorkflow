"""
Tests for PDF content — generates real PDFs and verifies the text content
using pdfplumber.

Install: pip install pdfplumber
Run:     pytest tests/test_pdf_content.py -v
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

try:
    import pdfplumber
    import io
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

from pdf_generator import generate_approval_pdf, build_pdf_filename

pytestmark = pytest.mark.skipif(
    not HAS_PDFPLUMBER,
    reason="pdfplumber not installed — run: pip install pdfplumber"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF as a single string."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def normalize(text: str) -> str:
    """Collapse newlines/whitespace so PDF line-wrap doesn't break assertions."""
    return " ".join(text.split())


SAMPLE_APPROVALS = [
    {"step": 1, "role": "HR Manager",       "name": "Rae-Lynn Perkins", "decision": "Approved",
     "date": "2026-04-12T10:14:00+00:00", "comments": ""},
    {"step": 2, "role": "2nd Level Manager", "name": "Keith Haynes",     "decision": "Approved",
     "date": "2026-04-12T11:30:00+00:00", "comments": "Budget confirmed."},
    {"step": 3, "role": "GM/Director",       "name": "Quanah Gilmore",   "decision": "Approved",
     "date": "2026-04-12T14:45:00+00:00", "comments": ""},
]

SAMPLE_DETAILS = {
    "request_type":    "Backfill – Budgeted",
    "employee_name":   "John Smith",
    "employee_number": "1003500",
    "initiator_name":  "Chris Hayslip",
    "submitted_date":  "2026-04-12T09:00:00+00:00",
    "effective_date":  "2026-05-01",
    "notes":           "Replacing departing service tech in Midland.",
}


@pytest.fixture(scope="module")
def sample_pdf() -> bytes:
    return generate_approval_pdf(
        request_details=SAMPLE_DETAILS,
        workflow_name="Backfill – Budgeted",
        workflow_category="Job Requisition",
        approvals=SAMPLE_APPROVALS,
        notify_roles=["Benefits Specialist", "Payroll Manager"],
        fully_approved_date="2026-04-12T14:45:00+00:00",
        request_id="item-1042",
    )


# ---------------------------------------------------------------------------
# PDF is valid
# ---------------------------------------------------------------------------

class TestPDFIsValid:

    def test_pdf_is_bytes(self, sample_pdf):
        assert isinstance(sample_pdf, bytes)

    def test_pdf_not_empty(self, sample_pdf):
        assert len(sample_pdf) > 1000

    def test_pdf_starts_with_pdf_header(self, sample_pdf):
        assert sample_pdf[:4] == b"%PDF"

    def test_pdf_is_readable_by_pdfplumber(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert isinstance(text, str)
        assert len(text) > 0


# ---------------------------------------------------------------------------
# Request details appear in PDF
# ---------------------------------------------------------------------------

class TestPDFRequestDetails:

    def test_employee_name_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "John Smith" in text

    def test_employee_number_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "1003500" in text

    def test_initiator_name_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Chris Hayslip" in text

    def test_workflow_name_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Backfill" in text

    def test_workflow_category_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Job Requisition" in text

    def test_request_id_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "item-1042" in text

    def test_notes_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Midland" in text

    def test_effective_date_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "2026-05-01" in text or "May" in text


# ---------------------------------------------------------------------------
# Approval chain appears in PDF
# ---------------------------------------------------------------------------

class TestPDFApprovalChain:

    def test_hr_manager_name_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Rae-Lynn Perkins" in text

    def test_second_level_manager_name_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Keith Haynes" in text

    def test_gm_director_name_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Quanah Gilmore" in text

    def test_approved_decision_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Approved" in text

    def test_approver_comments_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Budget confirmed" in normalize(text)


# ---------------------------------------------------------------------------
# Notify roles appear in PDF
# ---------------------------------------------------------------------------

class TestPDFNotifyRoles:

    def test_benefits_specialist_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Benefits Specialist" in text

    def test_payroll_manager_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Payroll Manager" in text


# ---------------------------------------------------------------------------
# Approved stamp / status
# ---------------------------------------------------------------------------

class TestPDFApprovedStatus:

    def test_fully_approved_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "FULLY APPROVED" in text or "Fully Approved" in text

    def test_stream_flo_branding_in_pdf(self, sample_pdf):
        text = extract_text(sample_pdf)
        assert "Stream-Flo" in text


# ---------------------------------------------------------------------------
# Different workflows produce different PDFs
# ---------------------------------------------------------------------------

class TestPDFVariation:

    def test_different_employees_produce_different_pdfs(self):
        details1 = {**SAMPLE_DETAILS, "employee_name": "John Smith"}
        details2 = {**SAMPLE_DETAILS, "employee_name": "David Almaraz"}

        pdf1 = generate_approval_pdf(
            request_details=details1, workflow_name="Backfill – Budgeted",
            workflow_category="Job Requisition", approvals=SAMPLE_APPROVALS,
            notify_roles=[], fully_approved_date="2026-04-12T14:45:00+00:00",
            request_id="item-001",
        )
        pdf2 = generate_approval_pdf(
            request_details=details2, workflow_name="Backfill – Budgeted",
            workflow_category="Job Requisition", approvals=SAMPLE_APPROVALS,
            notify_roles=[], fully_approved_date="2026-04-12T14:45:00+00:00",
            request_id="item-002",
        )

        text1 = extract_text(pdf1)
        text2 = extract_text(pdf2)
        assert "John Smith" in text1
        assert "David Almaraz" in text2
        assert "John Smith" not in text2
        assert "David Almaraz" not in text1

    def test_no_notify_roles_pdf_still_valid(self):
        pdf = generate_approval_pdf(
            request_details=SAMPLE_DETAILS,
            workflow_name="Backfill – Budgeted",
            workflow_category="Job Requisition",
            approvals=SAMPLE_APPROVALS,
            notify_roles=[],
            fully_approved_date="2026-04-12T14:45:00+00:00",
            request_id="item-003",
        )
        text = extract_text(pdf)
        assert "John Smith" in text
        assert pdf[:4] == b"%PDF"

    def test_empty_notes_pdf_still_valid(self):
        details = {**SAMPLE_DETAILS, "notes": ""}
        pdf = generate_approval_pdf(
            request_details=details,
            workflow_name="Termination – Discharge",
            workflow_category="Payroll Change Notice",
            approvals=SAMPLE_APPROVALS,
            notify_roles=["Benefits Specialist"],
            fully_approved_date="2026-04-12T14:45:00+00:00",
            request_id="item-004",
        )
        assert pdf[:4] == b"%PDF"
        text = extract_text(pdf)
        assert "John Smith" in text

    def test_approver_with_comments_shows_comments(self):
        approvals_with_comments = [
            {"step": 1, "role": "HR Manager", "name": "Rae-Lynn Perkins",
             "decision": "Approved", "date": "2026-04-12T10:00:00+00:00",
             "comments": "Approved pending budget sign-off."},
        ]
        pdf = generate_approval_pdf(
            request_details=SAMPLE_DETAILS,
            workflow_name="Backfill – Budgeted",
            workflow_category="Job Requisition",
            approvals=approvals_with_comments,
            notify_roles=[],
            fully_approved_date="2026-04-12T10:00:00+00:00",
            request_id="item-005",
        )
        text = extract_text(pdf)
        assert "Approved pending budget sign-off" in normalize(text)
