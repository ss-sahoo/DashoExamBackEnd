"""
Account app URL configuration.

This module contains all account-related API endpoints:
- Authentication (login for different roles)
- User creation (Super Admin creates centers, admins, teachers, students)
- Program and Batch management
- Password change
"""

from django.urls import path

from timetable_account.api_views import (
    SuperAdminLoginView,
    AdminLoginView,
    TeacherLoginView,
    StaffLoginView,
    StudentLoginView,
    change_password,
)
from timetable_account.user_creation_views import (
    create_center,
    create_admin,
    create_teacher,
    create_student,
)
from timetable_account.program_batch_views import (
    create_program,
    create_batch,
    add_student_to_batch,
    list_programs,
    get_program,
    list_batches,
    get_batch,
)

app_name = "account"

urlpatterns = [
    # ===========
    # Auth APIs
    # ===========
    path("auth/superadmin/login/", SuperAdminLoginView.as_view(), name="superadmin-login"),
    path("auth/admin/login/", AdminLoginView.as_view(), name="admin-login"),
    path("auth/teacher/login/", TeacherLoginView.as_view(), name="teacher-login"),
    path("auth/student/login/", StudentLoginView.as_view(), name="student-login"),
    path("auth/staff/login/", StaffLoginView.as_view(), name="staff-login"),
    path("auth/change-password/", change_password, name="change-password"),

    # ===========
    # Super Admin User Creation APIs
    # ===========
    path("superadmin/centers/create/", create_center, name="create-center"),
    path("superadmin/admins/create/", create_admin, name="create-admin"),
    path("superadmin/teachers/create/", create_teacher, name="create-teacher"),
    path("superadmin/students/create/", create_student, name="create-student"),

    # ===========
    # Program and Batch Management APIs
    # ===========
    path("superadmin/programs/create/", create_program, name="create-program"),
    path("programs/", list_programs, name="list-programs"),
    path("programs/<uuid:program_id>/", get_program, name="get-program"),
    path("admin/batches/create/", create_batch, name="create-batch"),
    path("batches/", list_batches, name="list-batches"),
    path("batches/<uuid:batch_id>/", get_batch, name="get-batch"),
    path("admin/batches/add-student/", add_student_to_batch, name="add-student-to-batch"),
]

