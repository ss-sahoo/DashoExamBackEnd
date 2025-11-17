from __future__ import annotations

import os
from io import BytesIO
from typing import Any, Dict, List, Optional

from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import QuestionEvaluation

LOGO_COLOR_HEX = "#094fb5"
LOGO_COLOR = colors.HexColor(LOGO_COLOR_HEX)


def ensure_answer_sheet_pdf(attempt, force_regenerate: bool = False) -> Optional[Dict[str, Any]]:
    """
    Ensure the answer sheet PDF for an attempt exists and return the rendering context.
    """
    context = build_answer_sheet_context(attempt)
    if not context:
        return None

    pdf_missing = (
        not attempt.answer_sheet_pdf
        or not attempt.answer_sheet_pdf.storage.exists(attempt.answer_sheet_pdf.name)
    )

    if force_regenerate or pdf_missing:
        render_answer_sheet_pdf(attempt, context)

    return context


def build_answer_sheet_context(attempt) -> Optional[Dict[str, Any]]:
    evaluations = (
        QuestionEvaluation.objects.filter(attempt=attempt)
        .select_related("question")
        .order_by("question_number")
    )
    if not evaluations.exists():
        return None

    exam = attempt.exam
    institute = exam.institute

    marks_obtained = sum(float(e.marks_obtained or 0) for e in evaluations)
    total_marks_available = sum(float(e.max_marks or 0) for e in evaluations)
    if not total_marks_available:
        total_marks_available = float(exam.total_marks or 0)

    percentage = (
        float(attempt.percentage)
        if attempt.percentage is not None
        else (_safe_divide(marks_obtained, total_marks_available) * 100 if total_marks_available else 0)
    )
    grade, grade_text = _grade_for_percentage(percentage)

    question_breakdown: List[Dict[str, Any]] = []
    for evaluation in evaluations:
        question = evaluation.question
        question_breakdown.append(
            {
                "question_number": evaluation.question_number,
                "question_id": question.id if question else None,
                "question_type": getattr(question, "question_type", None),
                "question_text": getattr(question, "question_text", "Question unavailable"),
                "student_answer": evaluation.student_answer or "Not answered",
                "correct_answer": getattr(question, "correct_answer", "N/A"),
                "marks_obtained": float(evaluation.marks_obtained or 0),
                "max_marks": float(evaluation.max_marks or 0),
                "is_correct": evaluation.is_correct,
                "evaluation_notes": evaluation.evaluation_notes
                or evaluation.manual_feedback
                or evaluation.ai_feedback
                or "",
            }
        )

    branding = _build_branding_info(institute)

    return {
        "exam": {
            "id": exam.id,
            "title": exam.title,
            "description": exam.description or "",
            "total_marks": total_marks_available,
            "duration_minutes": exam.duration_minutes,
        },
        "student": {
            "id": attempt.student.id,
            "name": attempt.student.get_full_name(),
            "email": attempt.student.email,
        },
        "attempt": {
            "id": attempt.id,
            "number": attempt.attempt_number,
            "submitted_at": attempt.submitted_at,
            "time_spent_seconds": attempt.time_spent,
            "status": attempt.status,
        },
        "question_breakdown": question_breakdown,
        "branding": branding,
        "grading": {
            "percentage": round(percentage, 2) if percentage is not None else None,
            "marks_obtained": marks_obtained,
            "total_marks": total_marks_available,
            "grade": grade,
            "remarks": grade_text,
        },
        "invigilator_placeholders": [
            {"label": "Invigilator Name", "value": ""},
            {"label": "Invigilator Signature", "value": ""},
            {"label": "Date", "value": ""},
        ],
        "generated_on": timezone.now(),
    }


