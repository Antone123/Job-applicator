"""
Builds a professional PDF resume using ReportLab.
Replicates the clean single-column layout of Antone's original resume.
"""
import os
import sys
from pathlib import Path
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    HRFlowable, Table, TableStyle, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

PAGE_W, PAGE_H = A4
L_MARGIN = R_MARGIN = 20 * mm
T_MARGIN = B_MARGIN = 15 * mm
BODY_WIDTH = PAGE_W - L_MARGIN - R_MARGIN


# ── Styles ─────────────────────────────────────────────────────────────────────

def _styles():
    s = {}

    s["name"] = ParagraphStyle(
        "Name",
        fontName="Helvetica-Bold",
        fontSize=20,
        alignment=TA_CENTER,
        spaceAfter=3,
        textColor=colors.black,
    )
    s["contact"] = ParagraphStyle(
        "Contact",
        fontName="Helvetica",
        fontSize=9,
        alignment=TA_CENTER,
        spaceAfter=6,
        textColor=colors.HexColor("#333333"),
    )
    s["section_header"] = ParagraphStyle(
        "SectionHeader",
        fontName="Helvetica-Bold",
        fontSize=10,
        spaceBefore=10,
        spaceAfter=3,
        textColor=colors.black,
        leading=14,
    )
    s["job_title"] = ParagraphStyle(
        "JobTitle",
        fontName="Helvetica-Bold",
        fontSize=10,
        spaceBefore=6,
        spaceAfter=1,
        leading=13,
    )
    s["company_period"] = ParagraphStyle(
        "CompanyPeriod",
        fontName="Helvetica-Oblique",
        fontSize=9,
        spaceAfter=3,
        leading=12,
        textColor=colors.HexColor("#444444"),
    )
    s["bullet"] = ParagraphStyle(
        "Bullet",
        fontName="Helvetica",
        fontSize=9,
        leftIndent=10,
        firstLineIndent=0,
        spaceAfter=2,
        leading=13,
    )
    s["skill_line"] = ParagraphStyle(
        "SkillLine",
        fontName="Helvetica",
        fontSize=9,
        leftIndent=6,
        spaceAfter=2,
        leading=13,
    )
    s["summary"] = ParagraphStyle(
        "Summary",
        fontName="Helvetica",
        fontSize=9,
        spaceAfter=4,
        leading=14,
        textColor=colors.HexColor("#222222"),
    )
    return s


def _hr(thick=0.8, color=colors.black, space_before=0, space_after=6):
    return HRFlowable(
        width="100%", thickness=thick, color=color,
        spaceBefore=space_before, spaceAfter=space_after
    )


def _section(label: str, st: dict):
    return [
        Paragraph(label.upper(), st["section_header"]),
        _hr(thick=0.5, color=colors.HexColor("#888888"), space_after=5),
    ]


# ── Build ──────────────────────────────────────────────────────────────────────

