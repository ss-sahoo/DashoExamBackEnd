"""
Timetable app URL configuration.

This module contains all timetable-related API endpoints:
- Timetable creation and management
- Day slots management
- Teacher availability management
- Optimization payload generation
- Timetable authentication and user management
"""

from django.urls import path

from timetable.views import (
    timetable_payload,
    create_timetable_with_slots,
    get_timetable,
    get_timetable_slots,
    list_timetables,
    set_teacher_slot_availability,
    get_teacher_availability,
    assign_batch_to_timetable,
    assign_teacher_to_batch,
    get_timetable_batch_assignments,
    assign_fixed_slot,
    get_fixed_slots,
    run_timetable_optimization,
)

# Import timetable auth and management views from accounts
from accounts.timetable_auth_views import (
    SuperAdminLoginView,
    AdminLoginView,
    TeacherLoginView,
    StaffLoginView,
    StudentLoginView,
    change_password,
)
from accounts.timetable_views import (
    create_center,
    create_admin,
    create_teacher,
    create_student,
)
from accounts.program_batch_views import (
    create_program,
    create_batch,
    add_student_to_batch,
    list_programs,
    get_program,
    list_batches,
    get_batch,
)

app_name = "timetable"

urlpatterns = [
    # ===========
    # Timetable Auth APIs
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
    
    # ===========
    # Timetable Management APIs
    # ===========
    path("admin/timetables/create/", create_timetable_with_slots, name="create-timetable-with-slots"),
    path("timetables/", list_timetables, name="list-timetables"),
    path("timetables/<uuid:timetable_id>/", get_timetable, name="get-timetable"),
    path("timetables/<uuid:timetable_id>/slots/", get_timetable_slots, name="get-timetable-slots"),
    
    # ===========
    # Teacher Availability APIs
    # ===========
    path("admin/timetables/teacher-availability/", set_teacher_slot_availability, name="set-teacher-slot-availability"),
    path("timetables/<uuid:timetable_id>/teacher-availability/", get_teacher_availability, name="get-teacher-availability"),
    
    # ===========
    # Batch and Teacher Assignment APIs
    # ===========
    path("admin/timetables/assign-batch/", assign_batch_to_timetable, name="assign-batch-to-timetable"),
    path("admin/timetables/assign-teacher/", assign_teacher_to_batch, name="assign-teacher-to-batch"),
    path("timetables/<uuid:timetable_id>/batch-assignments/", get_timetable_batch_assignments, name="get-timetable-batch-assignments"),
    
    # ===========
    # Fixed Slot APIs
    # ===========
    path("admin/timetables/fixed-slots/assign/", assign_fixed_slot, name="assign-fixed-slot"),
    path("timetables/<uuid:timetable_id>/fixed-slots/", get_fixed_slots, name="get-fixed-slots"),
    
    # ===========
    # Optimization Payload API
    # ===========
    path("timetables/<uuid:timetable_id>/payload/", timetable_payload, name="timetable-payload"),
    
    # ===========
    # Optimization Algorithm API
    # ===========
    path("timetables/<uuid:timetable_id>/optimize/", run_timetable_optimization, name="run-timetable-optimization"),
]