def render_answer_sheet_pdf(attempt, context: Dict[str, Any]) -> None:
    buffer = BytesIO()
    # Widen the page, but still good for A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=32,
        rightMargin=32,
        topMargin=40,
        bottomMargin=34,
    )

    styles = getSampleStyleSheet()
    full_width = 7.3 * inch
    # Card backgrounds and border/shadow color
    CARD_BG = colors.HexColor('#f9fbfd')
    Q_BOX_BG = colors.HexColor('#f3f7fc')
    ANS_CORRECT = colors.HexColor('#e3fee3')
    ANS_WRONG = colors.HexColor('#ffeaea')
    CORR_ANS_BG = colors.HexColor('#e4f1ff')
    EXPL_BG = colors.HexColor('#fbfbf2')
    BORDER_COLOR = colors.HexColor('#e3eaf2')
    SHADOW_COLOR = colors.HexColor('#f1f1f5')
    # Enhanced styles
    header_title = ParagraphStyle("HeaderTitle", parent=styles["Heading1"], fontSize=22, leading=28, textColor=LOGO_COLOR, alignment=0, spaceAfter=0, spaceBefore=0,)
    bold_big = ParagraphStyle("BoldBig", parent=styles["Heading2"], fontSize=14, leading=19, spaceAfter=3, textColor=colors.HexColor("#212133"), alignment=0)
    muted = ParagraphStyle("Muted", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#757575"), alignment=0)
    stat_label = ParagraphStyle("StatLabel", parent=styles["Normal"], fontSize=8.0, textColor=colors.HexColor("#b1b1c5"),)
    stat_value = ParagraphStyle("StatValue", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#1c2558"),)
    summary_card_label = ParagraphStyle("SummaryCardLabel", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#8fa0b2"), alignment=0, spaceAfter=2)
    summary_card_value = ParagraphStyle("SummaryCardValue", parent=styles["Normal"], fontSize=17, leading=18, alignment=0, textColor=LOGO_COLOR, spaceAfter=1)
    block_head = ParagraphStyle("BlockHead", parent=styles["Heading3"], fontSize=13, leading=22, spaceAfter=6, textColor=LOGO_COLOR, alignment=0)
    question_label = ParagraphStyle("QuestionNum", parent=styles["Normal"], fontSize=10.6, textColor=LOGO_COLOR, spaceAfter=2, spaceBefore=12, alignment=0, leftIndent=0)
    question_type_style = ParagraphStyle("TypeLabel", parent=styles["Heading3"], fontSize=11, textColor=colors.black, spaceAfter=5, spaceBefore=0, alignment=0, leftIndent=0)
    q_text_style = ParagraphStyle("QTextStyle", parent=styles["Normal"], fontSize=11.4, spaceBefore=0, spaceAfter=10, textColor=colors.HexColor('#202e3d'), leftIndent=3, rightIndent=3)
    ans_label = ParagraphStyle("AnsLabel", parent=styles["Normal"], fontSize=9.5, textColor=colors.HexColor('#62840e'), spaceAfter=1)
    ans_style = ParagraphStyle("AnsStyle", parent=styles["Normal"], fontSize=12, textColor=colors.HexColor('#115523'), spaceAfter=2, leftIndent=2)
    wrong_label = ParagraphStyle("WrongLabel", parent=styles["Normal"], fontSize=9, textColor=colors.red)
    wrong_style = ParagraphStyle("WrongStyle", parent=styles["Normal"], fontSize=12, textColor=colors.red, spaceAfter=2, leftIndent=2)
    correct_label = ParagraphStyle("CorrectLabel", parent=styles["Normal"], fontSize=9.5, textColor=colors.green)
    pill_correct = ParagraphStyle("PillCorrect", parent=styles["Normal"], fontSize=9, textColor=colors.green, alignment=1, backColor=ANS_CORRECT, borderPadding=(6,2,6,2))
    pill_wrong = ParagraphStyle("PillWrong", parent=styles["Normal"], fontSize=9, textColor=colors.red, alignment=1, backColor=ANS_WRONG, borderPadding=(6,2,6,2))
    marks_right = ParagraphStyle("MarksRight", parent=styles["Heading4"], fontSize=10.9, textColor=LOGO_COLOR, alignment=2, leftIndent=0)
    expl_label = ParagraphStyle("ExplanationLabel", parent=styles["Normal"], fontSize=9.9, textColor=colors.HexColor('#6d6d6d'))
    expl_body = ParagraphStyle("ExplBody", parent=styles["Normal"], fontSize=11, leading=13, textColor=colors.HexColor('#353535'))

    story = []
    exam = context["exam"]
    student = context["student"]
    attempt_dict = context["attempt"]
    grading = context["grading"]

    # --- HEADER ---
    # Wider columns for left/right
    header_block = [
        [
            Paragraph(f"<b>{exam['title']}</b>", header_title),
            Paragraph(f"<b>{student['name']}</b><br/><font size=8 color='#146'>{student['email']}<br/>{attempt_dict['submitted_at'].strftime('%d/%m/%Y, %H:%M') if attempt_dict['submitted_at'] else ''}</font>", marks_right)
        ],
        [
            Paragraph(f"Attempt #{attempt_dict['id']}", muted),
            ''
        ],
    ]
    story.append(Table(header_block, colWidths=[4.0*inch, full_width-4.0*inch], style=TableStyle([
        ("SPAN", (1,0), (1,1)),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0)
    ])))
    story.append(Spacer(1, 12))

    # Meta stats block, fullwidth, larger cells
    meta_grid = [
        [Paragraph("INSTITUTE STATUS", stat_label), Paragraph("TOTAL MARKS", stat_label), Paragraph("DURATION", stat_label)],
        [Paragraph(f"<b>{attempt_dict['status'].upper()}</b>", stat_value), Paragraph(f"{exam['total_marks']}", stat_value), Paragraph(f"{exam['duration_minutes']} min", stat_value)]
    ]
    story.append(Table(meta_grid, colWidths=[2.25*inch,2.0*inch,2.15*inch], style=TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), CARD_BG),
        ("FONTNAME", (0,1), (-1,1), "Helvetica-Bold"),
        ("FONTSIZE", (0,1), (-1,1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("LINEBELOW", (0,0), (-1,0), 0.7, BORDER_COLOR),
        ("GRID", (0,0), (-1,1), 0.05, CARD_BG),
        ("BOX", (0,0), (-1,-1), 0.6, BORDER_COLOR),
        ("LEFTPADDING", (0,0), (-1,-1), 15),
        ("RIGHTPADDING", (0,0), (-1,-1), 13)
    ])))
    story.append(Spacer(1, 22))

    # Summary Cards
    cards_data = [
      [
          Paragraph("SCORE", summary_card_label),
          Paragraph("ACCURACY", summary_card_label),
          Paragraph("VIOLATIONS", summary_card_label),
          Paragraph("SECTIONS GRADED", summary_card_label)
      ],
      [
          Paragraph(f"<b>{grading['marks_obtained']} / {grading['total_marks']}</b>", summary_card_value),
          Paragraph(f"<b>{grading.get('percentage',0):.1f}%</b>", summary_card_value),
          Paragraph(f"<b>{attempt_dict.get('violations', 0)}</b>", summary_card_value),
          Paragraph(f"<b>{context.get('sections_graded', '') or ''}</b>", summary_card_value),
      ]
    ]
    story.append(Table(cards_data, colWidths=[full_width/4]*4, style=TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ("LEFTPADDING", (0,0), (-1,-1), 18),
        ("RIGHTPADDING", (0,0), (-1,-1), 18),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 11),
        ("LINEBELOW", (0,0), (-1,0), 0.55, BORDER_COLOR),
        ("BOX", (0,1), (-1,1), 0.45, BORDER_COLOR),
        ("BACKGROUND", (0,1), (-1,1), CARD_BG),
        ("FONTSIZE", (0,0), (-1,0), 9.3),
        ("FONTSIZE", (0,1), (-1,1), 18),
    ])))
    story.append(Spacer(1, 25))

    # Section: Detailed responses
    story.append(Paragraph("Detailed Responses", block_head))
    story.append(Spacer(1, 9))

    # Each Question Block
    for q in context['question_breakdown']:
        student_correct = q.get("is_correct", False)
        q_block = []
        # Q# and type
        q_block.append(Paragraph(f"QUESTION {q['question_number']}", question_label))
        q_block.append(Paragraph(f"<b>{str(q.get('question_type','')).upper()}</b>", question_type_style))
        # Question text as wide card
        q_block.append(
            Table([[Paragraph(q["question_text"], q_text_style)]], colWidths=[full_width-20],
                  style=TableStyle([
                      ("BACKGROUND", (0,0), (-1,-1), Q_BOX_BG),
                      ("BOX", (0,0), (-1,-1), 1.2, BORDER_COLOR),
                      ("LEFTPADDING", (0,0), (-1,-1), 22),
                      ("RIGHTPADDING", (0,0), (-1,-1), 22),
                      ("TOPPADDING", (0,0), (-1,-1), 15),
                      ("BOTTOMPADDING", (0,0), (-1,-1), 14),
                  ]))
        )
        q_block.append(Spacer(1,5))
        # Student/Correct answer side-by-side
        stud_ans_bg = ANS_CORRECT if student_correct else ANS_WRONG
        ans_badge = Paragraph("Correct", pill_correct) if student_correct else Paragraph("Incorrect", pill_wrong)
        # The mark pill
        mark_val = f"Marks {q['marks_obtained']} / {q['max_marks']}"
        mark_pill = Paragraph(mark_val, marks_right)
        q_block.append(
            Table([
                [
                    Paragraph("STUDENT ANSWER", ans_label if student_correct else wrong_label),
                    Paragraph("CORRECT ANSWER", ans_label),
                    mark_pill,
                    ans_badge
                ],
                [
                    Paragraph(q["student_answer"], ans_style if student_correct else wrong_style),
                    Paragraph(q["correct_answer"], ans_style),
                    '',
                    ''
                ]
            ],
            colWidths=[(full_width-60)/2,(full_width-60)/2, 1.09*inch, 1.09*inch],
            style=TableStyle([
                ("BACKGROUND", (0,0), (0,1), stud_ans_bg),
                ("BACKGROUND", (1,0), (1,1), CORR_ANS_BG),
                ("BOX", (0,0), (-1,1), 1.1, BORDER_COLOR),
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("ALIGN", (2,0), (3,0), "RIGHT"),
                ("ALIGN", (2,1), (3,1), "RIGHT"),
                ("SPAN", (0,0), (0,0)), ("SPAN", (1,0), (1,0)),
                ("SPAN", (2,0), (2,0)), ("SPAN", (3,0), (3,0)),
                ("TOPPADDING", (0,0), (3,0), 10),
                ("TOPPADDING", (0,1), (3,1), 7),
                ("BOTTOMPADDING", (0,1), (3,1), 13),
                ("FONTSIZE", (0,0), (-1,-1), 11),
                ("LEFTPADDING", (0,0), (-1,-1), 20),
                ("RIGHTPADDING", (0,0), (-1,-1), 20),
            ]))
        )
        q_block.append(Spacer(1, 5))
        # Explanation
        if q.get("evaluation_notes"):
            q_block.append(
                Table(
                    [[Paragraph("EXPLANATION", expl_label), Paragraph(q["evaluation_notes"], expl_body)]],
                    colWidths=[1.2*inch, full_width-36-1.2*inch],
                    style=TableStyle([
                        ("BACKGROUND", (0,0), (-1,-1), EXPL_BG),
                        ("BOX", (0,0), (-1,-1), 1.1, BORDER_COLOR),
                        ("LEFTPADDING", (0,0), (-1,-1), 15),
                        ("RIGHTPADDING", (0,0), (-1,-1), 15),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 11),
                        ("TOPPADDING", (0,0), (-1,-1), 11),
                        ("FONTSIZE", (0,0), (-1,-1), 10),
                    ]),
                )
            )
        q_block.append(Spacer(1,27)) # Large space after Q block
        story.extend(q_block)
    # FINISH ---
    doc.build(story)
    exam = context["exam"]
    attempt_dict = context["attempt"]
    filename = f"answer_sheet_exam_{exam['id']}_attempt_{attempt_dict['id']}_{timezone.now().strftime('%Y%m%d%H%M%S')}.pdf"
    attempt.answer_sheet_pdf.save(filename, ContentFile(buffer.getvalue()), save=False)
    attempt.answer_sheet_generated_at = timezone.now()
    attempt.save(update_fields=["answer_sheet_pdf", "answer_sheet_generated_at"])