def build_resume_pdf(profile: dict, tailored: dict, output_path: str) -> str:
    """
    Generate a tailored resume PDF.

    Args:
        profile:      The base profile.json dict
        tailored:     Output from ai_engine.tailor_resume()
        output_path:  Full path to write the PDF

    Returns:
        output_path
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=L_MARGIN,
        rightMargin=R_MARGIN,
        topMargin=T_MARGIN,
        bottomMargin=B_MARGIN,
    )

    st    = _styles()
    story = []
    personal = profile["personal"]

    # ── Header ─────────────────────────────────────────────────────────────────
    story.append(Paragraph(personal["name"], st["name"]))
    contact_parts = [
        personal.get("location", ""),
        personal.get("email", ""),
        personal.get("phone", ""),
    ]
    story.append(Paragraph("  |  ".join(p for p in contact_parts if p), st["contact"]))
    story.append(_hr(thick=1.0, space_after=6))

    # ── Professional Summary ────────────────────────────────────────────────────
    summary = tailored.get("professional_summary", "")
    if summary:
        story += _section("Professional Summary", st)
        story.append(Paragraph(summary, st["summary"]))

    # ── Skills ─────────────────────────────────────────────────────────────────
    story += _section("Skills", st)
    skill_keys = tailored.get("skills_order") or list(profile["skills"].keys())
    labels     = profile.get("skills_labels", {})
    for key in skill_keys:
        skills = profile["skills"].get(key, [])
        if not skills:
            continue
        label     = labels.get(key, key.replace("_", " ").title())
        skill_str = ", ".join(skills)
        story.append(
            Paragraph(f"<b>{label}:</b> {skill_str}", st["skill_line"])
        )

    # ── Professional Experience ─────────────────────────────────────────────────
    story += _section("Professional Experience", st)

    # Build a lookup from tailored experience
    tailored_exp_map = {}
    for exp in tailored.get("experience", []):
        key = (exp["role"].strip(), exp["company"].strip())
        tailored_exp_map[key] = exp

    for orig_exp in profile.get("experience", []):
        key      = (orig_exp["role"].strip(), orig_exp["company"].strip())
        use_exp  = tailored_exp_map.get(key, orig_exp)

        role_line   = use_exp.get("role", orig_exp["role"])
        company     = use_exp.get("company", orig_exp["company"])
        period      = use_exp.get("period", orig_exp.get("period", ""))
        location    = use_exp.get("location", orig_exp.get("location", ""))

        block = [
            Paragraph(role_line, st["job_title"]),
        ]

        # Company (left) + Period (right) in a table row
        company_label = f"<i>{company}</i>"
        period_loc    = f"<i>{period}" + (f", {location}" if location else "") + "</i>"
        cp_table = Table(
            [[Paragraph(company_label, st["company_period"]),
              Paragraph(period_loc, st["company_period"])]],
            colWidths=[BODY_WIDTH * 0.60, BODY_WIDTH * 0.40],
        )
        cp_table.setStyle(TableStyle([
            ("ALIGN",       (0, 0), (0, 0), "LEFT"),
            ("ALIGN",       (1, 0), (1, 0), "RIGHT"),
            ("VALIGN",      (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",  (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        block.append(cp_table)

        for bullet in use_exp.get("bullets", orig_exp.get("bullets", [])):
            block.append(Paragraph(f"\u2022 {bullet}", st["bullet"]))

        block.append(Spacer(1, 4))
        story.append(KeepTogether(block))

    # ── Industry Projects ───────────────────────────────────────────────────────
    story += _section("Industry Projects", st)

    tailored_proj_map = {}
    for proj in tailored.get("projects", []):
        tailored_proj_map[proj["name"].strip()] = proj

    for orig_proj in profile.get("projects", []):
        use_proj = tailored_proj_map.get(orig_proj["name"].strip(), orig_proj)

        proj_name = use_proj.get("name", orig_proj["name"])
        org       = use_proj.get("org", orig_proj.get("org", ""))
        period    = use_proj.get("period", orig_proj.get("period", ""))

        display = proj_name
        if org:
            display += f", {org}"

        block = [Paragraph(f"<i><b>{display}</b></i>", st["job_title"])]
        if period:
            block.append(Paragraph(f"<i>{period}</i>", st["company_period"]))

        for bullet in use_proj.get("bullets", orig_proj.get("bullets", [])):
            block.append(Paragraph(f"\u2022 {bullet}", st["bullet"]))

        block.append(Spacer(1, 4))
        story.append(KeepTogether(block))

    # ── Education ───────────────────────────────────────────────────────────────
    story += _section("Education", st)

    for edu in profile.get("education", []):
        edu_table = Table(
            [[Paragraph(f"<b>{edu['degree']}</b>", st["job_title"]),
              Paragraph(f"<i>{edu.get('period','')}</i>", st["company_period"])]],
            colWidths=[BODY_WIDTH * 0.70, BODY_WIDTH * 0.30],
        )
        edu_table.setStyle(TableStyle([
            ("ALIGN",       (0, 0), (0, 0), "LEFT"),
            ("ALIGN",       (1, 0), (1, 0), "RIGHT"),
            ("VALIGN",      (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",  (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(edu_table)

        details = edu.get("institution", "")
        if edu.get("location"):
            details += f" \u2022 {edu['location']}"
        if edu.get("grade"):
            details += f" \u2022 {edu['grade']}"
        story.append(Paragraph(details, st["skill_line"]))
        story.append(Spacer(1, 4))

    doc.build(story)
    return output_path


def build_cover_letter_pdf(cover_letter_text: str, profile: dict,
                            company: str, job_title: str,
                            output_path: str) -> str:
    """Save the cover letter as a plain, clean PDF."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=L_MARGIN + 5 * mm,
        rightMargin=R_MARGIN + 5 * mm,
        topMargin=T_MARGIN + 5 * mm,
        bottomMargin=B_MARGIN,
    )

    body_style = ParagraphStyle(
        "CLBody",
        fontName="Helvetica",
        fontSize=10,
        leading=16,
        spaceAfter=12,
    )
    header_style = ParagraphStyle(
        "CLHeader",
        fontName="Helvetica-Bold",
        fontSize=11,
        spaceAfter=4,
    )
    date_style = ParagraphStyle(
        "CLDate",
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=20,
    )

    personal = profile.get("personal", {})
    story    = []

    # Sender info
    story.append(Paragraph(personal.get("name", ""), header_style))
    story.append(Paragraph(
        f"{personal.get('email','')}  |  {personal.get('phone','')}  |  {personal.get('location','')}",
        date_style
    ))
    story.append(Paragraph(datetime.now().strftime("%d %B %Y"), date_style))
    story.append(Paragraph(f"Re: {job_title} – {company}", header_style))
    story.append(Spacer(1, 12))

    # Cover letter body – split on double newlines into paragraphs
    for para in cover_letter_text.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(para, body_style))

    doc.build(story)
    return output_path
