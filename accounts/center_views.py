"""
GET APIs for Centers, Batches, Users, and Timetables
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Q
from .models import Center, Batch, Program, User
from timetable.models import Timetable


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_centers(request):
    """
    GET /api/timetable/centers/
    
    List all centers. 
    - Super Admin: sees all centers
    - Admin: sees only their center
    - Others: sees all centers (or can be restricted)
    
    Query params:
    - institute_id: Filter by institute
    - city: Filter by city
    - search: Search by name
    """
    user = request.user
    
    # Base queryset
    centers = Center.objects.select_related('institute').all()
    
    # Filter by role - Admins see only their center, Super Admins see all
    if user.role in ['admin', 'ADMIN', 'institute_admin'] and user.center:
        centers = centers.filter(id=user.center.id)
    
    # Query filters
    institute_id = request.query_params.get('institute_id')
    
    # If user has an institute, they should only see centers for that institute
    # unless they are a global super admin (no institute assigned)
    effective_institute_id = institute_id or getattr(user, 'institute_id', None)
    
    if effective_institute_id:
        centers = centers.filter(institute_id=effective_institute_id)
    
    city = request.query_params.get('city')
    if city:
        centers = centers.filter(city__icontains=city)
    
    search = request.query_params.get('search')
    if search:
        centers = centers.filter(name__icontains=search)
    
    # Serialize
    centers_data = []
    for center in centers:
        # Count admins for this center (exclude super admins)
        admin_count = User.objects.filter(
            center=center,
            role__in=['admin', 'ADMIN', 'institute_admin']
        ).exclude(
            role__in=['super_admin', 'SUPER_ADMIN']
        ).count()
        
        centers_data.append({
            "id": str(center.id),
            "name": center.name,
            "city": center.city,
            "address": center.address,
            "institute": {
                "id": center.institute.id,
                "name": center.institute.name,
            },
            "admin_count": admin_count,
            "created_at": center.created_at.isoformat() if hasattr(center, 'created_at') else None,
        })
    
    return Response(
        {
            "count": len(centers_data),
            "results": centers_data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_center(request, center_id: str):
    """
    GET /api/timetable/centers/<center_id>/
    
    Get details of a specific center.
    """
    try:
        center = Center.objects.select_related('institute').get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {"detail": "Center not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions - Admins can only access their center, Super Admins can access all
    user = request.user
    if user.role in ['admin', 'ADMIN', 'institute_admin'] and user.center and user.center.id != center.id:
        return Response(
            {"detail": "You can only access your own center."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    return Response(
        {
            "id": str(center.id),
            "name": center.name,
            "city": center.city,
            "address": center.address,
            "institute": {
                "id": center.institute.id,
                "name": center.institute.name,
                "head_office_location": center.institute.head_office_location,
            },
            "created_at": center.created_at.isoformat() if hasattr(center, 'created_at') else None,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_center_programs(request, center_id: str):
    """
    GET /api/timetable/centers/<center_id>/programs/
    
    List all programs in a center.
    
    Query params:
    - search: Search by program name
    - is_active: Filter by active status (true/false)
    """
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {"detail": "Center not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions - Admins can only access their center, Super Admins can access all
    user = request.user
    if user.role in ['admin', 'ADMIN', 'institute_admin'] and user.center and user.center.id != center.id:
        return Response(
            {"detail": "You can only access your own center."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Get programs in this center
    programs = Program.objects.filter(center=center).select_related('center')
    
    # Query filters
    search = request.query_params.get('search')
    if search:
        programs = programs.filter(name__icontains=search)
    
    is_active = request.query_params.get('is_active')
    if is_active is not None:
        is_active_bool = is_active.lower() == 'true'
        programs = programs.filter(is_active=is_active_bool)
    
    # Serialize
    programs_data = []
    for program in programs:
        programs_data.append({
            "id": str(program.id),
            "name": program.name,
            "description": program.description,
            "category": program.category,
            "is_active": program.is_active,
            "batches_count": program.batches.count(),
            "created_at": program.created_at.isoformat() if hasattr(program, 'created_at') else None,
        })
    
    return Response(
        {
            "center_id": str(center.id),
            "center_name": center.name,
            "count": len(programs_data),
            "results": programs_data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_center_batches(request, center_id: str):
    """
    GET /api/timetable/centers/<center_id>/batches/
    
    List all batches in a center.
    
    Query params:
    - program_id: Filter by program
    - search: Search by batch code or name
    """
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {"detail": "Center not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions - Admins can only access their center, Super Admins can access all
    user = request.user
    if user.role in ['admin', 'ADMIN', 'institute_admin'] and user.center and user.center.id != center.id:
        return Response(
            {"detail": "You can only access your own center."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    try:
        # Get batches in this center - use direct center field only
        # Note: Program model doesn't have a center field, it has institute field
        batches = Batch.objects.filter(center=center).select_related('program')
        
        # Query filters
        program_id = request.query_params.get('program_id')
        if program_id:
            batches = batches.filter(program_id=program_id)
        
        search = request.query_params.get('search')
        if search:
            batches = batches.filter(
                Q(code__icontains=search) | Q(name__icontains=search)
            )
        
        # Serialize
        batches_data = []
        for batch in batches:
            try:
                student_count = batch.enrollments.filter(status='ACTIVE').count() if hasattr(batch, 'enrollments') else 0
            except Exception:
                student_count = 0
            
            try:
                teacher_count = batch.teachers.count() if hasattr(batch, 'teachers') else 0
            except Exception:
                teacher_count = 0
            
            batch_data = {
                "id": str(batch.id),
                "code": batch.code,
                "name": batch.name,
                "start_date": str(batch.start_date) if batch.start_date else None,
                "end_date": str(batch.end_date) if batch.end_date else None,
                "program": None,
                "student_count": student_count,
                "teacher_count": teacher_count,
                "created_at": batch.created_at.isoformat() if hasattr(batch, 'created_at') else None,
            }
            
            if batch.program:
                batch_data["program"] = {
                    "id": str(batch.program.id),
                    "name": batch.program.name,
                }
            
            batches_data.append(batch_data)
        
        return Response(
            {
                "center_id": str(center.id),
                "center_name": center.name,
                "count": len(batches_data),
                "results": batches_data,
            },
            status=status.HTTP_200_OK,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error listing center batches: {e}")
        return Response(
            {"detail": f"Error fetching batches: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_center_users(request, center_id: str):
    """
    GET /api/timetable/centers/<center_id>/users/
    
    List all users in a center.
    
    Query params:
    - role: Filter by role (admin, teacher, student, staff)
    - search: Search by username, email, or name
    """
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {"detail": "Center not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions - Admins can only access their center, Super Admins can access all
    user = request.user
    if user.role in ['admin', 'ADMIN', 'institute_admin'] and user.center and user.center.id != center.id:
        return Response(
            {"detail": "You can only access your own center."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Get users in this center
    users = User.objects.filter(center=center)
    
    # Query filters
    role = request.query_params.get('role')
    if role:
        users = users.filter(role=role)
        # Exclude FREE virtual teachers from teacher list
        if role.lower() == 'teacher':
            users = users.exclude(teacher_code__istartswith='FREE')
            users = users.exclude(teacher_subjects__iexact='FREE')
    
    search = request.query_params.get('search')
    if search:
        users = users.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )
    
    # Serialize
    users_data = []
    for user_obj in users:
        user_data = {
            "id": str(user_obj.id),
            "username": user_obj.username,
            "email": user_obj.email,
            "first_name": user_obj.first_name,
            "last_name": user_obj.last_name,
            "role": user_obj.role,
            "is_active": user_obj.is_active,
        }
        
        # Add role-specific fields
        if user_obj.role in ['teacher', 'TEACHER']:
            user_data.update({
                "teacher_code": user_obj.teacher_code,
                "teacher_subjects": user_obj.teacher_subjects,
                "teacher_employee_id": user_obj.teacher_employee_id,
            })
        elif user_obj.role in ['student', 'STUDENT']:
            user_data.update({
                "student_code": getattr(user_obj, 'student_code', None),
            })
        
        users_data.append(user_data)
    
    return Response(
        {
            "center_id": str(center.id),
            "center_name": center.name,
            "count": len(users_data),
            "results": users_data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_center_timetables(request, center_id: str):
    """
    GET /api/timetable/centers/<center_id>/timetables/
    
    List all timetables in a center.
    
    Query params:
    - is_active: Filter by active status (true/false)
    - from_date: Filter by from_date (YYYY-MM-DD)
    - to_date: Filter by to_date (YYYY-MM-DD)
    """
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {"detail": "Center not found."},
            status=status.HTTP_404_NOT_FOUND,
        )
    
    # Check permissions - Admins can only access their center, Super Admins can access all
    user = request.user
    if user.role in ['admin', 'ADMIN', 'institute_admin'] and user.center and user.center.id != center.id:
        return Response(
            {"detail": "You can only access your own center."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    # Get timetables in this center
    timetables = Timetable.objects.filter(center=center)
    
    # Query filters
    is_active = request.query_params.get('is_active')
    if is_active is not None:
        is_active_bool = is_active.lower() == 'true'
        timetables = timetables.filter(is_active=is_active_bool)
    
    from_date = request.query_params.get('from_date')
    if from_date:
        timetables = timetables.filter(from_date__gte=from_date)
    
    to_date = request.query_params.get('to_date')
    if to_date:
        timetables = timetables.filter(to_date__lte=to_date)
    
    # Order by date
    timetables = timetables.order_by('-from_date', '-to_date')
    
    # Serialize
    timetables_data = []
    for timetable in timetables:
        timetables_data.append({
            "id": str(timetable.id),
            "name": timetable.name,
            "description": timetable.description,
            "from_date": str(timetable.from_date),
            "to_date": str(timetable.to_date),
            "is_active": timetable.is_active,
            "created_at": timetable.created_at.isoformat() if hasattr(timetable, 'created_at') else None,
        })
    
    return Response(
        {
            "center_id": str(center.id),
            "center_name": center.name,
            "count": len(timetables_data),
            "results": timetables_data,
        },
        status=status.HTTP_200_OK,
    )
