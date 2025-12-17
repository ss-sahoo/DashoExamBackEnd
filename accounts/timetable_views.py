"""
Timetable management APIs - Super Admin creates centers, admins, teachers, students.
All these endpoints require Super Admin authentication.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from .models import Institute, Center, Program, Batch, Enrollment, User
from .utils import generate_user_code, generate_password


def _check_super_admin(request):
    """Helper to check if user is super admin (supports both role formats)."""
    if not request.user.is_authenticated:
        return False, Response(
            {"detail": "Authentication required."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    # Support both 'super_admin' and 'SUPER_ADMIN' roles
    if request.user.role not in [User.ROLE_SUPER_ADMIN, 'SUPER_ADMIN']:
        return False, Response(
            {"detail": "Only Super Admin can perform this action."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return True, None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_center(request):
    """
    Super Admin creates a new Center.
    
    Payload:
    {
        "institute_name": "Allen Coaching",  # Will find or create institute
        "name": "Allen - Jaipur Center",
        "city": "Jaipur",
        "address": "Optional address"
    }
    """
    is_super, error_response = _check_super_admin(request)
    if not is_super:
        return error_response
    
    institute_name = request.data.get("institute_name")
    name = request.data.get("name")
    city = request.data.get("city")
    address = request.data.get("address", "")
    
    if not institute_name or not name or not city:
        return Response(
            {"detail": "institute_name, name, and city are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Find or create institute by name
    institute, created = Institute.objects.get_or_create(
        name=institute_name,
        defaults={"head_office_location": city, "contact_email": f"contact@{institute_name.lower().replace(' ', '')}.com"}
    )
    
    try:
        center = Center.objects.create(
            institute=institute,
            name=name,
            city=city,
            address=address,
        )
        return Response(
            {
                "id": str(center.id),
                "name": center.name,
                "city": center.city,
                "institute": institute.name,
            },
            status=status.HTTP_201_CREATED,
        )
    except Exception as e:
        return Response(
            {"detail": f"Error creating center: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_admin(request):
    """
    Super Admin creates a new Admin user for a center.
    
    Auto-generates:
    - username (code): ADM-<center_code>-<3_digits>
    - password: Admin@<center_code><year>
    
    Payload:
    {
        "center_name": "Allen - Jaipur Center",
        "name": "Admin Name",
        "email": "admin@example.com",
        "phone_number": "9876543210"
    }
    
    Returns:
    {
        "username": "ADM-XXXX-123",
        "password": "Admin@XXXX2025",
        "user_id": "uuid"
    }
    """
    is_super, error_response = _check_super_admin(request)
    if not is_super:
        return error_response
    
    center_name = request.data.get("center_name")
    name = request.data.get("name")
    email = request.data.get("email", "")
    phone_number = request.data.get("phone_number", "")
    
    if not center_name or not name:
        return Response(
            {"detail": "center_name and name are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    try:
        center = Center.objects.get(name=center_name)
    except Center.DoesNotExist:
        return Response(
            {"detail": f"Center '{center_name}' not found. Please create the center first."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Center.MultipleObjectsReturned:
        return Response(
            {"detail": f"Multiple centers found with name '{center_name}'. Please use center_id instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Generate code and password - use 'ADMIN' role for timetable system
    center_code = center.name[:4].replace(" ", "").replace("-", "")
    username = generate_user_code('ADMIN', center_code)
    password = generate_password('ADMIN', center_code)
    
    # Split name
    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email or f"{username}@temp.com",
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone_number or "",
                phone_number=phone_number or "",
                role='ADMIN',  # Use timetable role
                center=center,
                institute=center.institute,
            )
            
            # Add admin to center's admins
            center.admins.add(user)
            
            return Response(
                {
                    "message": "Admin created successfully.",
                    "username": username,
                    "password": password,
                    "user_id": str(user.id),
                    "center": center.name,
                },
                status=status.HTTP_201_CREATED,
            )
    except Exception as e:
        return Response(
            {"detail": f"Error creating admin: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _check_admin_or_super(request):
    """Helper to check if user is admin or super admin."""
    if not request.user.is_authenticated:
        return False, None, Response(
            {"detail": "Authentication required."},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    user = request.user
    is_super = user.role in [User.ROLE_SUPER_ADMIN, 'SUPER_ADMIN']
    is_admin = user.role in [User.ROLE_ADMIN, 'ADMIN', 'institute_admin']
    
    if not (is_super or is_admin):
        return False, None, Response(
            {"detail": "Only Admin or Super Admin can perform this action."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    return True, (is_super, is_admin), None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_teacher(request):
    """
    Super Admin or Admin creates a new Teacher user.
    
    - Super Admin: Can create teacher in any center (must provide center_name)
    - Admin: Can create teacher in their own center (center_name optional)
    
    Auto-generates:
    - username (code): TCH-<center_code>-<3_digits>
    - password: Teacher@<center_code><year>
    - teacher_code: Same as username
    
    Payload:
    {
        "center_name": "Allen - Jaipur Center",  # Required for Super Admin, optional for Admin
        "name": "Teacher Name",
        "email": "teacher@example.com",
        "phone_number": "9876543210",
        "employee_id": "EMP-001",
        "subjects": "Physics, Chemistry"
    }
    
    Returns:
    {
        "username": "TCH-XXXX-123",
        "password": "Teacher@XXXX2025",
        "teacher_code": "TCH-XXXX-123",
        "user_id": "uuid"
    }
    """
    can_proceed, role_info, error_response = _check_admin_or_super(request)
    if not can_proceed:
        return error_response
    
    is_super, is_admin = role_info
    user = request.user
    
    center_name = request.data.get("center_name")
    name = request.data.get("name")
    email = request.data.get("email", "")
    phone_number = request.data.get("phone_number", "")
    employee_id = request.data.get("employee_id", "")
    subjects = request.data.get("subjects", "")
    
    if not name:
        return Response(
            {"detail": "name is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Determine center
    if is_super:
        # Super Admin must provide center_name
        if not center_name:
            return Response(
                {"detail": "center_name is required for Super Admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            center = Center.objects.get(name=center_name)
        except Center.DoesNotExist:
            return Response(
                {"detail": f"Center '{center_name}' not found. Please create the center first."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Center.MultipleObjectsReturned:
            return Response(
                {"detail": f"Multiple centers found with name '{center_name}'. Please use center_id instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        # Admin uses their own center
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        center = user.center
    
    # Generate code and password
    center_code = center.name[:4].replace(" ", "").replace("-", "")
    username = generate_user_code('TEACHER', center_code)
    password = generate_password('TEACHER', center_code)
    teacher_code = username  # Use same code
    
    # Split name
    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email or f"{username}@temp.com",
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone_number or "",
                phone_number=phone_number or "",
                role='teacher',  # Use exam role format (compatible with both)
                center=center,
                institute=center.institute,
                teacher_code=teacher_code,
                teacher_employee_id=employee_id,
                teacher_subjects=subjects,
            )
            
            return Response(
                {
                    "message": "Teacher created successfully.",
                    "username": username,
                    "password": password,
                    "teacher_code": teacher_code,
                    "user_id": str(user.id),
                    "center": center.name,
                },
                status=status.HTTP_201_CREATED,
            )
    except Exception as e:
        return Response(
            {"detail": f"Error creating teacher: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_student(request):
    """
    Super Admin or Admin creates a new Student user.
    
    - Super Admin: Can create student in any batch
    - Admin: Can create student in batches from their center
    
    Auto-generates:
    - username (code): STU-<batch_code>-<4_digits>
    - password: Student@<batch_code><year> or Student@<dob_year>
    
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
        "username": "STU-XXXX-1234",
        "password": "Student@XXXX2025",
        "user_id": "uuid"
    }
    """
    can_proceed, role_info, error_response = _check_admin_or_super(request)
    if not can_proceed:
        return error_response
    
    is_super, is_admin = role_info
    user = request.user
    
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
    
    try:
        batch = Batch.objects.select_related('program', 'program__center').get(code=batch_code)
        center = batch.program.center
    except Batch.DoesNotExist:
        return Response(
            {"detail": f"Batch with code '{batch_code}' not found. Please create the batch first."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except Batch.MultipleObjectsReturned:
        return Response(
            {"detail": f"Multiple batches found with code '{batch_code}'. Please use batch_id instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Check permissions: Admin can only create students in their center's batches
    if is_admin:
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if center != user.center:
            return Response(
                {"detail": f"You can only create students in batches from your center '{user.center.name}'."},
                status=status.HTTP_403_FORBIDDEN,
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
            
            # Auto-enroll student in the batch
            Enrollment.objects.get_or_create(
                student=user,
                batch=batch,
                defaults={'status': Enrollment.STATUS_ACTIVE}
            )
            
            return Response(
                {
                    "message": "Student created successfully.",
                    "username": username,
                    "password": password,
                    "user_id": str(user.id),
                    "batch": batch.code,
                    "center": center.name,
                },
                status=status.HTTP_201_CREATED,
            )
    except Exception as e:
        return Response(
            {"detail": f"Error creating student: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_staff(request):
    """
    Super Admin or Admin creates a new Staff user.
    
    - Super Admin: Can create staff in any center (must provide center_name)
    - Admin: Can create staff in their own center (center_name optional)
    
    Auto-generates:
    - username (code): STF-<center_code>-<3_digits>
    - password: Staff@<center_code><year>
    
    Payload:
    {
        "center_name": "Allen - Jaipur Center",  # Required for Super Admin, optional for Admin
        "name": "Staff Name",
        "email": "staff@example.com",
        "phone_number": "9876543210"
    }
    
    Returns:
    {
        "username": "STF-XXXX-123",
        "password": "Staff@XXXX2025",
        "user_id": "uuid"
    }
    """
    can_proceed, role_info, error_response = _check_admin_or_super(request)
    if not can_proceed:
        return error_response
    
    is_super, is_admin = role_info
    user = request.user
    
    center_name = request.data.get("center_name")
    name = request.data.get("name")
    email = request.data.get("email", "")
    phone_number = request.data.get("phone_number", "")
    
    if not name:
        return Response(
            {"detail": "name is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Determine center
    if is_super:
        # Super Admin must provide center_name
        if not center_name:
            return Response(
                {"detail": "center_name is required for Super Admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            center = Center.objects.get(name=center_name)
        except Center.DoesNotExist:
            return Response(
                {"detail": f"Center '{center_name}' not found. Please create the center first."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Center.MultipleObjectsReturned:
            return Response(
                {"detail": f"Multiple centers found with name '{center_name}'. Please use center_id instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        # Admin uses their own center
        if not user.center:
            return Response(
                {"detail": "Admin user is not linked to any center."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        center = user.center
    
    # Generate code and password
    center_code = center.name[:4].replace(" ", "").replace("-", "")
    username = generate_user_code('STAFF', center_code)
    password = generate_password('STAFF', center_code)
    
    # Split name
    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    try:
        with transaction.atomic():
            user_obj = User.objects.create_user(
                username=username,
                email=email or f"{username}@temp.com",
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone=phone_number or "",
                phone_number=phone_number or "",
                role=User.ROLE_STAFF,  # Use timetable role
                center=center,
                institute=center.institute,
            )
            
            return Response(
                {
                    "message": "Staff created successfully.",
                    "username": username,
                    "password": password,
                    "user_id": str(user_obj.id),
                    "center": center.name,
                },
                status=status.HTTP_201_CREATED,
            )
    except Exception as e:
        return Response(
            {"detail": f"Error creating staff: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

