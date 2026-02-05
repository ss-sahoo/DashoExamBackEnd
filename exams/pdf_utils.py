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
                    # For S3/DO Spaces, .path is not available. 
                    # ReportLab Image can take a URL or we can omit path.
                    # We'll rely on logo_url which can be a full S3 URL.
                    try:
                        logo_path = institute.logo.path
                    except (NotImplementedError, AttributeError):
                        logo_path = None
                    logo_url = institute.logo.url
        except Exception:
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


def generate_question_paper_pdf(exam) -> BytesIO:
    """
    Generate a board-exam style PDF for an exam.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    
    # Board Exam Style - B&W, Serif if possible, otherwise clean Sans
    board_header = ParagraphStyle("BoardHeader", parent=styles["Heading1"], fontSize=16, alignment=1, spaceAfter=6, fontName="Helvetica-Bold")
    board_sub_header = ParagraphStyle("BoardSubHeader", parent=styles["Heading2"], fontSize=12, alignment=1, spaceAfter=12, fontName="Helvetica")
    board_instruction = ParagraphStyle("BoardInstruction", parent=styles["Normal"], fontSize=10, alignment=0, spaceAfter=10, fontName="Helvetica-Oblique")
    board_section = ParagraphStyle("BoardSection", parent=styles["Heading3"], fontSize=12, alignment=1, spaceBefore=15, spaceAfter=8, fontName="Helvetica-Bold", borderPadding=3, borderWidth=1, borderColor=colors.black)
    board_question = ParagraphStyle("BoardQuestion", parent=styles["Normal"], fontSize=11, leading=14, spaceBefore=10, fontName="Helvetica")
    board_option = ParagraphStyle("BoardOption", parent=styles["Normal"], fontSize=10, leftIndent=20, leading=14, fontName="Helvetica")
    board_marks = ParagraphStyle("BoardMarks", parent=styles["Normal"], fontSize=10, alignment=2, fontName="Helvetica-Bold")
    
    # Table-specific styles (no indentation to prevent layout errors)
    board_table_text = ParagraphStyle("BoardTableText", parent=styles["Normal"], fontSize=10, leftIndent=0, leading=14, fontName="Helvetica")
    board_table_label = ParagraphStyle("BoardTableLabel", parent=styles["Normal"], fontSize=10, leftIndent=0, leading=14, fontName="Helvetica-Bold")

    # Helper function to sanitize text for PDF rendering
    def sanitize_pdf_text(text):
        """Clean text so it can be rendered in ReportLab Paragraphs."""
        if text is None:
            return ""
        # Convert to string and strip null bytes
        text = str(text).replace('\x00', '').strip()
        if not text:
            return " "
            
        import html
        import re
        
        # 1. First, unescape any existing HTML entities to avoid double escaping
        text = html.unescape(text)
        
        # 2. Clean up common LaTeX "text" wrappers which cause brace confusion
        # Handle \text{...} or \mathrm{...}
        text = re.sub(r'\\(?:text|mathrm|mathbf|mathit)\{([^}]*)\}', r'\1', text)
        
        # 3. Convert common LaTeX symbols to Unicode equivalents
        symbols = {
            '\\circ': '°', '\\times': '×', '\\div': '÷',
            '\\alpha': 'α', '\\beta': 'β', '\\gamma': 'γ', '\\delta': 'δ',
            '\\lambda': 'λ', '\\pi': 'π', '\\sigma': 'σ', '\\omega': 'ω',
            '\\theta': 'θ', '\\pm': '±', '\\neq': '≠', '\\approx': '≈',
            '\\geq': '≥', '\\leq': '≤', '\\infty': '∞', '\\to': '→',
            '\\rightarrow': '→', '\\leftrightarrow': '↔', '\\Rightarrow': '⇒',
        }
        for lat, sym in symbols.items():
            text = text.replace(lat, sym)
            
        # 4. Handle braced subscripts/superscripts (INNERMOST FIRST)
        # Use a loop to handle nested cases like _{X^{2+}}
        for _ in range(5):  # Max 5 levels of nesting
            # Match only innermost groups (containing no other { or })
            new_text = re.sub(r'\_\{([^{}]*)\}', r'<sub>\1</sub>', text)
            new_text = re.sub(r'\^\{([^{}]*)\}', r'<sup>\1</sup>', new_text)
            if new_text == text:
                break
            text = new_text
            
        # 5. Handle single-character subscripts/superscripts
        # Only if NOT followed by { (already handled) and NOT part of an existing tag
        # Use a more constrained char set to avoid matching part of tags like <sub>
        text = re.sub(r'(?<![a-zA-Z0-9])\_([a-zA-Z0-9°α-ωΑ-Ω])', r'<sub>\1</sub>', text)
        text = re.sub(r'(?<![a-zA-Z0-9])\^([a-zA-Z0-9°α-ωΑ-Ω])', r'<sup>\1</sup>', text)
        # Fallback for simple cases like H_2O (no word boundary needed)
        text = re.sub(r'([a-zA-Z])\_([0-9])', r'\1<sub>\2</sub>', text)
        text = re.sub(r'([a-zA-Z])\^([0-9])', r'\1<sup>\2</sup>', text)

        # 6. Remove remaining $ delimiters
        text = text.replace('$', '')
        
        # 7. XML Escaping for ReportLab (must come AFTER conversions but BEFORE restoring tags)
        from xml.sax.saxutils import escape as xml_escape
        text = xml_escape(text)
        
        # 8. Unescape allowed ReportLab tags
        text = text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
        text = text.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
        text = text.replace('&lt;u&gt;', '<u>').replace('&lt;/u&gt;', '</u>')
        text = text.replace('&lt;br/&gt;', '<br/>').replace('&lt;br&gt;', '<br/>')
        text = text.replace('&lt;sub&gt;', '<sub>').replace('&lt;/sub&gt;', '</sub>')
        text = text.replace('&lt;sup&gt;', '<sup>').replace('&lt;/sup&gt;', '</sup>')
        
        # Limit length to prevent memory issues
        if len(text) > 10000:
            text = text[:10000] + '...'
        return text

    def to_roman(n):
        """Convert integer to lowercase roman numeral."""
        try:
            n = int(n)
            romans = {1: 'i', 2: 'ii', 3: 'iii', 4: 'iv', 5: 'v', 6: 'vi', 7: 'vii', 8: 'viii', 9: 'ix', 10: 'x'}
            return romans.get(n, str(n))
        except:
            return str(n)

    story = []

    # 1. Header Information
    institute = exam.institute
    story.append(Paragraph(f"<b>{institute.name.upper()}</b>", board_header))
    story.append(Paragraph(f"<b>{exam.title.upper()}</b>", board_sub_header))
    
    info_table_data = [
        [f"Time Allowed: {exam.duration_minutes} Minutes", f"Maximum Marks: {exam.total_marks}"]
    ]
    info_table = Table(info_table_data, colWidths=[3.25 * inch, 3.25 * inch])
    info_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (0,0), 'LEFT'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('LINEBELOW', (0,0), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 15))

    # 2. General Instructions
    story.append(Paragraph("<b>GENERAL INSTRUCTIONS:</b>", board_instruction))
    instructions = [
        "1. All questions are compulsory.",
        "2. The question paper consists of multiple sections as defined below.",
        "3. Read each question carefully before attempting.",
        "4. Marks for each question are indicated against it."
    ]
    for instr in instructions:
        story.append(Paragraph(instr, board_instruction))
    story.append(Spacer(1, 15))

    # 3. Questions by Section
    sections = exam.pattern.sections.all().order_by('order', 'start_question')
    
    # Get all active questions for the exam
    questions = exam.questions.filter(is_active=True).order_by('question_number')
    
    for section in sections:
        story.append(Paragraph(sanitize_pdf_text(f"SECTION - {section.name.upper()} ({section.subject})"), board_section))
        story.append(Paragraph(sanitize_pdf_text(f"<i>(This section consists of questions {section.start_question} to {section.end_question}. Each question carries {section.marks_per_question} marks.)</i>"), board_instruction))
        
        section_questions = questions.filter(
            question_number__gte=section.start_question,
            question_number__lte=section.end_question
        )
        
        # 3. Questions by Section
        for q in section_questions:
            # Check for pattern-level question configuration (internal choices, nested parts)
            # The config is keyed by the pattern-relative question number (1,2,3 within section)
            pattern_q_num = getattr(q, 'question_number_in_pattern', None) or q.question_number
            q_config = section.question_configurations.get(str(pattern_q_num))
            # Fallback: also try the absolute question number (for compatibility)
            if not q_config:
                q_config = section.question_configurations.get(str(q.question_number))
            
            # Get saved question structure (contains the actual content)
            q_structure = getattr(q, 'structure', None) or {}
            saved_parts = q_structure.get('parts', []) or q_structure.get('nested_parts', [])
            
            # Debug: Log saved structure for troubleshooting
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"PDF Gen Q{q.question_number}: q_config={bool(q_config)}, is_nested={q_config.get('is_nested') if q_config else False}")
            logger.info(f"PDF Gen Q{q.question_number}: q_structure keys={list(q_structure.keys())}, saved_parts count={len(saved_parts)}")
            if saved_parts:
                logger.info(f"PDF Gen Q{q.question_number}: saved_parts[0]={saved_parts[0] if saved_parts else 'none'}")
            
            if q_config and q_config.get('is_nested'):
                # Handle Nested / Internal Choice Question
                nested_type = q_config.get('nested_type')
                options = q_config.get('options', [])
                
                # Render the main question text first
                q_text = f"Q.{q.question_number}  {q.question_text}"
                story.append(Table([[Paragraph(sanitize_pdf_text(q_text), board_question), Paragraph(sanitize_pdf_text(f"[{section.marks_per_question}]"), board_marks)]], colWidths=[5.8 * inch, 0.7 * inch], style=TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 0), ('RIGHTPADDING', (0,0), (-1,-1), 0)])))
                
                # Helper to find saved content for a part (by label or index fallback)
                def find_saved_part(label, saved_list, index=None):
                    if not saved_list: return None
                    label_str = str(label).lower().strip()
                    # Only match by label if label is non-empty to avoid false positives on empty labels
                    if label_str:
                        for sp in saved_list:
                            if str(sp.get('label', '')).lower().strip() == label_str:
                                return sp
                    # Fallback to index if labels don't match OR label is empty
                    if index is not None and index < len(saved_list):
                        return saved_list[index]
                    return None
                
                # Render options (Parts / Choices) - prioritize saved parts count
                render_options_list = saved_parts if len(saved_parts) > len(options) else options
                for i, opt in enumerate(render_options_list):
                    opt_type = opt.get('type', 'part')
                    
                    if i > 0 and nested_type == 'internal_choice':
                        story.append(Paragraph("<b>OR</b>", ParagraphStyle("OrStyle", parent=board_question, alignment=1, spaceBefore=4, spaceAfter=4)))
                    
                    # Handle choice_group type (internal OR within a part like c)
                    if opt_type == 'choice_group':
                        # Find saved choice_group data
                        opt_label = str(opt.get('label', ''))
                        saved_choice_group = find_saved_part(opt_label, saved_parts)
                        saved_choice_options = []
                        if saved_choice_group:
                            saved_choice_options = saved_choice_group.get('options', [])
                            
                        config_choice_options = opt.get('options', [])
                        # Ensure we don't miss any choices the user added
                        choices_to_render = saved_choice_options if len(saved_choice_options) > len(config_choice_options) else config_choice_options
                        
                        for ci, choice in enumerate(choices_to_render):
                            if ci > 0:
                                story.append(Paragraph("<b>OR</b>", ParagraphStyle("OrStyle2", parent=board_question, alignment=1, spaceBefore=3, spaceAfter=3)))
                            
                            choice_label = str(choice.get('label', ''))
                            # Find saved content for this choice
                            saved_choice = find_saved_part(choice_label, saved_choice_options, ci)
                            choice_text = ''
                            if saved_choice:
                                choice_text = saved_choice.get('question_text', saved_choice.get('text', ''))
                            if not choice_text:
                                choice_text = choice.get('text', choice.get('description', ''))
                            
                            choice_marks_val = choice.get('marks')
                            choice_marks = f"[{choice_marks_val}]" if choice_marks_val else ""
                            
                            if choice_label and not (choice_label.startswith('(') and choice_label.endswith(')')):
                                full_choice_label = f"({choice_label})"
                            else:
                                full_choice_label = choice_label
                            
                            full_choice_text = f"<b>{full_choice_label}</b>"
                            if choice_text:
                                full_choice_text += f" {choice_text}"
                            
                            choice_table = Table([
                                [Paragraph(sanitize_pdf_text(full_choice_text), board_table_text), Paragraph(sanitize_pdf_text(choice_marks), board_marks)]
                            ], colWidths=[5.8*inch, 0.7*inch], style=TableStyle([
                                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                                ('LEFTPADDING', (0,0), (-1,-1), 0),
                                ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                            ]))
                            story.append(choice_table)
                            
                            # Handle choice_group sub-parts if they exist - prioritize saved count
                            config_choice_sub_parts = choice.get('sub_parts', []) or choice.get('parts', [])
                            saved_choice_sub_parts = []
                            if saved_choice:
                                saved_choice_sub_parts = saved_choice.get('sub_parts', []) or saved_choice.get('parts', [])
                            
                            # Ensure we render all sub-parts if user added more
                            render_csubs = saved_choice_sub_parts if len(saved_choice_sub_parts) > len(config_choice_sub_parts) else config_choice_sub_parts
                            
                            # Check if we should use Roman numerals (i, ii) vs (1, 2)
                            # Favor Roman if pattern suggests it or if it's a numeric sub-part
                            use_roman_labels = any(str(p.get('label', '')).lower() in ['i', 'ii', 'iii', 'iv'] for p in config_choice_sub_parts)
                            if not use_roman_labels and len(render_csubs) > 0:
                                # Default to Roman for sub-parts if they are digit-based
                                use_roman_labels = True
                            
                            for csi, csub in enumerate(render_csubs):
                                csub_label = str(csub.get('label', ''))
                                # If label is a digit, convert to Roman
                                if csub_label.isdigit():
                                    csub_label = to_roman(int(csub_label))
                                elif not csub_label:
                                    csub_label = to_roman(csi + 1)
                                    
                                saved_csub = find_saved_part(csub_label, saved_choice_sub_parts, csi)
                                csub_text = ''
                                if saved_csub:
                                    csub_text = saved_csub.get('question_text', saved_csub.get('text', ''))
                                if not csub_text:
                                    csub_text = csub.get('text', csub.get('description', ''))
                                if not csub_text:
                                    csub_text = '...........................................................................'
                                
                                csub_marks_val = csub.get('marks')
                                csub_marks = f"[{csub_marks_val}]" if csub_marks_val else ""
                                
                                if csub_label and not (csub_label.startswith('(') and csub_label.endswith(')')):
                                    full_csub_label = f"({csub_label})"
                                else:
                                    full_csub_label = csub_label
                                
                                csub_table = Table([
                                    [Paragraph(sanitize_pdf_text(full_csub_label), board_table_label), Paragraph(sanitize_pdf_text(csub_text), board_table_text), Paragraph(sanitize_pdf_text(csub_marks), board_marks)]
                                ], colWidths=[0.8*inch, 5.0*inch, 0.7*inch], style=TableStyle([
                                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                                    ('LEFTPADDING', (0,0), (-1,-1), 0),
                                ]))
                                story.append(csub_table)
                        continue  # Skip the normal option rendering for choice_groups
                    
                    # Get saved content for this part
                    opt_label = str(opt.get('label', ''))
                    saved_opt = find_saved_part(opt_label, saved_parts, i)
                    
                    # Use saved question_text if available, fallback to config text/description
                    opt_text = ''
                    if saved_opt:
                        opt_text = saved_opt.get('question_text', saved_opt.get('text', ''))
                    if not opt_text:
                        opt_text = opt.get('text', opt.get('description', ''))
                    
                    opt_marks_val = opt.get('marks')
                    opt_marks = f"[{opt_marks_val}]" if opt_marks_val is not None and str(opt_marks_val).strip() != "" else ""
                    
                    # Ensure label is wrapped in parens if not already
                    if opt_label and not (opt_label.startswith('(') and opt_label.endswith(')')):
                        full_opt_label = f"({opt_label})"
                    else:
                        full_opt_label = opt_label

                    full_opt_text = f"<b>{full_opt_label}</b>"
                    if opt_text:
                        full_opt_text += f" {opt_text}"
                    
                    # Render Part (a, b, c) or Choice with marks on right
                    p_table = Table([
                        [Paragraph(sanitize_pdf_text(full_opt_text), board_table_text), Paragraph(sanitize_pdf_text(opt_marks), board_marks)]
                    ], colWidths=[5.8*inch, 0.7*inch], style=TableStyle([
                        ('VALIGN', (0,0), (-1,-1), 'TOP'),
                        ('LEFTPADDING', (0,0), (-1,-1), 0),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                    ]))
                    story.append(p_table)
                    
                    config_sub_parts = opt.get('parts', []) or opt.get('sub_parts', [])
                    saved_sub_parts = []
                    if saved_opt:
                        saved_sub_parts = saved_opt.get('sub_parts', []) or saved_opt.get('parts', [])
                    
                    # Ensure we render all sub-parts if user added more during extraction
                    render_sub_list = saved_sub_parts if len(saved_sub_parts) > len(config_sub_parts) else config_sub_parts

                    # Check if we should use Roman numerals
                    # Favor Roman for sub-parts (Level 3 nesting)
                    use_roman_sub = any(str(p.get('label', '')).lower() in ['i', 'ii', 'iii', 'iv'] for p in config_sub_parts)
                    if not use_roman_sub and len(render_sub_list) > 0:
                        use_roman_sub = True

                    for j, part in enumerate(render_sub_list):
                        p_label = str(part.get('label', ''))
                        
                        # Convert digit labels to Roman
                        if p_label.isdigit():
                            p_label = to_roman(int(p_label))
                        elif not p_label:
                            p_label = to_roman(j + 1)

                        # Find saved content for this sub-part (try label then index fallback)
                        saved_sub = find_saved_part(p_label, saved_sub_parts, j)
                        p_text = ''
                        if saved_sub:
                            p_text = saved_sub.get('question_text', saved_sub.get('text', ''))
                        if not p_text:
                            p_text = part.get('text', part.get('description', ''))
                        if not p_text:
                            p_text = '...........................................................................'
                        
                        part_marks_val = part.get('marks')
                        p_marks = f"[{part_marks_val}]" if part_marks_val is not None and str(part_marks_val).strip() != "" else ""
                        
                        # Ensure sub-label is wrapped in parens
                        if p_label and not (p_label.startswith('(') and p_label.endswith(')')):
                            full_p_label = f"({p_label})"
                        else:
                            full_p_label = p_label

                        # Extra indentation for sub-parts (i, ii) using first column width instead of padding
                        sub_p_table = Table([
                            [Paragraph(sanitize_pdf_text(full_p_label), board_table_label), Paragraph(sanitize_pdf_text(p_text), board_table_text), Paragraph(sanitize_pdf_text(p_marks), board_marks)]
                        ], colWidths=[0.8*inch, 5.0*inch, 0.7*inch], style=TableStyle([
                            ('VALIGN', (0,0), (-1,-1), 'TOP'),
                            ('LEFTPADDING', (0,0), (-1,-1), 0),
                        ]))
                        story.append(sub_p_table)
                
                # Global Sub-questions (i, ii, iii) - Only render from config to avoid duplication in nested questions
                sub_questions = q_config.get('sub_questions', [])
                for si, sub_q in enumerate(sub_questions):
                    sq_label = str(sub_q.get('label', ''))
                    
                    # Find saved content for this sub-question
                    saved_sq = find_saved_part(sq_label, saved_parts, si)
                    sq_text = ''
                    if saved_sq:
                        sq_text = saved_sq.get('question_text', saved_sq.get('text', ''))
                    if not sq_text:
                        sq_text = sub_q.get('text', sub_q.get('description', ''))
                    if not sq_text:
                        sq_text = '...........................................................................'
                    
                    sq_marks_val = sub_q.get('marks')
                    sq_marks = f"[{sq_marks_val}]" if sq_marks_val is not None and str(sq_marks_val).strip() != "" else ""
                    
                    if sq_label and not (sq_label.startswith('(') and sq_label.endswith(')')):
                        full_sq_label = f"({sq_label})"
                    else:
                        full_sq_label = sq_label

                    sq_table = Table([
                        [Paragraph(sanitize_pdf_text(full_sq_label), board_table_label), Paragraph(sanitize_pdf_text(sq_text), board_table_text), Paragraph(sanitize_pdf_text(sq_marks), board_marks)]
                    ], colWidths=[0.8*inch, 5.0*inch, 0.7*inch], style=TableStyle([
                        ('VALIGN', (0,0), (-1,-1), 'TOP'),
                        ('LEFTPADDING', (0,0), (-1,-1), 0),
                    ]))
                    story.append(sq_table)

            else:
                # Standard Question Rendering
                q_text = f"Q.{q.question_number}  {q.question_text}"
                q_marks = f"[{section.marks_per_question}]"
                
                q_table_data = [
                    [Paragraph(sanitize_pdf_text(q_text), board_question), Paragraph(sanitize_pdf_text(q_marks), board_marks)]
                ]
                q_table = Table(q_table_data, colWidths=[5.8 * inch, 0.7 * inch])
                q_table.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('LEFTPADDING', (0,0), (-1,-1), 0),
                    ('RIGHTPADDING', (0,0), (-1,-1), 0),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 0),
                ]))
                story.append(q_table)

                # Draw options for MCQs
                if q.question_type in ['single_mcq', 'multiple_mcq'] and q.options:
                    option_labels = ['(a)', '(b)', '(c)', '(d)', '(e)', '(f)']
                    
                    if len(q.options) <= 4:
                        opt_data = []
                        for i in range(0, len(q.options), 2):
                            row = []
                            row.append(Paragraph(sanitize_pdf_text(f"{option_labels[i]} {q.options[i]}"), board_option))
                            if i + 1 < len(q.options):
                                row.append(Paragraph(sanitize_pdf_text(f"{option_labels[i+1]} {q.options[i+1]}"), board_option))
                            else:
                                row.append("")
                            opt_data.append(row)
                        
                        opt_table = Table(opt_data, colWidths=[3.25 * inch, 3.25 * inch])
                        opt_table.setStyle(TableStyle([
                            ('LEFTPADDING', (0,0), (-1,-1), 20),
                            ('VALIGN', (0,0), (-1,-1), 'TOP'),
                        ]))
                        story.append(opt_table)
                    else:
                        for i, opt in enumerate(q.options):
                            story.append(Paragraph(sanitize_pdf_text(f"{option_labels[i]} {opt}"), board_option))
            
            story.append(Spacer(1, 10))

    # Footer
    story.append(Spacer(1, 30))
    story.append(Paragraph(sanitize_pdf_text("--- END OF QUESTION PAPER ---"), board_sub_header))

    doc.build(story)
    buffer.seek(0)
    return buffer
