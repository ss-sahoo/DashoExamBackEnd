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
    update_timetable,
    get_timetable,
    get_timetable_slots,
    list_timetables,
    set_teacher_slot_availability,
    get_teacher_availability,
    get_available_teachers_for_slot,
    get_teacher_wise_availability,
    assign_batch_to_timetable,
    remove_batch_from_timetable,
    assign_teacher_to_batch,
    remove_teacher_from_batch,
    get_timetable_batch_assignments,
    get_batch_wise_slots,
    assign_fixed_slot,
    get_fixed_slots,
    update_fixed_slot,
    delete_fixed_slot,
    check_timetable_feasibility,
    run_timetable_optimization,
    get_genetic_algorithm_task_status,
    regenerate_timetable_from_slot,
    set_free_classes_count,
    get_free_classes_count,
    get_all_batches_timetable,
    get_batch_timetable,
    get_teacher_timetable,
    activate_timetable,
    deactivate_timetable,
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
    update_center,
    delete_center,
    create_admin,
    create_teacher,
    create_student,
    create_staff,
    bulk_create_teachers,
    bulk_create_students,
    bulk_create_staff,
    download_student_template,
    list_people,
)
from accounts.center_views import (
    list_centers,
    get_center,
    list_center_programs,
    list_center_batches,
    list_people as list_center_users,
    list_center_timetables,
)
from accounts.program_batch_views import (
    create_program,
    create_batch,
    add_student_to_batch,
    list_programs,
    get_program,
    list_batches,
    get_batch,
    get_teachers_in_center,
    update_batch,
    update_batch,
    delete_batch,
    list_batch_students,
    enroll_existing_student,
    remove_student_from_batch,
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
    # Center Management APIs
    # ===========
    path("centers/", list_centers, name="list-centers"),
    path("centers/<uuid:center_id>/", get_center, name="get-center"),
    path("centers/<uuid:center_id>/programs/", list_center_programs, name="list-center-programs"),
    path("centers/<uuid:center_id>/batches/", list_center_batches, name="list-center-batches"),
    path("centers/<uuid:center_id>/users/", list_center_users, name="list-center-users"),
    path("centers/<uuid:center_id>/timetables/", list_center_timetables, name="list-center-timetables"),
    
    # ===========
    # Super Admin User Creation APIs
    # ===========
    path("superadmin/centers/create/", create_center, name="create-center"),
    path("superadmin/centers/<uuid:center_id>/update/", update_center, name="update-center"),
    path("superadmin/centers/<uuid:center_id>/delete/", delete_center, name="delete-center"),
    path("superadmin/admins/create/", create_admin, name="create-admin"),
    path("superadmin/teachers/create/", create_teacher, name="create-teacher"),
    path("superadmin/students/create/", create_student, name="create-student"),
    path("superadmin/staff/create/", create_staff, name="create-staff"),
    path("superadmin/teachers/bulk_create/", bulk_create_teachers, name="bulk-create-teachers"),
    path("superadmin/students/bulk_create/", bulk_create_students, name="bulk-create-students"),
    path("superadmin/students/template/", download_student_template, name="download-student-template"),
    path("superadmin/staff/bulk_create/", bulk_create_staff, name="bulk-create-staff"),
    
    # ===========
    # Admin User Creation APIs (for their center)
    # ===========
    path("admin/teachers/create/", create_teacher, name="admin-create-teacher"),
    path("admin/students/create/", create_student, name="admin-create-student"),
    path("admin/staff/create/", create_staff, name="admin-create-staff"),
    
    # ===========
    # Program and Batch Management APIs
    # ===========
    path("superadmin/programs/create/", create_program, name="create-program"),
    path("programs/", list_programs, name="list-programs"),
    path("programs/<uuid:program_id>/", get_program, name="get-program"),
    path("admin/batches/create/", create_batch, name="create-batch"),
    path("batches/", list_batches, name="list-batches"),
    path("batches/<uuid:batch_id>/", get_batch, name="get-batch"),
    path("admin/batches/<uuid:batch_id>/update/", update_batch, name="update-batch"),
    path("admin/batches/<uuid:batch_id>/delete/", delete_batch, name="delete-batch"),
    path("admin/batches/add-student/", add_student_to_batch, name="add-student-to-batch"),
    path("admin/batches/<uuid:batch_id>/students/", list_batch_students, name="list-batch-students"),
    path("admin/batches/<uuid:batch_id>/enroll/", enroll_existing_student, name="enroll-existing-student"),
    path("admin/batches/<uuid:batch_id>/students/<uuid:student_id>/", remove_student_from_batch, name="remove-student-from-batch"),
    path("teachers/", get_teachers_in_center, name="get-teachers-in-center"),
    
    # ===========
    # Timetable Management APIs
    # ===========
    path("admin/timetables/create/", create_timetable_with_slots, name="create-timetable-with-slots"),
    path("admin/timetables/<uuid:timetable_id>/update/", update_timetable, name="update-timetable"),
    path("admin/timetables/<uuid:timetable_id>/activate/", activate_timetable, name="activate-timetable"),
    path("admin/timetables/<uuid:timetable_id>/deactivate/", deactivate_timetable, name="deactivate-timetable"),
    path("timetables/", list_timetables, name="list-timetables"),
    path("timetables/<uuid:timetable_id>/", get_timetable, name="get-timetable"),
    path("timetables/<uuid:timetable_id>/slots/", get_timetable_slots, name="get-timetable-slots"),
    path("admin/timetables/<uuid:timetable_id>/free-classes/", set_free_classes_count, name="set-free-classes-count"),
    path("timetables/<uuid:timetable_id>/free-classes/", get_free_classes_count, name="get-free-classes-count"),
    
    # ===========
    # Teacher Availability APIs
    # ===========
    path("admin/timetables/teacher-availability/", set_teacher_slot_availability, name="set-teacher-slot-availability"),
    path("timetables/<uuid:timetable_id>/teacher-availability/", get_teacher_availability, name="get-teacher-availability"),
    path("timetables/<uuid:timetable_id>/teacher-wise-availability/", get_teacher_wise_availability, name="get-teacher-wise-availability"),
    path("timetables/<uuid:timetable_id>/slots/<uuid:slot_id>/available-teachers/", get_available_teachers_for_slot, name="get-available-teachers-for-slot"),
    path("timetables/<uuid:timetable_id>/available-teachers/", get_available_teachers_for_slot, name="get-available-teachers-by-slot-code"),
    
    # ===========
    # Batch and Teacher Assignment APIs
    # ===========
    path("admin/timetables/assign-batch/", assign_batch_to_timetable, name="assign-batch-to-timetable"),
    path("admin/timetables/remove-batch/", remove_batch_from_timetable, name="remove-batch-from-timetable"),
    path("admin/timetables/assign-teacher/", assign_teacher_to_batch, name="assign-teacher-to-batch"),
    path("admin/timetables/remove-teacher/", remove_teacher_from_batch, name="remove-teacher-from-batch"),
    path("timetables/<uuid:timetable_id>/batch-assignments/", get_timetable_batch_assignments, name="get-timetable-batch-assignments"),
    path("timetables/<uuid:timetable_id>/batch-wise-slots/", get_batch_wise_slots, name="get-batch-wise-slots"),
    path("timetables/<uuid:timetable_id>/batch-wise-slots/<uuid:batch_id>/", get_batch_wise_slots, name="get-single-batch-slots"),
    
    # ===========
    # Fixed Slot APIs
    # ===========
    path("admin/timetables/fixed-slots/assign/", assign_fixed_slot, name="assign-fixed-slot"),
    path("timetables/<uuid:timetable_id>/fixed-slots/", get_fixed_slots, name="get-fixed-slots"),
    path("admin/timetables/fixed-slots/<uuid:fixed_slot_id>/update/", update_fixed_slot, name="update-fixed-slot"),
    path("admin/timetables/fixed-slots/<uuid:fixed_slot_id>/delete/", delete_fixed_slot, name="delete-fixed-slot"),
    
    # ===========
    # Optimization Payload API
    # ===========
    path("timetables/<uuid:timetable_id>/payload/", timetable_payload, name="timetable-payload"),
    
    # ===========
    # Optimization Algorithm API
    # ===========
    path("timetables/<uuid:timetable_id>/check-feasibility/", check_timetable_feasibility, name="check-timetable-feasibility"),
    path("timetables/<uuid:timetable_id>/optimize/", run_timetable_optimization, name="run-timetable-optimization"),
    path("timetables/<uuid:timetable_id>/regenerate-from-slot/", regenerate_timetable_from_slot, name="regenerate-timetable-from-slot"),
    path("tasks/<str:task_id>/status/", get_genetic_algorithm_task_status, name="get-genetic-algorithm-task-status"),
    
    # ===========
    # Batch-wise Timetable GET APIs
    # ===========
    path("timetables/<uuid:timetable_id>/batches/", get_all_batches_timetable, name="get-all-batches-timetable"),
    path("timetables/<uuid:timetable_id>/batches/<uuid:batch_id>/", get_batch_timetable, name="get-batch-timetable"),
    
    # ===========
    # Teacher-wise Timetable GET APIs
    # ===========
    path("timetables/<uuid:timetable_id>/teachers/", get_teacher_timetable, name="get-all-teachers-timetable"),
    path("timetables/<uuid:timetable_id>/teachers/<uuid:teacher_id>/", get_teacher_timetable, name="get-teacher-timetable"),
]
