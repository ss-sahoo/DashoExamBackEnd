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
from .models import Center, Program, Batch, Enrollment, User
from .utils import generate_user_code, generate_password
from .timetable_views import _get_center_by_name_or_id


def _check_super_admin(request):
    """Helper to check if user is super admin (supports both role formats)."""
    if not request.user.is_authenticated:
        return False, Response(
            {"detail": "Authentication required."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    # Support both lowercase and uppercase variants
    if request.user.role not in ['super_admin', 'SUPER_ADMIN']:
        return False, Response(
            {"detail": "Only Super Admin can perform this action."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return True, None


def _check_admin(request):
    """Helper to check if user is admin (supports both role formats)."""
    if not request.user.is_authenticated:
        return False, Response(
            {"detail": "Authentication required."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    # Support both lowercase and uppercase roles
    if request.user.role not in ['admin', 'ADMIN', 'institute_admin']:
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
        "center_name": "Allen - Jaipur Center",  # OR use "center_id": "uuid"
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
    center_id = request.data.get("center_id")
    name = request.data.get("name")
    description = request.data.get("description", "")
    category = request.data.get("category", "")
    
    if not name:
        return Response(
            {"detail": "name is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    if not center_name and not center_id:
        return Response(
            {"detail": "Either center_name or center_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Find center by ID (preferred) or name
    center, error_response = _get_center_by_name_or_id(center_name=center_name, center_id=center_id)
    if error_response:
        return error_response
    
    # Check if program already exists for this center
    # Program is linked to Institute, not Center directly
    # Get the institute from the center
    if Program.objects.filter(institute=center.institute, name=name).exists():
        return Response(
            {"detail": f"Program '{name}' already exists for center '{center_name}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    try:
        program = Program.objects.create(
            institute=center.institute,
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
    Admin or Super Admin creates a new Batch (optionally under a program) in their center.
    
    Payload:
    {
        "program_id": "uuid",        # Optional - use either program_id or program_name
        "program_name": "Super 30",  # Optional - if not provided, batch created without program
        "code": "HDTN-1A-ZA1",       # Required
        "name": "Super 30 - Batch A (2025)",  # Optional - auto-generated from code if not provided
        "start_date": "2025-01-01",  # Optional
        "end_date": "2025-03-31"     # Optional
    }
    
    Returns:
    {
        "id": "uuid",
        "code": "HDTN-1A-ZA1",
        "name": "Super 30 - Batch A (2025)",
        "program": "Super 30",
        "program_id": "uuid",
        "center": "Allen - Jaipur Center",
        "center_id": "uuid"
    }
    """
    user = request.user
    
    # Allow both Admin and Super Admin to create batches
    if user.role in ['super_admin', 'SUPER_ADMIN']:
        # Super admin can create batch in any center (must specify center)
        center_id = request.data.get("center_id")
        center_name = request.data.get("center_name")
        
        if not center_id and not center_name:
            # If no center specified, try to use user's center if they have one
            if user.center:
                center = user.center
            else:
                return Response(
                    {"detail": "Super Admin must provide center_id or center_name, or be assigned to a center."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            center, error_response = _get_center_by_name_or_id(center_name=center_name, center_id=center_id)
            if error_response:
                return error_response
    elif user.role in ['admin', 'ADMIN', 'institute_admin']:
        # Admin can only create in their center
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        center = user.center
    else:
        return Response(
            {"detail": "Only Admin and Super Admin can create batches."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    program_id = request.data.get("program_id")
    program_name = request.data.get("program_name")
    code = request.data.get("code")
    name = request.data.get("name")
    start_date_str = request.data.get("start_date", "")
    end_date_str = request.data.get("end_date", "")
    
    if not code:
        return Response(
            {"detail": "code is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Auto-generate name from code if not provided
    if not name:
        name = f"Batch {code}"
    
    # Find program in center (optional) - support both program_id and program_name
    program = None
    if program_id:
        try:
            program = Program.objects.get(id=program_id, institute=center.institute)
        except Program.DoesNotExist:
            return Response(
                {"detail": f"Program with id '{program_id}' not found in center '{center.name}'."},
                status=status.HTTP_404_NOT_FOUND,
            )
    elif program_name:
        try:
            program = Program.objects.get(institute=center.institute, name=program_name)
        except Program.DoesNotExist:
            return Response(
                {"detail": f"Program '{program_name}' not found in center '{center.name}'."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Program.MultipleObjectsReturned:
            return Response(
                {"detail": f"Multiple programs found with name '{program_name}'. Please use program_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    
    # Check if batch code already exists
    if program:
        if Batch.objects.filter(program=program, code=code).exists():
            return Response(
                {"detail": f"Batch with code '{code}' already exists in program '{program_name}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        # Check if batch code exists without program in this center
        if Batch.objects.filter(program__isnull=True, code=code).exists():
            return Response(
                {"detail": f"Batch with code '{code}' already exists."},
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
            center=center,
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
                "program": program.name if program else None,
                "program_id": str(program.id) if program else None,
                "center": center.name,
                "center_id": str(center.id),
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
    
    # Find batch in admin's center (using direct center field)
    try:
        batch = Batch.objects.get(code=batch_code, center=center)
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
    username = generate_user_code('STUDENT', None, batch_code)
    password = generate_password('STUDENT', None, batch_code, date_of_birth)
    
    # Split name
    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    try:
        with transaction.atomic():
            # Create student user
            user = User.objects.create_user(
                username=username,
                email=email or f"{username}@temp.com",
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone_number or "",
                phone_number=phone_number or "",
                role='student',  # Use exam role format (compatible with both)
                center=center,
                institute=center.institute,
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
        "programs": [...],
        "total": 10
    }
    """
    user = request.user
    center_name = request.query_params.get("center_name", "")
    
    # Support both role formats
    if user.role in ['super_admin', 'SUPER_ADMIN']:
        programs = Program.objects.all()
        if center_name:
            programs = programs.filter(center__name__icontains=center_name)
    elif user.role in ['admin', 'ADMIN', 'institute_admin']:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Programs are at Institute level; filter by user's center's institute
        programs = Program.objects.filter(institute=user.center.institute)
    else:
        return Response(
            {"detail": "Only Super Admin and Admin can view programs."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    programs = programs.select_related("institute").prefetch_related("batches").order_by("institute__name", "name")
    
    programs_data = []
    for program in programs:
        programs_data.append({
            "id": str(program.id),
            "name": program.name,
            "institute": program.institute.name,
            "institute_id": str(program.institute.id),
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
    """Get details of a specific program."""
    user = request.user
    
    try:
        program = Program.objects.select_related("center").prefetch_related("batches").get(id=program_id)
    except Program.DoesNotExist:
        return Response(
            {"detail": "Program not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions
    if user.role in ['admin', 'ADMIN', 'institute_admin']:
        if not user.center or program.institute != user.center.institute:
            return Response(
                {"detail": "You don't have permission to view this program."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role not in ['super_admin', 'SUPER_ADMIN']:
        return Response(
            {"detail": "Only Super Admin and Admin can view programs."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    data = {
        "id": str(program.id),
        "name": program.name,
        "institute": program.institute.name,
        "institute_id": str(program.institute.id),
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
    """List all batches."""
    user = request.user
    program_name = request.query_params.get("program_name", "")
    center_name = request.query_params.get("center_name", "")
    center_id = request.query_params.get("center_id", "")
    
    if user.role in ['super_admin', 'SUPER_ADMIN']:
        batches = Batch.objects.all()
        if center_id:
            from django.db.models import Q
            # Show batches for the selected center ONLY
            batches = batches.filter(center__id=center_id)
        elif center_name:
            from django.db.models import Q
            # Filter by direct center field
            batches = batches.filter(center__name__icontains=center_name)
        
        if program_name:
            batches = batches.filter(program__name__icontains=program_name)
    elif user.role in ['admin', 'ADMIN', 'institute_admin']:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Include batches in user's center OR batches with program in user's institute
        from django.db.models import Q
        batches = Batch.objects.filter(
            Q(center=user.center) | Q(program__institute=user.center.institute) | Q(program__isnull=True, center=user.center)
        )
        if program_name:
            batches = batches.filter(program__name__icontains=program_name)
    elif user.role in ['teacher', 'TEACHER']:
        # Teachers see batches they are assigned to
        batches = Batch.objects.filter(teachers=user)
        if program_name:
            batches = batches.filter(program__name__icontains=program_name)
    elif user.role in ['student', 'STUDENT']:
        # Students see only batches they are enrolled in
        batches = Batch.objects.filter(
            enrollments__student=user,
            enrollments__status=Enrollment.STATUS_ACTIVE
        )
    else:
        return Response(
            {"detail": "You do not have permission to view batches."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Batch has direct center field; program has institute
    batches = batches.select_related("program", "program__institute", "center").prefetch_related(
        "enrollments", "teachers"
    ).order_by("program__name", "name")
    
    batches_data = []
    for batch in batches:
        # Use batch.center directly if available, otherwise fall back to program's institute
        center_name = batch.center.name if batch.center else None
        center_id = str(batch.center.id) if batch.center else None
        
        batches_data.append({
            "id": str(batch.id),
            "code": batch.code,
            "name": batch.name,
            "program": batch.program.name if batch.program else None,
            "program_id": str(batch.program.id) if batch.program else None,
            "center": center_name,
            "center_id": center_id,
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
    """Get details of a specific batch."""
    user = request.user
    
    try:
        batch = Batch.objects.select_related("program", "program__institute", "center").prefetch_related(
            "enrollments", "teachers"
        ).get(id=batch_id)
    except Batch.DoesNotExist:
        return Response(
            {"detail": "Batch not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions
    if user.role in ['admin', 'ADMIN', 'institute_admin']:
        # Check if batch belongs to user's center
        batch_center = batch.center
        if not user.center or batch_center != user.center:
            return Response(
                {"detail": "You don't have permission to view this batch."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role not in ['super_admin', 'SUPER_ADMIN']:
        return Response(
            {"detail": "Only Super Admin and Admin can view batches."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Use batch.center directly
    center_name = batch.center.name if batch.center else None
    center_id = str(batch.center.id) if batch.center else None
    
    data = {
        "id": str(batch.id),
        "code": batch.code,
        "name": batch.name,
        "program": batch.program.name if batch.program else None,
        "program_id": str(batch.program.id) if batch.program else None,
        "center": center_name,
        "center_id": center_id,
        "start_date": str(batch.start_date) if batch.start_date else None,
        "end_date": str(batch.end_date) if batch.end_date else None,
        "students_count": batch.enrollments.filter(status=Enrollment.STATUS_ACTIVE).count(),
        "teachers_count": batch.teachers.count(),
        "created_at": batch.created_at.isoformat(),
        "updated_at": batch.updated_at.isoformat(),
    }
    return Response(data, status=status.HTTP_200_OK)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_teachers_in_center(request):
    """
    Get all teachers in a center.
    - Super Admin: can specify center_name or center_id to get teachers from any center
    - Admin: gets teachers only from their own center
    
    Query Parameters:
    - center_name (optional): Filter by center name (Super Admin only)
    - center_id (optional): Filter by center ID (Super Admin only)
    
    Returns:
    {
        "teachers": [
            {
                "id": "uuid",
                "username": "teacher@example.com",
                "email": "teacher@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "full_name": "John Doe",
                "teacher_code": "JD-PHY",
                "teacher_employee_id": "EMP-001",
                "teacher_subjects": "Physics, Mathematics",
                "phone": "+1234567890",
                "center": "Allen - Jaipur Center",
                "center_id": "uuid",
                "is_active": true,
                "created_at": "2025-01-01T00:00:00Z"
            }
        ],
        "total": 10,
        "center": "Allen - Jaipur Center"
    }
    """
    user = request.user
    center_name = request.query_params.get("center_name", "")
    center_id = request.query_params.get("center_id", "")
    
    # Determine which center to query
    if user.role in ['super_admin', 'SUPER_ADMIN']:
        # Super admin can query any center
        if center_id:
            try:
                center = Center.objects.get(id=center_id)
            except Center.DoesNotExist:
                return Response(
                    {"detail": f"Center with ID '{center_id}' not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        elif center_name:
            try:
                center = Center.objects.get(name__iexact=center_name)
            except Center.DoesNotExist:
                return Response(
                    {"detail": f"Center '{center_name}' not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            except Center.MultipleObjectsReturned:
                return Response(
                    {"detail": f"Multiple centers found with name '{center_name}'. Please use center_id."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            return Response(
                {"detail": "Super Admin must provide center_name or center_id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    elif user.role in ['admin', 'ADMIN', 'institute_admin']:
        # Admin can only query their own center
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        center = user.center
    else:
        return Response(
            {"detail": "Only Super Admin and Admin can view teachers."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Get all teachers in the center (exclude FREE virtual teachers)
    teachers = User.objects.filter(
        center=center,
        role__in=['teacher', 'TEACHER']
    ).exclude(
        teacher_code__istartswith='FREE'  # Exclude FREE, FREE1, FREE2, etc.
    ).exclude(
        teacher_subjects__iexact='FREE'  # Also exclude by subject
    ).order_by('first_name', 'last_name')
    
    teachers_data = []
    for teacher in teachers:
        teachers_data.append({
            "id": str(teacher.id),
            "username": teacher.username,
            "email": teacher.email,
            "first_name": teacher.first_name,
            "last_name": teacher.last_name,
            "full_name": teacher.get_full_name(),
            "teacher_code": teacher.teacher_code or "",
            "teacher_employee_id": teacher.teacher_employee_id or "",
            "teacher_subjects": teacher.teacher_subjects or "",
            "phone": teacher.phone or teacher.phone_number or "",
            "center": center.name,
            "center_id": str(center.id),
            "is_active": teacher.is_active,
            "created_at": teacher.created_at.isoformat(),
        })
    
    return Response(
        {
            "teachers": teachers_data,
            "total": len(teachers_data),
            "center": center.name,
            "center_id": str(center.id),
        },
        status=status.HTTP_200_OK,
    )

@api_view(["PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def update_batch(request, batch_id):
    """
    Update a batch.
    - Admin (own center) or Super Admin.
    """
    user = request.user
    
    try:
        batch = Batch.objects.get(id=batch_id)
    except Batch.DoesNotExist:
        return Response(
            {"detail": "Batch not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Permission check
    if user.role in ['admin', 'ADMIN', 'institute_admin']:
        if not user.center or batch.center != user.center:
            return Response(
                {"detail": "You don't have permission to update this batch."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role not in ['super_admin', 'SUPER_ADMIN']:
        return Response(
            {"detail": "Only Admin and Super Admin can update batches."},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Fields to update
    name = request.data.get("name")
    start_date_str = request.data.get("start_date")
    end_date_str = request.data.get("end_date")
    program_id = request.data.get("program_id")

    if name:
        batch.name = name

    if start_date_str:
        try:
            batch.start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "start_date must be in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    
    if end_date_str:
        try:
            batch.end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "end_date must be in YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    if program_id:
        try:
            program = Program.objects.get(id=program_id)
            # Ensure program belongs to same institute
            if batch.center and program.institute != batch.center.institute:
                 return Response(
                    {"detail": "Program does not belong to the same institute as the batch."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            batch.program = program
        except Program.DoesNotExist:
             return Response(
                {"detail": "Program not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    batch.save()

    return Response(
        {
            "id": str(batch.id),
            "name": batch.name,
            "start_date": str(batch.start_date) if batch.start_date else None,
            "end_date": str(batch.end_date) if batch.end_date else None,
            "program_id": str(batch.program.id) if batch.program else None,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_batch(request, batch_id):
    """
    Delete a batch.
    """
    user = request.user
    
    try:
        batch = Batch.objects.get(id=batch_id)
    except Batch.DoesNotExist:
        return Response(
            {"detail": "Batch not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Permission check
    if user.role in ['admin', 'ADMIN', 'institute_admin']:
        if not user.center or batch.center != user.center:
            return Response(
                {"detail": "You don't have permission to delete this batch."},
                status=status.HTTP_403_FORBIDDEN,
            )
    elif user.role not in ['super_admin', 'SUPER_ADMIN']:
        return Response(
            {"detail": "Only Admin and Super Admin can delete batches."},
            status=status.HTTP_403_FORBIDDEN,
        )

    batch.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
