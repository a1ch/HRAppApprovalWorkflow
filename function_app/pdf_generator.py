"""
Generates a professional approval record PDF for fully approved HR requests.
Uses reportlab — no external services, runs entirely inside the Azure Function.
"""

import io
from datetime import datetime, timezone
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


# ── Brand colours ─────────────────────────────────────────────────────────
NAVY       = colors.HexColor("#003366")
NAVY_LIGHT = colors.HexColor("#E6EDF5")
GREEN      = colors.HexColor("#1a7a3c")
GREEN_LITE = colors.HexColor("#EAF3DE")
RED        = colors.HexColor("#c0392b")
RED_LITE   = colors.HexColor("#FDECEA")
GRAY_DARK  = colors.HexColor("#444444")
GRAY_MID   = colors.HexColor("#888888")
GRAY_LIGHT = colors.HexColor("#F5F5F5")
BLACK      = colors.HexColor("#1a1a1a")
WHITE      = colors.white


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", fontSize=20, textColor=WHITE,
            fontName="Helvetica-Bold", leading=24, alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontSize=11, textColor=colors.HexColor("#a0b8d0"),
            fontName="Helvetica", leading=16, alignment=TA_LEFT,
        ),
        "section_head": ParagraphStyle(
            "section_head", fontSize=9, textColor=NAVY,
            fontName="Helvetica-Bold", leading=14, spaceAfter=6,
            spaceBefore=14, letterSpacing=0.8,
        ),
        "label": ParagraphStyle(
            "label", fontSize=9, textColor=GRAY_MID,
            fontName="Helvetica", leading=14,
        ),
        "value": ParagraphStyle(
            "value", fontSize=10, textColor=BLACK,
            fontName="Helvetica", leading=14,
        ),
        "value_bold": ParagraphStyle(
            "value_bold", fontSize=10, textColor=BLACK,
            fontName="Helvetica-Bold", leading=14,
        ),
        "approved_stamp": ParagraphStyle(
            "approved_stamp", fontSize=13, textColor=GREEN,
            fontName="Helvetica-Bold", leading=18, alignment=TA_CENTER,
        ),
        "footer": ParagraphStyle(
            "footer", fontSize=8, textColor=GRAY_MID,
            fontName="Helvetica", leading=12, alignment=TA_CENTER,
        ),
        "notes": ParagraphStyle(
            "notes", fontSize=9, textColor=GRAY_DARK,
            fontName="Helvetica", leading=14,
        ),
        "step_role": ParagraphStyle(
            "step_role", fontSize=9, textColor=GRAY_MID,
            fontName="Helvetica", leading=13,
        ),
        "step_name": ParagraphStyle(
            "step_name", fontSize=10, textColor=BLACK,
            fontName="Helvetica-Bold", leading=14,
        ),
        "step_decision_approved": ParagraphStyle(
            "step_decision_approved", fontSize=9, textColor=GREEN,
            fontName="Helvetica-Bold", leading=13,
        ),
    }


