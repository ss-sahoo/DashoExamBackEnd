"""
APIs for Program and Batch management.

- Super Admin can create Programs under centers
- Admin can create Batches under programs in their center
- Admin can add students to batches
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from datetime import datetime
from timetable_account.models import Center, Program, Batch, Enrollment, User
from timetable_account.utils import generate_user_code, generate_password


def _check_super_admin(request):
    """Helper to check if user is super admin."""
    if not request.user.is_authenticated:
        return False, Response(
            {"detail": "Authentication required."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if request.user.role != User.ROLE_SUPER_ADMIN:
        return False, Response(
            {"detail": "Only Super Admin can perform this action."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return True, None


def _check_admin(request):
    """Helper to check if user is admin."""
    if not request.user.is_authenticated:
        return False, Response(
            {"detail": "Authentication required."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    if request.user.role != User.ROLE_ADMIN:
        return False, Response(
            {"detail": "Only Admin can perform this action."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not request.user.center:
        return False, Response(
            {"detail": "Admin user is not linked to any center."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return True, None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_program(request):
    """
    Super Admin creates a new Program under a center.
    
    Payload:
    {
        "center_name": "Allen - Jaipur Center",
        "name": "Super 30",
        "description": "JEE preparation program",
        "category": "JEE Prep"
    }
    
    Returns:
    {
        "id": "uuid",
        "name": "Super 30",
        "center": "Allen - Jaipur Center",
        "is_active": true
    }
    """
    is_super, error_response = _check_super_admin(request)
    if not is_super:
        return error_response
    
    center_name = request.data.get("center_name")
    name = request.data.get("name")
    description = request.data.get("description", "")
    category = request.data.get("category", "")
    
    if not center_name or not name:
        return Response(
            {"detail": "center_name and name are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    try:
        center = Center.objects.get(name=center_name)
    except Center.DoesNotExist:
        return Response(
            {"detail": f"Center '{center_name}' not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Center.MultipleObjectsReturned:
        return Response(
            {"detail": f"Multiple centers found with name '{center_name}'. Please use center_id instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Check if program already exists for this center
    if Program.objects.filter(center=center, name=name).exists():
        return Response(
            {"detail": f"Program '{name}' already exists for center '{center_name}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    try:
        program = Program.objects.create(
            center=center,
            name=name,
            description=description,
            category=category,
            is_active=True,
        )
        return Response(
            {
                "id": str(program.id),
                "name": program.name,
                "center": center.name,
                "description": program.description,
                "category": program.category,
                "is_active": program.is_active,
            },
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        return Response(
            {"detail": f"Error creating program: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_batch(request):
    """
    Admin creates a new Batch under a program in their center.
    
    Payload:
    {
        "program_name": "Super 30",
        "code": "HDTN-1A-ZA1",
        "name": "Super 30 - Batch A (2025)",
        "start_date": "2025-01-01",
        "end_date": "2025-03-31"
    }
    
    Returns:
    {
        "id": "uuid",
        "code": "HDTN-1A-ZA1",
        "name": "Super 30 - Batch A (2025)",
        "program": "Super 30"
    }
    """
    is_admin, error_response = _check_admin(request)
    if not is_admin:
        return error_response
    
    admin_user = request.user
    center = admin_user.center
    
    program_name = request.data.get("program_name")
    code = request.data.get("code")
    name = request.data.get("name")
    start_date_str = request.data.get("start_date", "")
    end_date_str = request.data.get("end_date", "")
    
    if not program_name or not code or not name:
        return Response(
            {"detail": "program_name, code, and name are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Find program in admin's center
    try:
        program = Program.objects.get(center=center, name=program_name)
    except Program.DoesNotExist:
        return Response(
            {"detail": f"Program '{program_name}' not found in your center '{center.name}'."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Program.MultipleObjectsReturned:
        return Response(
            {"detail": f"Multiple programs found with name '{program_name}'. Please contact Super Admin."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Check if batch code already exists in this program
    if Batch.objects.filter(program=program, code=code).exists():
        return Response(
            {"detail": f"Batch with code '{code}' already exists in program '{program_name}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Parse dates
    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "start_date must be in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "end_date must be in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    
    try:
        batch = Batch.objects.create(
            program=program,
            code=code,
            name=name,
            start_date=start_date,
            end_date=end_date,
        )
        return Response(
            {
                "id": str(batch.id),
                "code": batch.code,
                "name": batch.name,
                "program": program.name,
                "center": center.name,
                "start_date": str(batch.start_date) if batch.start_date else None,
                "end_date": str(batch.end_date) if batch.end_date else None,
            },
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        return Response(
            {"detail": f"Error creating batch: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def add_student_to_batch(request):
    """
    Admin adds a student to a batch (creates student user if needed, then enrolls).
    
    Payload:
    {
        "batch_code": "HDTN-1A-ZA1",
        "name": "Student Name",
        "email": "student@example.com",
        "phone_number": "9876543210",
        "date_of_birth": "2010-05-15"
    }
    
    Returns:
    {
        "message": "Student added to batch successfully.",
        "username": "STU-HDTN1-1234",
        "password": "Student@HDTN12025",
        "user_id": "uuid",
        "enrollment_id": "uuid",
        "batch": "HDTN-1A-ZA1"
    }
    """
    is_admin, error_response = _check_admin(request)
    if not is_admin:
        return error_response
    
    admin_user = request.user
    center = admin_user.center
    
    batch_code = request.data.get("batch_code")
    name = request.data.get("name")
    email = request.data.get("email", "")
    phone_number = request.data.get("phone_number", "")
    date_of_birth = request.data.get("date_of_birth", "")
    
    if not batch_code or not name:
        return Response(
            {"detail": "batch_code and name are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Find batch in admin's center
    try:
        batch = Batch.objects.get(code=batch_code, program__center=center)
    except Batch.DoesNotExist:
        return Response(
            {"detail": f"Batch with code '{batch_code}' not found in your center."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Batch.MultipleObjectsReturned:
        return Response(
            {"detail": f"Multiple batches found with code '{batch_code}'. Please contact Super Admin."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Generate code and password
    username = generate_user_code(User.ROLE_STUDENT, None, batch_code)
    password = generate_password(
        User.ROLE_STUDENT,
        None,
        batch_code,
        date_of_birth,
    )
    
    # Split name
    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    try:
        with transaction.atomic():
            # Create student user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                role=User.ROLE_STUDENT,
                center=center,
            )
            
            # Enroll student in batch
            enrollment, created = Enrollment.objects.get_or_create(
                student=user,
                batch=batch,
                defaults={"status": Enrollment.STATUS_ACTIVE},
            )
            
            if not created:
                return Response(
                    {"detail": f"Student is already enrolled in batch '{batch_code}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            
            return Response(
                {
                    "message": "Student added to batch successfully.",
                    "username": username,
                    "password": password,
                    "user_id": str(user.id),
                    "enrollment_id": str(enrollment.id),
                    "batch": batch.code,
                    "batch_name": batch.name,
                },
                status=status.HTTP_201_CREATED,
            )
    except Exception as e:
        return Response(
            {"detail": f"Error adding student to batch: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_programs(request):
    """
    List all programs.
    - Super Admin: sees all programs (can filter by center_name)
    - Admin: sees only programs in their center
    
    Query Parameters:
    - center_name (optional): Filter by center name (Super Admin only)
    
    Returns:
    {
        "programs": [
            {
                "id": "uuid",
                "name": "Super 30",
                "center": "Allen - Jaipur Center",
                "description": "...",
                "category": "JEE Prep",
                "is_active": true,
                "batches_count": 5,
                "created_at": "2025-01-01T10:00:00Z"
            }
        ],
        "total": 10
    }
    """
    user = request.user
    center_name = request.query_params.get("center_name", "")
    
    if user.role == User.ROLE_SUPER_ADMIN:
        # Super Admin can see all programs
        programs = Program.objects.all()
        if center_name:
            programs = programs.filter(center__name__icontains=center_name)
    elif user.role == User.ROLE_ADMIN:
        # Admin sees only their center's programs
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        programs = Program.objects.filter(center=user.center)
    else:
        return Response(
            {"detail": "Only Super Admin and Admin can view programs."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    programs = programs.select_related("center").prefetch_related("batches").order_by("center__name", "name")
    
    programs_data = []
    for program in programs:
        programs_data.append({
            "id": str(program.id),
            "name": program.name,
            "center": program.center.name,
            "center_id": str(program.center.id),
            "description": program.description,
            "category": program.category,
            "is_active": program.is_active,
            "batches_count": program.batches.count(),
            "created_at": program.created_at.isoformat(),
            "updated_at": program.updated_at.isoformat(),
        })
    
    return Response(
        {
            "programs": programs_data,
            "total": len(programs_data),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_program(request, program_id: str):
    """
    Get details of a specific program.
    
    Returns:
    {
        "id": "uuid",
        "name": "Super 30",
        "center": "Allen - Jaipur Center",
        "description": "...",
        "category": "JEE Prep",
        "is_active": true,
        "batches_count": 5,
        "created_at": "2025-01-01T10:00:00Z"
    }
    """
    user = request.user
    
    try:
        program = Program.objects.select_related("center").prefetch_related("batches").get(id=program_id)
    except Program.DoesNotExist:
        return Response(
            {"detail": "Program not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only see programs in their center
    if user.role == User.ROLE_ADMIN:
        if not user.center or program.center != user.center:
            return Response(
                {"detail": "You don't have permission to view this program."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role != User.ROLE_SUPER_ADMIN:
        return Response(
            {"detail": "Only Super Admin and Admin can view programs."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    data = {
        "id": str(program.id),
        "name": program.name,
        "center": program.center.name,
        "center_id": str(program.center.id),
        "description": program.description,
        "category": program.category,
        "is_active": program.is_active,
        "batches_count": program.batches.count(),
        "created_at": program.created_at.isoformat(),
        "updated_at": program.updated_at.isoformat(),
    }
    return Response(data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_batches(request):
    """
    List all batches.
    - Super Admin: sees all batches (can filter by program_name or center_name)
    - Admin: sees only batches in their center (can filter by program_name)
    
    Query Parameters:
    - program_name (optional): Filter by program name
    - center_name (optional): Filter by center name (Super Admin only)
    
    Returns:
    {
        "batches": [
            {
                "id": "uuid",
                "code": "HDTN-1A-ZA1",
                "name": "Super 30 - Batch A (2025)",
                "program": "Super 30",
                "center": "Allen - Jaipur Center",
                "start_date": "2025-01-01",
                "end_date": "2025-03-31",
                "students_count": 30,
                "teachers_count": 3,
                "created_at": "2025-01-01T10:00:00Z"
            }
        ],
        "total": 15
    }
    """
    user = request.user
    program_name = request.query_params.get("program_name", "")
    center_name = request.query_params.get("center_name", "")
    
    if user.role == User.ROLE_SUPER_ADMIN:
        # Super Admin can see all batches
        batches = Batch.objects.all()
        if center_name:
            batches = batches.filter(program__center__name__icontains=center_name)
        if program_name:
            batches = batches.filter(program__name__icontains=program_name)
    elif user.role == User.ROLE_ADMIN:
        # Admin sees only batches in their center
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        batches = Batch.objects.filter(program__center=user.center)
        if program_name:
            batches = batches.filter(program__name__icontains=program_name)
    else:
        return Response(
            {"detail": "Only Super Admin and Admin can view batches."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    batches = batches.select_related("program", "program__center").prefetch_related(
        "enrollments", "teachers"
    ).order_by("program__name", "name")
    
    batches_data = []
    for batch in batches:
        batches_data.append({
            "id": str(batch.id),
            "code": batch.code,
            "name": batch.name,
            "program": batch.program.name,
            "program_id": str(batch.program.id),
            "center": batch.program.center.name,
            "center_id": str(batch.program.center.id),
            "start_date": str(batch.start_date) if batch.start_date else None,
            "end_date": str(batch.end_date) if batch.end_date else None,
            "students_count": batch.enrollments.filter(status=Enrollment.STATUS_ACTIVE).count(),
            "teachers_count": batch.teachers.count(),
            "created_at": batch.created_at.isoformat(),
            "updated_at": batch.updated_at.isoformat(),
        })
    
    return Response(
        {
            "batches": batches_data,
            "total": len(batches_data),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_batch(request, batch_id: str):
    """
    Get details of a specific batch.
    
    Returns:
    {
        "id": "uuid",
        "code": "HDTN-1A-ZA1",
        "name": "Super 30 - Batch A (2025)",
        "program": "Super 30",
        "program_id": "uuid",
        "center": "Allen - Jaipur Center",
        "center_id": "uuid",
        "start_date": "2025-01-01",
        "end_date": "2025-03-31",
        "students_count": 30,
        "teachers_count": 3,
        "created_at": "2025-01-01T10:00:00Z"
    }
    """
    user = request.user
    
    try:
        batch = Batch.objects.select_related("program", "program__center").prefetch_related(
            "enrollments", "teachers"
        ).get(id=batch_id)
    except Batch.DoesNotExist:
        return Response(
            {"detail": "Batch not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions: Admin can only see batches in their center
    if user.role == User.ROLE_ADMIN:
        if not user.center or batch.program.center != user.center:
            return Response(
                {"detail": "You don't have permission to view this batch."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role != User.ROLE_SUPER_ADMIN:
        return Response(
            {"detail": "Only Super Admin and Admin can view batches."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    data = {
        "id": str(batch.id),
        "code": batch.code,
        "name": batch.name,
        "program": batch.program.name,
        "program_id": str(batch.program.id),
        "center": batch.program.center.name,
        "center_id": str(batch.program.center.id),
        "start_date": str(batch.start_date) if batch.start_date else None,
        "end_date": str(batch.end_date) if batch.end_date else None,
        "students_count": batch.enrollments.filter(status=Enrollment.STATUS_ACTIVE).count(),
        "teachers_count": batch.teachers.count(),
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
    }
    return Response(data, status=status.HTTP_200_OK)

