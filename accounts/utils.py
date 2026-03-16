"""
Utility functions for user code and password generation.
"""

import random
import string
import threading
from datetime import datetime
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from .models import User

# Thread-local storage for the current tenant database
_thread_locals = threading.local()

def set_current_db(db_name):
    """Set the database name for the current thread"""
    _thread_locals.current_db = db_name

def get_current_db():
    """Get the database name for the current thread"""
    return getattr(_thread_locals, 'current_db', 'default')

def clear_current_db():
    """Clear the database name for the current thread"""
    if hasattr(_thread_locals, 'current_db'):
        del _thread_locals.current_db


def generate_user_code(role: str, center_code: str = None, batch_code: str = None) -> str:
    """
    Generate a unique user code based on role and context.
    
    Format:
    - ADMIN: ADM-<center_code>-<3_digits>
    - TEACHER: TCH-<center_code>-<3_digits> or TCH-<3_digits>
    - STUDENT: STU-<batch_code>-<4_digits> or STU-<4_digits>
    
    Args:
        role: User role (ADMIN, TEACHER, STUDENT, or exam roles)
        center_code: Optional center code (first 3-4 chars)
        batch_code: Optional batch code (for students)
    
    Returns:
        Unique user code string
    """
    # Map exam roles to timetable roles for code generation
    role_mapping = {
        'super_admin': 'ADMIN',
        'SUPER_ADMIN': 'ADMIN',
        'institute_admin': 'ADMIN',
        'exam_admin': 'ADMIN',
        'admin': 'ADMIN',
        'ADMIN': 'ADMIN',
        'teacher': 'TEACHER',
        'TEACHER': 'TEACHER',
        'student': 'STUDENT',
        'STUDENT': 'STUDENT',
        'staff': 'STAFF',
        'STAFF': 'STAFF',
    }
    
    mapped_role = role_mapping.get(role, role)
    
    # Get current year for reference
    current_year = datetime.now().year
    
    if mapped_role == 'ADMIN':
        prefix = "ADM"
        if center_code:
            center_part = center_code[:4].upper().replace("-", "")
            suffix = f"{random.randint(100, 999)}"
            code = f"{prefix}-{center_part}-{suffix}"
        else:
            code = f"{prefix}-{random.randint(1000, 9999)}"
    
    elif mapped_role == 'TEACHER':
        prefix = "TCH"
        if center_code:
            center_part = center_code[:4].upper().replace("-", "")
            suffix = f"{random.randint(100, 999)}"
            code = f"{prefix}-{center_part}-{suffix}"
        else:
            code = f"{prefix}-{random.randint(1000, 9999)}"
    
    elif mapped_role == 'STUDENT':
        prefix = "STU"
        if batch_code:
            batch_part = batch_code[:6].upper().replace("-", "").replace(" ", "")
            suffix = f"{random.randint(1000, 9999)}"
            code = f"{prefix}-{batch_part}-{suffix}"
        else:
            code = f"{prefix}-{random.randint(10000, 99999)}"
    
    elif mapped_role == 'STAFF':
        prefix = "STF"
        if center_code:
            center_part = center_code[:4].upper().replace("-", "")
            suffix = f"{random.randint(100, 999)}"
            code = f"{prefix}-{center_part}-{suffix}"
        else:
            code = f"{prefix}-{random.randint(1000, 9999)}"
    
    else:
        # Fallback for other roles
        prefix = mapped_role[:3].upper()
        code = f"{prefix}-{random.randint(1000, 9999)}"
    
    # Ensure uniqueness
    base_code = code
    counter = 1
    while User.objects.filter(username=code).exists():
        if "-" in code:
            parts = code.rsplit("-", 1)
            code = f"{parts[0]}-{counter:03d}"
        else:
            code = f"{base_code}{counter:03d}"
        counter += 1
    
    return code