def _fmt_date(iso_str: str) -> str:
    """Format ISO datetime to readable string."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%B %d, %Y %I:%M %p UTC")
    except Exception:
        return iso_str


def _detail_table(rows: list[tuple[str, str]], styles: dict) -> Table:
    """Two-column label/value table for request details."""
    data = [
        [Paragraph(label, styles["label"]), Paragraph(value, styles["value"])]
        for label, value in rows
    ]
    t = Table(data, colWidths=[1.8 * inch, 4.7 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, colors.HexColor("#EEEEEE")),
    ]))
    return t


def _approver_table(approvals: list[dict], styles: dict) -> Table:
    """
    Table showing each approval step with step number, role, name, decision, date, comments.
    approvals: list of dicts with keys: step, role, name, decision, date, comments
    """
    header = [
        Paragraph("Step", styles["label"]),
        Paragraph("Role", styles["label"]),
        Paragraph("Approver", styles["label"]),
        Paragraph("Decision", styles["label"]),
        Paragraph("Date", styles["label"]),
    ]
    rows = [header]
    for a in approvals:
        decision_style = styles["step_decision_approved"]
        dec_text = a.get("decision", "Approved")
        rows.append([
            Paragraph(str(a.get("step", "")), styles["value"]),
            Paragraph(a.get("role", ""), styles["step_role"]),
            Paragraph(a.get("name", ""), styles["step_name"]),
            Paragraph(dec_text, decision_style),
            Paragraph(_fmt_date(a.get("date", "")), styles["notes"]),
        ])
        if a.get("comments"):
            rows.append([
                Paragraph("", styles["label"]),
                Paragraph("Comments:", styles["label"]),
                Paragraph(a["comments"], styles["notes"]),
                Paragraph("", styles["label"]),
                Paragraph("", styles["label"]),
            ])

    col_widths = [0.45 * inch, 1.3 * inch, 1.6 * inch, 0.9 * inch, 2.25 * inch]
    t = Table(rows, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY_LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GRAY_LIGHT]),
    ]))
    return t


def generate_approval_pdf(
    request_details: dict,
    workflow_name: str,
    workflow_category: str,
    approvals: list[dict],
    notify_roles: list[str],
    fully_approved_date: str,
    request_id: str,
) -> bytes:
    """
    Generate approval record PDF and return as bytes.

    approvals: list of dicts — {step, role, name, decision, date, comments}
    request_details: dict from orchestrator._extract_request_details()
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.75 * inch,
        title=f"Approval Record — {request_details.get('employee_name', '')}",
        author="Stream-Flo USA HR System",
        subject=workflow_name,
    )

    s = _styles()
    story = []

    # ── Header banner ────────────────────────────────────────────────────
    header_data = [[
        Paragraph("Stream-Flo USA", s["title"]),
        Paragraph(
            f"HR Approval Record<br/><font size='9' color='#a0b8d0'>"
            f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y')}</font>",
            s["subtitle"],
        ),
    ]]
    header_table = Table(header_data, colWidths=[4 * inch, 2.75 * inch])
    header_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING", (0, 0), (0, 0), 20),
        ("RIGHTPADDING", (-1, 0), (-1, 0), 16),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 16))

    # ── Approved stamp ───────────────────────────────────────────────────
    stamp_data = [[
        Paragraph("FULLY APPROVED", s["approved_stamp"]),
        Paragraph(
            f"All approvals complete — {_fmt_date(fully_approved_date)}",
            ParagraphStyle("stamp_sub", fontSize=9, textColor=GREEN,
                           fontName="Helvetica", leading=13, alignment=TA_CENTER),
        ),
    ]]
    stamp_table = Table(stamp_data, colWidths=[6.75 * inch])
    stamp_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_LITE),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("BOX", (0, 0), (-1, -1), 0.5, GREEN),
        ("ROUNDEDCORNERS", [4]),
    ]))
    story.append(stamp_table)
    story.append(Spacer(1, 20))

    # ── Request details ──────────────────────────────────────────────────
    story.append(Paragraph("REQUEST DETAILS", s["section_head"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=NAVY_LIGHT, spaceAfter=8))

    detail_rows = [
        ("Request type",    workflow_name),
        ("Category",        workflow_category),
        ("Employee",        request_details.get("employee_name", "—")),
        ("Employee no.",    request_details.get("employee_number", "—")),
        ("Initiated by",    request_details.get("initiator_name", "—")),
        ("Submitted",       _fmt_date(request_details.get("submitted_date", ""))),
        ("Effective date",  request_details.get("effective_date", "—") or "—"),
        ("Request ID",      request_id),
    ]
    if request_details.get("notes"):
        detail_rows.append(("Notes", request_details["notes"]))

    story.append(_detail_table(detail_rows, s))
    story.append(Spacer(1, 20))

    # ── Approval chain ───────────────────────────────────────────────────
    story.append(KeepTogether([
        Paragraph("APPROVAL CHAIN", s["section_head"]),
        HRFlowable(width="100%", thickness=0.5, color=NAVY_LIGHT, spaceAfter=8),
        _approver_table(approvals, s),
    ]))
    story.append(Spacer(1, 20))

    # ── Notifications sent ───────────────────────────────────────────────
    if notify_roles:
        story.append(Paragraph("NOTIFICATIONS SENT", s["section_head"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=NAVY_LIGHT, spaceAfter=8))
        notify_data = [[
            Paragraph("Role", s["label"]),
            Paragraph("Action", s["label"]),
        ]]
        for role in notify_roles:
            notify_data.append([
                Paragraph(role, s["value"]),
                Paragraph("FYI notification sent automatically", s["notes"]),
            ])
        nt = Table(notify_data, colWidths=[2.5 * inch, 4.25 * inch])
        nt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY_LIGHT),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
        ]))
        story.append(nt)
        story.append(Spacer(1, 20))

    # ── Footer ───────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=NAVY_LIGHT, spaceBefore=12))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "This document is an automatically generated audit record from the Stream-Flo USA HR Approval System. "
        "It is valid without a physical signature. "
        f"Record ID: {request_id}",
        s["footer"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def build_pdf_filename(
    employee_name: str,
    request_type: str,
    approved_date: str,
) -> str:
    """
    Returns a clean filename like:
    ApprovalRecord_SmithJohn_BackfillBudgeted_20260411.pdf
    """
    def clean(s: str) -> str:
        return "".join(c for c in s.title().replace(" ", "").replace("–", "").replace("/", "") if c.isalnum())

    try:
        dt = datetime.fromisoformat(approved_date.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y%m%d")
    except Exception:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")

    emp = clean(employee_name)[:20]
    req = clean(request_type)[:25]
    return f"ApprovalRecord_{emp}_{req}_{date_str}.pdf"
