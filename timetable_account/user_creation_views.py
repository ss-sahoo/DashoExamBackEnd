"""
APIs for Super Admin to create Centers, Admins, Teachers, and Students.

All these endpoints require Super Admin authentication.
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from timetable_account.models import Institute, Center, Program, Batch, User
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
        defaults={"head_office_location": city}  # Use city as default location
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
        "center_name": "Allen - Jaipur Center",  # Will find center by name
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
    
    # Generate code and password
    center_code = center.name[:4].replace(" ", "").replace("-", "")
    username = generate_user_code(User.ROLE_ADMIN, center_code)
    password = generate_password(User.ROLE_ADMIN, center_code)
    
    # Split name
    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                role=User.ROLE_ADMIN,
                center=center,
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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_teacher(request):
    """
    Super Admin creates a new Teacher user.
    
    Auto-generates:
    - username (code): TCH-<center_code>-<3_digits>
    - password: Teacher@<center_code><year>
    - teacher_code: Same as username
    
    Payload:
    {
        "center_name": "Allen - Jaipur Center",  # Will find center by name
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
    is_super, error_response = _check_super_admin(request)
    if not is_super:
        return error_response
    
    center_name = request.data.get("center_name")
    name = request.data.get("name")
    email = request.data.get("email", "")
    phone_number = request.data.get("phone_number", "")
    employee_id = request.data.get("employee_id", "")
    subjects = request.data.get("subjects", "")
    
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
    
    # Generate code and password
    center_code = center.name[:4].replace(" ", "").replace("-", "")
    username = generate_user_code(User.ROLE_TEACHER, center_code)
    password = generate_password(User.ROLE_TEACHER, center_code)
    teacher_code = username  # Use same code
    
    # Split name
    name_parts = name.strip().split()
    first_name = name_parts[0] if name_parts else name
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                phone_number=phone_number,
                role=User.ROLE_TEACHER,
                center=center,
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
    Super Admin creates a new Student user.
    
    Auto-generates:
    - username (code): STU-<batch_code>-<4_digits>
    - password: Student@<batch_code><year> or Student@<dob_year>
    
    Payload:
    {
        "batch_code": "HDTN-1A-ZA1",  # Will find batch by code
        "name": "Student Name",
        "email": "student@example.com",
        "phone_number": "9876543210",
        "date_of_birth": "2010-05-15"  # Optional, for password generation
    }
    
    Returns:
    {
        "username": "STU-XXXX-1234",
        "password": "Student@XXXX2025",
        "user_id": "uuid"
    }
    """
    is_super, error_response = _check_super_admin(request)
    if not is_super:
        return error_response
    
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
        batch = Batch.objects.get(code=batch_code)
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
    
    # Generate code and password
    batch_code = batch.code
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

