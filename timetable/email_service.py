"""
Email service for sending timetable notifications to teachers.
Generates PDF timetables and sends them via email.
"""
from django.core.mail import EmailMessage
from django.conf import settings
from django.template.loader import render_to_string
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def generate_teacher_timetable_pdf(teacher, timetable, slots_by_day, batches):
    """
    Generate a PDF timetable for a specific teacher.
    
    Args:
        teacher: User object (teacher)
        timetable: Timetable object
        slots_by_day: Dict of day -> list of slot assignments
        batches: List of batch codes assigned to this teacher
    
    Returns:
        BytesIO buffer containing the PDF
    """
    buffer = BytesIO()
    
    # Create PDF document in landscape mode for better table fit
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1*cm,
        leftMargin=1*cm,
        topMargin=1*cm,
        bottomMargin=1*cm
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        alignment=TA_CENTER,
        spaceAfter=20
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=12,
        alignment=TA_CENTER,
        spaceAfter=10
    )
    
    info_style = ParagraphStyle(
        'InfoStyle',
        parent=styles['Normal'],
        fontSize=10,
        alignment=TA_LEFT,
        spaceAfter=5
    )
    
    # Title
    teacher_name = teacher.get_full_name() or teacher.username
    elements.append(Paragraph(f"Timetable for {teacher_name}", title_style))
    
    # Timetable info
    timetable_name = timetable.name or f"{timetable.center.name} Timetable"
    elements.append(Paragraph(timetable_name, subtitle_style))
    elements.append(Paragraph(
        f"Period: {timetable.from_date.strftime('%d %b %Y')} to {timetable.to_date.strftime('%d %b %Y')}",
        subtitle_style
    ))
    elements.append(Spacer(1, 0.3*inch))
    
    # Teacher info
    elements.append(Paragraph(f"<b>Teacher Code:</b> {teacher.teacher_code or 'N/A'}", info_style))
    elements.append(Paragraph(f"<b>Center:</b> {timetable.center.name}", info_style))
    elements.append(Paragraph(f"<b>Batches:</b> {', '.join(batches) if batches else 'N/A'}", info_style))
    elements.append(Spacer(1, 0.3*inch))
    
    # Build timetable table
    # Get all unique days and sort them
    day_order = ['d1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7', 'd8', 'd9', 'd10',
                 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
    
    sorted_days = sorted(
        slots_by_day.keys(),
        key=lambda x: day_order.index(x.lower()) if x.lower() in day_order else 100
    )
    
    if not sorted_days:
        elements.append(Paragraph("No classes scheduled.", info_style))
    else:
        # Get all unique slot numbers across all days
        all_slots = set()
        for day_slots in slots_by_day.values():
            for slot in day_slots:
                all_slots.add(slot.get('slot_number', 0))
        
        sorted_slot_numbers = sorted(all_slots)
        
        # Build header row
        header_row = ['Day/Slot']
        for slot_num in sorted_slot_numbers:
            header_row.append(f"Slot {slot_num}")
        
        # Build data rows
        table_data = [header_row]
        
        for day in sorted_days:
            day_display = day.upper()
            if day.lower().startswith('d') and day[1:].isdigit():
                # Date-based day
                day_slots = slots_by_day.get(day, [])
                if day_slots and day_slots[0].get('actual_date'):
                    day_display = day_slots[0]['actual_date']
            
            row = [day_display]
            day_slots = slots_by_day.get(day, [])
            
            # Create a lookup by slot number
            slot_lookup = {s.get('slot_number'): s for s in day_slots}
            
            for slot_num in sorted_slot_numbers:
                slot = slot_lookup.get(slot_num)
                if slot:
                    cell_text = f"{slot.get('subject', 'N/A')}\n{slot.get('batch_code', '')}\n{slot.get('start_time', '')}-{slot.get('end_time', '')}"
                    row.append(cell_text)
                else:
                    row.append("-")
            
            table_data.append(row)
        
        # Create table
        col_widths = [2*cm] + [3.5*cm] * len(sorted_slot_numbers)
        table = Table(table_data, colWidths=col_widths)
        
        # Table styling
        table_style = TableStyle([
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            
            # First column styling (days)
            ('BACKGROUND', (0, 1), (0, -1), colors.HexColor('#D6DCE5')),
            ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
            
            # Body styling
            ('FONTNAME', (1, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BOX', (0, 0), (-1, -1), 1, colors.black),
            
            # Alternating row colors
            ('ROWBACKGROUNDS', (1, 1), (-1, -1), [colors.white, colors.HexColor('#F2F2F2')]),
            
            # Padding
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ])
        
        table.setStyle(table_style)
        elements.append(table)
    
    # Footer
    elements.append(Spacer(1, 0.5*inch))
    footer_style = ParagraphStyle(
        'FooterStyle',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.grey
    )
    elements.append(Paragraph(
        f"Generated on {datetime.now().strftime('%d %b %Y at %H:%M')} | {timetable.center.name}",
        footer_style
    ))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return buffer


def send_timetable_email_to_teacher(teacher, timetable, slots_by_day, batches):
    """
    Send timetable email with PDF attachment to a teacher.
    
    Args:
        teacher: User object (teacher)
        timetable: Timetable object
        slots_by_day: Dict of day -> list of slot assignments
        batches: List of batch codes
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    if not teacher.email:
        logger.warning(f"Teacher {teacher.username} has no email address")
        return False
    
    try:
        # Generate PDF
        pdf_buffer = generate_teacher_timetable_pdf(teacher, timetable, slots_by_day, batches)
        
        # Prepare email content
        teacher_name = teacher.get_full_name() or teacher.username
        timetable_name = timetable.name or f"{timetable.center.name} Timetable"
        
        subject = f"Your Timetable - {timetable_name}"
        
        # Email body
        body = f"""Dear {teacher_name},

A new timetable has been activated for you at {timetable.center.name}.

Timetable Details:
- Name: {timetable_name}
- Period: {timetable.from_date.strftime('%d %b %Y')} to {timetable.to_date.strftime('%d %b %Y')}
- Batches: {', '.join(batches) if batches else 'N/A'}

Please find your personalized timetable attached as a PDF.

If you have any questions, please contact your center administrator.

Best regards,
{timetable.center.name}
"""
        
        # Create email
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[teacher.email],
        )
        
        # Attach PDF
        filename = f"timetable_{teacher.teacher_code or teacher.username}_{timetable.from_date.strftime('%Y%m%d')}.pdf"
        email.attach(filename, pdf_buffer.getvalue(), 'application/pdf')
        
        # Send email
        email.send(fail_silently=False)
        
        logger.info(f"Timetable email sent to {teacher.email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send timetable email to {teacher.email}: {str(e)}")
        return False


def send_timetable_emails_to_all_teachers(timetable):
    """
    Send timetable emails to all teachers assigned to a timetable.
    
    Args:
        timetable: Timetable object
    
    Returns:
        dict: Summary of emails sent
    """
    from .models import BatchFacultyLoad, TimetableEntry, FixedSlot, DaySlot
    from accounts.models import User as AccountUser
    
    # Get all teachers assigned to this timetable
    teacher_ids = set()
    
    # From BatchFacultyLoad
    teacher_ids.update(
        BatchFacultyLoad.objects.filter(
            timetable=timetable,
            teacher__isnull=False
        ).values_list('teacher_id', flat=True)
    )
    
    # From TimetableEntry
    teacher_ids.update(
        TimetableEntry.objects.filter(
            day_slot__timetable=timetable,
            teacher__isnull=False
        ).values_list('teacher_id', flat=True)
    )
    
    # From FixedSlot
    teacher_ids.update(
        FixedSlot.objects.filter(
            timetable=timetable,
            teacher__isnull=False
        ).values_list('teacher_id', flat=True)
    )
    
    teachers = AccountUser.objects.filter(id__in=teacher_ids)
    
    # Get all entries and fixed slots for this timetable
    entries = TimetableEntry.objects.filter(
        day_slot__timetable=timetable
    ).select_related('day_slot', 'batch', 'teacher')
    
    fixed_slots = FixedSlot.objects.filter(
        timetable=timetable
    ).select_related('day_slot', 'batch', 'teacher')
    
    # Day key helper
    DAY_MAP_SHORT = {
        'MON': 'mon', 'TUE': 'tue', 'WED': 'wed',
        'THU': 'thu', 'FRI': 'fri', 'SAT': 'sat', 'SUN': 'sun'
    }
    
    def get_day_key(day_slot):
        if day_slot.day_index:
            return f"d{day_slot.day_index}"
        return DAY_MAP_SHORT.get(day_slot.day, 'unknown')
    
    # Send emails to each teacher
    results = {
        'total_teachers': len(teachers),
        'emails_sent': 0,
        'emails_failed': 0,
        'no_email': 0,
        'details': []
    }
    
    for teacher in teachers:
        if not teacher.email:
            results['no_email'] += 1
            results['details'].append({
                'teacher_code': teacher.teacher_code or teacher.username,
                'teacher_name': teacher.get_full_name(),
                'status': 'no_email'
            })
            continue
        
        # Build slots_by_day for this teacher
        slots_by_day = {}
        batches_set = set()
        
        # From TimetableEntry
        teacher_entries = [e for e in entries if e.teacher_id == teacher.id]
        for entry in teacher_entries:
            day_key = get_day_key(entry.day_slot)
            if day_key == 'unknown':
                continue
            
            slot_data = {
                'slot_code': entry.day_slot.slot_code,
                'slot_number': entry.day_slot.slot_number,
                'start_time': entry.day_slot.start_time.strftime('%H:%M'),
                'end_time': entry.day_slot.end_time.strftime('%H:%M'),
                'batch_code': entry.batch.code,
                'batch_name': entry.batch.name,
                'subject': entry.subject,
                'actual_date': str(entry.day_slot.actual_date) if entry.day_slot.actual_date else None,
            }
            
            slots_by_day.setdefault(day_key, []).append(slot_data)
            batches_set.add(entry.batch.code)
        
        # From FixedSlot
        teacher_fixed = [fs for fs in fixed_slots if fs.teacher_id == teacher.id]
        for fs in teacher_fixed:
            day_key = get_day_key(fs.day_slot)
            if day_key == 'unknown':
                continue
            
            # Check if already exists
            existing = False
            if day_key in slots_by_day:
                for s in slots_by_day[day_key]:
                    if s['slot_code'] == fs.day_slot.slot_code and s['batch_code'] == fs.batch.code:
                        existing = True
                        break
            
            if not existing:
                slot_data = {
                    'slot_code': fs.day_slot.slot_code,
                    'slot_number': fs.day_slot.slot_number,
                    'start_time': fs.day_slot.start_time.strftime('%H:%M'),
                    'end_time': fs.day_slot.end_time.strftime('%H:%M'),
                    'batch_code': fs.batch.code,
                    'batch_name': fs.batch.name,
                    'subject': fs.subject or '',
                    'actual_date': str(fs.day_slot.actual_date) if fs.day_slot.actual_date else None,
                }
                slots_by_day.setdefault(day_key, []).append(slot_data)
                batches_set.add(fs.batch.code)
        
        # Send email
        success = send_timetable_email_to_teacher(
            teacher, timetable, slots_by_day, sorted(list(batches_set))
        )
        
        if success:
            results['emails_sent'] += 1
            results['details'].append({
                'teacher_code': teacher.teacher_code or teacher.username,
                'teacher_name': teacher.get_full_name(),
                'email': teacher.email,
                'status': 'sent'
            })
        else:
            results['emails_failed'] += 1
            results['details'].append({
                'teacher_code': teacher.teacher_code or teacher.username,
                'teacher_name': teacher.get_full_name(),
                'email': teacher.email,
                'status': 'failed'
            })
    
    return results
