"""
Script to create test accounts using the proper APIs.
This will generate auto-generated codes for Admin, Teacher, Student, Staff.
"""

import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from django.db import transaction
from accounts.models import Institute, Center, User, Program, Batch
from accounts.utils import generate_user_code, generate_password


def create_all_accounts():
    print("=" * 70)
    print("CREATING TEST ACCOUNTS WITH AUTO-GENERATED CODES")
    print("=" * 70)
    
    # 1. Get or create Institute
    institute, _ = Institute.objects.get_or_create(
        name="DiracAI",
        defaults={
            'description': 'Main test institute',
            'is_active': True,
            'is_verified': True,
        }
    )
    print(f"\n Institute: {institute.name} (ID: {institute.id})")
    
    # 2. Get or create Center
    center, _ = Center.objects.get_or_create(
        institute=institute,
        name="DiracAI Main Center",
        defaults={
            'city': 'Mumbai',
            'address': '123 Tech Park, Mumbai',
        }
    )
    print(f" Center: {center.name} (ID: {center.id})")
    
    # 3. Get or create Program
    program, _ = Program.objects.get_or_create(
        center=center,
        name="JEE Advanced 2026",
        defaults={
            'description': 'JEE Advanced preparation program',
            'is_active': True,
        }
    )
    print(f" Program: {program.name} (ID: {program.id})")
    
    # 4. Get or create Batch
    batch, _ = Batch.objects.get_or_create(
        program=program,
        code="JEE-2026-A",
        defaults={
            'name': 'JEE 2026 Batch A',
        }
    )
    print(f" Batch: {batch.name} (Code: {batch.code})")
    
    # Center code for generating usernames
    center_code = center.name[:4].replace(" ", "").replace("-", "")
    
    created_accounts = []
    
    # ============================================
    # 5. Create SUPER ADMIN (manual - no code needed)
    # ============================================
    superadmin, created = User.objects.get_or_create(
        email='superadmin@diracai.com',
        defaults={
            'username': 'superadmin',
            'first_name': 'Super',
            'last_name': 'Admin',
            'role': 'super_admin',
            'institute': institute,
            'is_active': True,
            'is_verified': True,
            'is_staff': True,
            'is_superuser': True,
        }
    )
    superadmin.set_password('SuperAdmin@2026')
    superadmin.save()
    created_accounts.append({
        'role': 'super_admin',
        'code': 'superadmin',
        'email': 'superadmin@diracai.com',
        'password': 'SuperAdmin@2026',
        'login_with': 'Email or Username'
    })
    
    # ============================================
    # 6. Create ADMIN with auto-generated code
    # ============================================
    admin_code = generate_user_code('ADMIN', center_code)
    admin_password = generate_password('ADMIN', center_code)
    
    admin, created = User.objects.get_or_create(
        username=admin_code,
        defaults={
            'email': f'{admin_code.lower()}@diracai.com',
            'first_name': 'Center',
            'last_name': 'Admin',
            'role': 'ADMIN',
            'institute': institute,
            'center': center,
            'is_active': True,
            'is_verified': True,
        }
    )
    if created:
        admin.set_password(admin_password)
        admin.save()
        center.admins.add(admin)
    else:
        # Get existing password pattern
        admin_password = generate_password('ADMIN', center_code)
        admin.set_password(admin_password)
        admin.save()
    
    created_accounts.append({
        'role': 'ADMIN (Center Admin)',
        'code': admin_code,
        'email': admin.email,
        'password': admin_password,
        'login_with': f'Code: {admin_code}'
    })
    
    # ============================================
    # 7. Create TEACHER with auto-generated code
    # ============================================
    teacher_code = generate_user_code('TEACHER', center_code)
    teacher_password = generate_password('TEACHER', center_code)
    
    teacher, created = User.objects.get_or_create(
        username=teacher_code,
        defaults={
            'email': f'{teacher_code.lower()}@diracai.com',
            'first_name': 'Test',
            'last_name': 'Teacher',
            'role': 'teacher',
            'institute': institute,
            'center': center,
            'teacher_code': teacher_code,
            'teacher_subjects': 'Physics, Mathematics',
            'is_active': True,
            'is_verified': True,
        }
    )
    if created:
        teacher.set_password(teacher_password)
        teacher.save()
    else:
        teacher_password = generate_password('TEACHER', center_code)
        teacher.set_password(teacher_password)
        teacher.teacher_code = teacher_code
        teacher.save()
    
    created_accounts.append({
        'role': 'teacher',
        'code': teacher_code,
        'email': teacher.email,
        'password': teacher_password,
        'login_with': f'Code: {teacher_code}'
    })
    
    # ============================================
    # 8. Create STUDENT with auto-generated code
    # ============================================
    student_code = generate_user_code('STUDENT', None, batch.code)
    student_password = generate_password('STUDENT', None, batch.code)
    
    student, created = User.objects.get_or_create(
        username=student_code,
        defaults={
            'email': f'{student_code.lower()}@diracai.com',
            'first_name': 'Test',
            'last_name': 'Student',
            'role': 'student',
            'institute': institute,
            'center': center,
            'is_active': True,
            'is_verified': True,
        }
    )
    if created:
        student.set_password(student_password)
        student.save()
    else:
        student_password = generate_password('STUDENT', None, batch.code)
        student.set_password(student_password)
        student.save()
    
    created_accounts.append({
        'role': 'student',
        'code': student_code,
        'email': student.email,
        'password': student_password,
        'login_with': f'Code: {student_code}'
    })
    
    # ============================================
    # 9. Create STAFF with auto-generated code
    # ============================================
    staff_code = generate_user_code('STAFF', center_code)
    staff_password = generate_password('STAFF', center_code)
    
    staff, created = User.objects.get_or_create(
        username=staff_code,
        defaults={
            'email': f'{staff_code.lower()}@diracai.com',
            'first_name': 'Test',
            'last_name': 'Staff',
            'role': 'STAFF',
            'institute': institute,
            'center': center,
            'is_active': True,
            'is_verified': True,
        }
    )
    if created:
        staff.set_password(staff_password)
        staff.save()
    else:
        staff_password = generate_password('STAFF', center_code)
        staff.set_password(staff_password)
        staff.save()
    
    created_accounts.append({
        'role': 'STAFF',
        'code': staff_code,
        'email': staff.email,
        'password': staff_password,
        'login_with': f'Code: {staff_code}'
    })
    
    # ============================================
    # Print Summary
    # ============================================
    print("\n" + "=" * 70)
    print(" ALL ACCOUNTS CREATED WITH AUTO-GENERATED CODES")
    print("=" * 70)
    print(f"\nInstitute: {institute.name}")
    print(f"Center: {center.name} (ID: {center.id})")
    print(f"Program: {program.name}")
    print(f"Batch: {batch.code}")
    print("\n" + "-" * 70)
    print(f"{'ROLE':<20} {'CODE/USERNAME':<20} {'PASSWORD':<25}")
    print("-" * 70)
    
    for acc in created_accounts:
        print(f"{acc['role']:<20} {acc['code']:<20} {acc['password']:<25}")
    
    print("-" * 70)
    print("\n📋 LOGIN INSTRUCTIONS:")
    print("-" * 70)
    
    for acc in created_accounts:
        print(f"\n{acc['role'].upper()}:")
        print(f"   Username/Code: {acc['code']}")
        print(f"   Password: {acc['password']}")
        if acc['role'] == 'super_admin':
            print(f"   Endpoint: POST /api/timetable/auth/superadmin/login/")
        elif 'ADMIN' in acc['role']:
            print(f"   Endpoint: POST /api/timetable/auth/admin/login/")
        elif acc['role'] == 'teacher':
            print(f"   Endpoint: POST /api/timetable/auth/teacher/login/")
        elif acc['role'] == 'student':
            print(f"   Endpoint: POST /api/timetable/auth/student/login/")
        elif acc['role'] == 'STAFF':
            print(f"   Endpoint: POST /api/timetable/auth/staff/login/")
    
    print("\n" + "=" * 70)
    print("Example Login Request:")
    print("=" * 70)
    print("""
curl -X POST http://localhost:8000/api/timetable/auth/admin/login/ \\
  -H "Content-Type: application/json" \\
  -d '{"username": "<CODE>", "password": "<PASSWORD>"}'
""")
    
    return created_accounts


if __name__ == '__main__':
    create_all_accounts()