def _build_branding_info(institute) -> Dict[str, Optional[str]]:
    logo_path = None
    logo_url = None
    if getattr(institute, "logo", None):
        try:
            if institute.logo and institute.logo.name:
                if institute.logo.storage.exists(institute.logo.name):
                    logo_path = institute.logo.path
                    logo_url = institute.logo.url
        except (ValueError, OSError):
            logo_path = None
            logo_url = None

    return {
        "institute_logo_path": logo_path,
        "institute_logo_url": logo_url,
        "primary_hex": LOGO_COLOR_HEX,
    }


def _build_branding_table(context: Dict[str, Any], label_style, styles) -> Table:
    institute_block = Paragraph(
        (
            f"<b>{escape(context['exam']['title'])}</b><br/>"
            f"Student: {escape(context['student']['name'])}<br/>"
            f"Email: {escape(context['student']['email'])}"
        ),
        styles["Normal"],
    )

    attempt = context["attempt"]
    attempt_block = Paragraph(
        (
            f"Attempt #{attempt['number']}<br/>"
            f"Status: {attempt['status'].title()}<br/>"
            f"Submitted: {attempt['submitted_at'].strftime('%Y-%m-%d %H:%M') if attempt['submitted_at'] else 'N/A'}"
        ),
        styles["Normal"],
    )

    d_logo_para = Paragraph(
        f'<para align="center"><font color="{LOGO_COLOR_HEX}" size="32"><b>D</b></font></para>',
        styles["Normal"],
    )
    d_logo_table = Table([[d_logo_para]], colWidths=[0.8 * inch], rowHeights=[0.8 * inch])
    d_logo_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 2, LOGO_COLOR),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )

    header_table = Table(
        [[d_logo_table, institute_block, attempt_block]],
        colWidths=[1.0 * inch, 3.0 * inch, 2.4 * inch],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBEFORE", (2, 0), (2, 0), 0.25, colors.lightgrey),
            ]
        )
    )
    return header_table