def generate_password(role: str, center_code: str = None, batch_code: str = None, 
                      date_of_birth: str = None, year: int = None, phone_number: str = None,
                      username: str = None) -> str:
    """
    Generate a unique password based on role and context.
    
    Password format:
    - ADMIN: Admin@<center_code><current_year>
    - TEACHER: Teacher@<center_code><current_year>
    - STUDENT: Student@<unique_combination> (using DOB + phone for uniqueness)
    
    Args:
        role: User role
        center_code: Optional center code
        batch_code: Optional batch code (for students)
        date_of_birth: Optional DOB in YYYY-MM-DD format
        year: Optional year (for students, could be batch year or DOB year)
        phone_number: Optional phone number (for additional uniqueness)
    
    Returns:
        Generated password string
    """
    # Map exam roles to timetable roles for password generation
    role_mapping = {
        'super_admin': 'ADMIN',
        'SUPER_ADMIN': 'ADMIN',
        'institute_admin': 'ADMIN',
        'exam_admin': 'ADMIN',
        'admin': 'ADMIN',
        'ADMIN': 'ADMIN',
        'teacher': 'TEACHER',
        'TEACHER': 'TEACHER',
        'student': 'STUDENT',
        'STUDENT': 'STUDENT',
        'staff': 'STAFF',
        'STAFF': 'STAFF',
    }
    
    mapped_role = role_mapping.get(role, role)
    current_year = datetime.now().year
    
    if mapped_role == 'ADMIN':
        if center_code:
            center_part = center_code[:4].upper().replace("-", "").replace(" ", "")
            password = f"Admin@{center_part}{current_year}"
        else:
            password = f"Admin@{current_year}"
    
    elif mapped_role == 'TEACHER':
        # Create unique password using multiple factors
        password_parts = []
        password_parts.append("Teacher@")
        
        # Add center code if available
        if center_code:
            center_part = center_code[:3].upper().replace("-", "").replace(" ", "")
            password_parts.append(center_part)
        
        # Add phone number last 4 digits for uniqueness
        if phone_number:
            phone_digits = ''.join(filter(str.isdigit, phone_number))
            if len(phone_digits) >= 4:
                phone_part = phone_digits[-4:]
                password_parts.append(phone_part)
        
        # Add current year last 2 digits
        password_parts.append(str(current_year)[-2:])
        
        # If we don't have enough unique components, add timestamp
        if len(''.join(password_parts[1:])) < 6:  # Excluding "Teacher@"
            import time
            timestamp = str(int(time.time()))[-4:]  # Last 4 digits of timestamp
            password_parts.append(timestamp)
        
        password = ''.join(password_parts)
    
    elif mapped_role == 'STUDENT':
        # Create unique password using multiple factors
        password_parts = []
        password_parts.append("Student@")

        # Add date of birth component (DDMM format for uniqueness)
        if date_of_birth:
            try:
                dob_date = datetime.strptime(date_of_birth, "%Y-%m-%d")
                dob_part = f"{dob_date.day:02d}{dob_date.month:02d}"
                password_parts.append(dob_part)
                year = dob_date.year
            except Exception:
                year = current_year

        # Add phone number last 4 digits for additional uniqueness
        if phone_number:
            phone_digits = ''.join(filter(str.isdigit, phone_number))
            if len(phone_digits) >= 4:
                password_parts.append(phone_digits[-4:])

        # Add batch code prefix if available
        if batch_code:
            import re
            year_match = re.search(r'\d{4}', batch_code)
            if year_match:
                year = int(year_match.group())
            else:
                year = current_year
            batch_part = batch_code[:3].upper().replace("-", "").replace(" ", "")
            password_parts.append(batch_part)

        # Add year component
        if not year:
            year = current_year
        password_parts.append(str(year)[-2:])

        # Use the unique username suffix to guarantee no two students share a password
        # username format is e.g. STU-BATCH-1234, so the numeric suffix is always unique
        if username:
            digits = ''.join(filter(str.isdigit, username))
            if digits:
                password_parts.append(digits[-4:])

        # Final fallback if still too short (no username, no DOB, no phone)
        if len(''.join(password_parts[1:])) < 6:
            password_parts.append(str(random.randint(1000, 9999)))

        password = ''.join(password_parts)
    
    elif mapped_role == 'STAFF':
        # Create unique password using multiple factors
        password_parts = []
        password_parts.append("Staff@")
        
        # Add center code if available
        if center_code:
            center_part = center_code[:3].upper().replace("-", "").replace(" ", "")
            password_parts.append(center_part)
        
        # Add phone number last 4 digits for uniqueness
        if phone_number:
            phone_digits = ''.join(filter(str.isdigit, phone_number))
            if len(phone_digits) >= 4:
                phone_part = phone_digits[-4:]
                password_parts.append(phone_part)
        
        # Add current year last 2 digits
        password_parts.append(str(current_year)[-2:])
        
        # If we don't have enough unique components, add timestamp
        if len(''.join(password_parts[1:])) < 6:  # Excluding "Staff@"
            import time
            timestamp = str(int(time.time()))[-4:]  # Last 4 digits of timestamp
            password_parts.append(timestamp)
        
        password = ''.join(password_parts)
    
    else:
        password = f"User@{current_year}"
    
    return password


def log_activity(institute, log_type, title, description, user=None, status='info', metadata=None, request=None):
    """
    Utility function to create an activity log entry.
    """
    from .models import ActivityLog
    
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0]
        else:
            ip_address = request.META.get('REMOTE_ADDR')

    return ActivityLog.objects.create(
        institute=institute,
        log_type=log_type,
        title=title,
        description=description,
        user=user,
        status=status,
        metadata=metadata or {},
        ip_address=ip_address
    )


def send_credentials_email(user, password):
    """
    Send an email to the user with their account credentials.
    """
    try:
        if not user.email:
            print(f"User {user.username} has no email address. Skipping credential email.")
            return False

        # Prepare context
        context = {
            'name': user.get_full_name() or user.username,
            'role': user.role,
            'username': user.username,
            'password': password,
            'institute_name': user.institute.name if user.institute else "Exam Flow System",
            'center_name': user.center.name if user.center else None,
            'login_url': f"{settings.FRONTEND_URL}/login", 
        }

        # Render templates
        subject = "Your Account Credentials - Exam Flow System"
        text_content = render_to_string('emails/credential_notification.txt', context)
        html_content = render_to_string('emails/credential_notification.html', context)

        # Send email
        msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [user.email])
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        
        print(f"Credential email sent to {user.email}")
        return True

    except Exception as e:
        print(f"Failed to send credential email to {user.email}: {str(e)}")
        # We don't want to fail the user creation if email fails, so we just log it
        return False
