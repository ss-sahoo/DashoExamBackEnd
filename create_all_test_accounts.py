"""
Script to create all test accounts for ExamFlow system.
Creates: Institute SuperAdmin, Admin, Center, Teacher, Student, Staff
All with proper relationships and login credentials.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import Institute, Center, User

def create_test_accounts():
    """Create all test accounts with proper relationships"""
    
    print("=" * 60)
    print("CREATING TEST ACCOUNTS FOR EXAMFLOW")
    print("=" * 60)
    
    # 1. Get or create the main test institute
    institute, created = Institute.objects.get_or_create(
        name="DiracAI",
        defaults={
            'description': 'Main test institute for ExamFlow',
            'domain': 'diracai.com',
            'contact_email': 'contact@diracai.com',
            'is_active': True,
            'is_verified': True,
        }
    )
    print(f"\n Institute: {institute.name} (ID: {institute.id})")
    
    # 2. Create a Center under the institute
    center, created = Center.objects.get_or_create(
        institute=institute,
        name="DiracAI Main Center",
        defaults={
            'city': 'Mumbai',
            'address': '123 Tech Park, Mumbai, India',
        }
    )
    print(f" Center: {center.name} (ID: {center.id})")
    
    # 3. Create Institute SuperAdmin (super_admin role)
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
    superadmin.set_password('superadmin123')
    superadmin.save()
    print(f"\n SUPER ADMIN Created:")
    print(f"   Email: superadmin@diracai.com")
    print(f"   Password: superadmin123")
    print(f"   Role: super_admin")
    print(f"   Login: Email/Username")
    
    # 4. Create Institute Admin (institute_admin role)
    inst_admin, created = User.objects.get_or_create(
        email='instituteadmin@diracai.com',
        defaults={
            'username': 'instituteadmin',
            'first_name': 'Institute',
            'last_name': 'Admin',
            'role': 'institute_admin',
            'institute': institute,
            'center': center,
            'is_active': True,
            'is_verified': True,
        }
    )
    inst_admin.set_password('instadmin123')
    inst_admin.save()
    # Add as center admin
    center.admins.add(inst_admin)
    print(f"\n INSTITUTE ADMIN Created:")
    print(f"   Email: instituteadmin@diracai.com")
    print(f"   Password: instadmin123")
    print(f"   Role: institute_admin")
    print(f"   Center: {center.name}")
    print(f"   Login: Email/Username")
    
    # 5. Create Center Admin (ADMIN role - for code-based login)
    center_admin, created = User.objects.get_or_create(
        email='centeradmin@diracai.com',
        defaults={
            'username': 'centeradmin',
            'first_name': 'Center',
            'last_name': 'Admin',
            'role': 'ADMIN',
            'institute': institute,
            'center': center,
            'is_active': True,
            'is_verified': True,
        }
    )
    center_admin.set_password('centeradmin123')
    center_admin.save()
    # Add as center admin
    center.admins.add(center_admin)
    print(f"\n CENTER ADMIN Created:")
    print(f"   Email: centeradmin@diracai.com")
    print(f"   Username: centeradmin")
    print(f"   Password: centeradmin123")
    print(f"   Role: ADMIN")
    print(f"   Center: {center.name}")
    print(f"   Login: Email/Username/Code")
    
    # 6. Create Teacher (teacher role - with teacher_code for code-based login)
    teacher, created = User.objects.get_or_create(
        email='teacher@diracai.com',
        defaults={
            'username': 'teacher1',
            'first_name': 'Test',
            'last_name': 'Teacher',
            'role': 'teacher',
            'institute': institute,
            'center': center,
            'teacher_code': 'TCH001',
            'teacher_employee_id': 'EMP-001',
            'teacher_subjects': 'Physics, Mathematics',
            'is_active': True,
            'is_verified': True,
        }
    )
    teacher.set_password('teacher123')
    teacher.teacher_code = 'TCH001'
    teacher.save()
    print(f"\n TEACHER Created:")
    print(f"   Email: teacher@diracai.com")
    print(f"   Username: teacher1")
    print(f"   Teacher Code: TCH001")
    print(f"   Password: teacher123")
    print(f"   Role: teacher")
    print(f"   Center: {center.name}")
    print(f"   Login: Email/Username/Teacher Code (TCH001)")
    
    # 7. Create Student (student role)
    student, created = User.objects.get_or_create(
        email='student@diracai.com',
        defaults={
            'username': 'student1',
            'first_name': 'Test',
            'last_name': 'Student',
            'role': 'student',
            'institute': institute,
            'center': center,
            'is_active': True,
            'is_verified': True,
        }
    )
    student.set_password('student123')
    student.save()
    print(f"\n STUDENT Created:")
    print(f"   Email: student@diracai.com")
    print(f"   Username: student1")
    print(f"   Password: student123")
    print(f"   Role: student")
    print(f"   Center: {center.name}")
    print(f"   Login: Email/Username")
    
    # 8. Create Staff (STAFF role)
    staff, created = User.objects.get_or_create(
        email='staff@diracai.com',
        defaults={
            'username': 'staff1',
            'first_name': 'Test',
            'last_name': 'Staff',
            'role': 'STAFF',
            'institute': institute,
            'center': center,
            'is_active': True,
            'is_verified': True,
        }
    )
    staff.set_password('staff123')
    staff.save()
    print(f"\n STAFF Created:")
    print(f"   Email: staff@diracai.com")
    print(f"   Username: staff1")
    print(f"   Password: staff123")
    print(f"   Role: STAFF")
    print(f"   Center: {center.name}")
    print(f"   Login: Email/Username")
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY - ALL TEST ACCOUNTS")
    print("=" * 60)
    print(f"""
┌─────────────────────────────────────────────────────────────────────────────────┐
│ INSTITUTE: {institute.name} (ID: {institute.id})                                              
│ CENTER: {center.name} (ID: {center.id})
├─────────────────────────────────────────────────────────────────────────────────┤
│ ROLE            │ EMAIL                      │ PASSWORD       │ LOGIN METHOD   │
├─────────────────────────────────────────────────────────────────────────────────┤
│ super_admin     │ superadmin@diracai.com     │ superadmin123  │ Email/Username │
│ institute_admin │ instituteadmin@diracai.com │ instadmin123   │ Email/Username │
│ ADMIN (Center)  │ centeradmin@diracai.com    │ centeradmin123 │ Email/Username │
│ teacher         │ teacher@diracai.com        │ teacher123     │ Email/TCH001   │
│ student         │ student@diracai.com        │ student123     │ Email/Username │
│ STAFF           │ staff@diracai.com          │ staff123       │ Email/Username │
└─────────────────────────────────────────────────────────────────────────────────┘

LOGIN ENDPOINTS:
- Super Admin:  POST /api/auth/superadmin/login/
- Admin:        POST /api/auth/admin/login/
- Teacher:      POST /api/auth/teacher/login/
- Student:      POST /api/auth/student/login/
- Staff:        POST /api/auth/staff/login/

DASHBOARD ROUTES:
- Super Admin:  /superadmin/dashboard
- Admin:        /center-admin/dashboard
- Teacher:      /teacher
- Student:      /student-dashboard
""")
    
    return {
        'institute': institute,
        'center': center,
        'superadmin': superadmin,
        'institute_admin': inst_admin,
        'center_admin': center_admin,
        'teacher': teacher,
        'student': student,
        'staff': staff,
    }


if __name__ == '__main__':
    create_test_accounts()