def _build_summary_table(context: Dict[str, Any], styles) -> Table:
    attempt = context["attempt"]
    exam = context["exam"]
    data = [
        ["Exam Duration", f"{exam['duration_minutes']} mins"],
        ["Time Spent", f"{_seconds_to_minutes(attempt['time_spent_seconds'])} mins"],
        ["Total Questions", len(context["question_breakdown"])],
        ["Generated On", context["generated_on"].strftime("%Y-%m-%d %H:%M")],
    ]
    table = Table(data, colWidths=[2.2 * inch, 4.2 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    return table


def _build_grading_table(context: Dict[str, Any], styles) -> Table:
    grading = context["grading"]
    data = [
        ["Score", f"{grading['marks_obtained']} / {grading['total_marks']}"],
        ["Percentage", f"{grading['percentage']:.2f}%"],
        ["Grade", grading["grade"]],
        ["Remarks", grading["remarks"]],
    ]
    table = Table(data, colWidths=[1.6 * inch, 4.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), LOGO_COLOR),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]
        )
    )
    return table


def _build_signature_table(context: Dict[str, Any], styles) -> Table:
    placeholders = context["invigilator_placeholders"]
    data = []
    for placeholder in placeholders:
        data.append([placeholder["label"], "____________________________"])
    table = Table(data, colWidths=[2.2 * inch, 4.2 * inch])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    safe_text = escape(text or "").replace("\n", "<br/>")
    return Paragraph(safe_text, style)


def _seconds_to_minutes(value: Optional[int]) -> str:
    if not value:
        return "0"
    return f"{round(value / 60, 2)}"


def _safe_divide(a: float, b: float) -> float:
    if not b:
        return 0.0
    return a / b


def _grade_for_percentage(percentage: Optional[float]) -> (str, str):
    if percentage is None:
        return "N/A", "Score unavailable"
    if percentage >= 90:
        return "A+", "Outstanding performance"
    if percentage >= 80:
        return "A", "Excellent grasp of the material"
    if percentage >= 70:
        return "B+", "Very good effort"
    if percentage >= 60:
        return "B", "Good performance"
    if percentage >= 50:
        return "C", "Satisfactory but improvement needed"
    return "F", "Below expectations - review required"

