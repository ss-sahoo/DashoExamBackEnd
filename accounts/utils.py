"""
Utility functions for user code and password generation.
"""

import random
import string
from datetime import datetime
from .models import User


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
        'institute_admin': 'ADMIN',
        'exam_admin': 'ADMIN',
        'teacher': 'TEACHER',
        'student': 'STUDENT',
        'ADMIN': 'ADMIN',
        'TEACHER': 'TEACHER',
        'STUDENT': 'STUDENT',
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
                      date_of_birth: str = None, year: int = None) -> str:
    """
    Generate a password based on role and context.
    
    Password format:
    - ADMIN: Admin@<center_code><current_year>
    - TEACHER: Teacher@<center_code><current_year>
    - STUDENT: Student@<batch_code><year> or Student@<dob_year>
    
    Args:
        role: User role
        center_code: Optional center code
        batch_code: Optional batch code (for students)
        date_of_birth: Optional DOB in YYYY-MM-DD format
        year: Optional year (for students, could be batch year or DOB year)
    
    Returns:
        Generated password string
    """
    # Map exam roles to timetable roles for password generation
    role_mapping = {
        'super_admin': 'ADMIN',
        'institute_admin': 'ADMIN',
        'exam_admin': 'ADMIN',
        'teacher': 'TEACHER',
        'student': 'STUDENT',
        'ADMIN': 'ADMIN',
        'TEACHER': 'TEACHER',
        'STUDENT': 'STUDENT',
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
        if center_code:
            center_part = center_code[:4].upper().replace("-", "").replace(" ", "")
            password = f"Teacher@{center_part}{current_year}"
        else:
            password = f"Teacher@{current_year}"
    
    elif mapped_role == 'STUDENT':
        # Priority: batch_code year > DOB year > current year
        if batch_code:
            # Try to extract year from batch code (e.g., "HDTN-1A-2025" -> 2025)
            import re
            year_match = re.search(r'\d{4}', batch_code)
            if year_match:
                year = int(year_match.group())
            else:
                year = current_year
        elif date_of_birth:
            # Extract year from DOB
            try:
                dob_date = datetime.strptime(date_of_birth, "%Y-%m-%d")
                year = dob_date.year
            except:
                year = current_year
        elif year:
            year = year
        else:
            year = current_year
        
        if batch_code:
            batch_part = batch_code[:6].upper().replace("-", "").replace(" ", "")
            password = f"Student@{batch_part}{year}"
        else:
            password = f"Student@{year}"
    
    else:
        password = f"User@{current_year}"
    
    return password

