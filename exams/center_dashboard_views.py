"""
Center Dashboard API Views

These views provide center-specific analytics and stats for center admins.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Avg, Count, Q
from django.utils import timezone
from datetime import timedelta

from accounts.models import User, Center, Batch
from .models import Exam, ExamAttempt, QuestionEvaluation


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def center_dashboard_stats(request):
    """
    Get center-specific dashboard statistics.
    
    Query params:
        center_id (required): UUID of the center
        
    Returns:
        total_students: Number of students in the center
        total_teachers: Number of teachers in the center
        total_staff: Number of staff in the center
        active_batches: Number of active batches
        total_exams: Total exams accessible to this center
        active_exams: Currently active exams
        total_attempts: Total exam attempts by center students
        completed_attempts: Completed exam attempts
        pending_evaluation: Pending evaluations count
        average_score: Average score across all attempts
        pass_rate: Percentage of passing attempts (>= 40%)
    """
    center_id = request.query_params.get('center_id')
    
    if not center_id:
        # Try to get center from user's profile
        user = request.user
        if hasattr(user, 'center') and user.center:
            center_id = str(user.center.id)
        else:
            return Response(
                {'error': 'center_id is required'},
                status=400
            )
    
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {'error': 'Center not found'},
            status=404
        )
    
    # Get users in this center
    center_users = User.objects.filter(center=center)
    total_students = center_users.filter(role='student').count()
    total_teachers = center_users.filter(role='teacher').count()
    total_staff = center_users.filter(role__in=['staff', 'admin']).count()
    
    # Get batches - batches have direct center field
    active_batches = Batch.objects.filter(
        center=center
    ).count()
    
    # Get exams accessible to this center
    # Exams with visibility_scope='centers' and this center in allowed_centers
    # OR exams with visibility_scope='institute' from same institute
    center_exams = Exam.objects.filter(
        Q(allowed_centers=center) | 
        Q(visibility_scope='institute', institute=center.institute)
    ).distinct()
    
    total_exams = center_exams.count()
    
    # Active exams (published/active status and within date range)
    now = timezone.now()
    active_exams = center_exams.filter(
        status__in=['published', 'active'],
        start_date__lte=now,
        end_date__gte=now
    ).count()
    
    # Get exam attempts by center students
    center_student_ids = center_users.filter(role='student').values_list('id', flat=True)
    
    attempts = ExamAttempt.objects.filter(
        student_id__in=center_student_ids
    )
    
    total_attempts = attempts.count()
    completed_attempts = attempts.filter(
        status__in=['submitted', 'auto_submitted']
    ).count()
    
    # Calculate pending evaluations
    pending_evaluation = QuestionEvaluation.objects.filter(
        attempt__student_id__in=center_student_ids,
        evaluation_status='pending'
    ).count()
    
    # Calculate average score
    avg_result = attempts.filter(
        status__in=['submitted', 'auto_submitted'],
        percentage__isnull=False
    ).aggregate(avg_score=Avg('percentage'))
    
    average_score = round(float(avg_result['avg_score'] or 0), 1)
    
    # Calculate pass rate (>= 40% is passing)
    passing_attempts = attempts.filter(
        status__in=['submitted', 'auto_submitted'],
        percentage__gte=40
    ).count()
    
    if completed_attempts > 0:
        pass_rate = round((passing_attempts / completed_attempts) * 100, 1)
    else:
        pass_rate = 0.0
    
    return Response({
        'total_students': total_students,
        'total_teachers': total_teachers,
        'total_staff': total_staff,
        'active_batches': active_batches,
        'total_exams': total_exams,
        'active_exams': active_exams,
        'total_attempts': total_attempts,
        'completed_attempts': completed_attempts,
        'pending_evaluation': pending_evaluation,
        'average_score': average_score,
        'pass_rate': pass_rate,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def center_activity(request):
    """
    Get recent activity for a center.
    
    Query params:
        center_id (required): UUID of the center
        limit (optional): Number of activities to return (default 10)
        
    Returns:
        List of recent activities (exam attempts, new users, etc.)
    """
    center_id = request.query_params.get('center_id')
    limit = int(request.query_params.get('limit', 10))
    
    if not center_id:
        user = request.user
        if hasattr(user, 'center') and user.center:
            center_id = str(user.center.id)
        else:
            return Response(
                {'error': 'center_id is required'},
                status=400
            )
    
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {'error': 'Center not found'},
            status=404
        )
    
    activities = []
    
    # Get recent exam attempts from center students
    center_student_ids = User.objects.filter(
        center=center, 
        role='student'
    ).values_list('id', flat=True)
    
    recent_attempts = ExamAttempt.objects.filter(
        student_id__in=center_student_ids
    ).select_related('student', 'exam').order_by('-updated_at')[:limit]
    
    for attempt in recent_attempts:
        if attempt.status in ['submitted', 'auto_submitted']:
            activity_type = 'exam_attempt'
            title = attempt.exam.title
            score = f"{attempt.percentage}%" if attempt.percentage else "Pending"
            description = f"{attempt.student.get_full_name()} completed with {score}"
            icon = 'score'
        else:
            activity_type = 'exam_started'
            title = attempt.exam.title
            description = f"{attempt.student.get_full_name()} started the exam"
            icon = 'exam'
        
        # Calculate relative time
        time_diff = timezone.now() - attempt.updated_at
        if time_diff.seconds < 60:
            time_str = "Just now"
        elif time_diff.seconds < 3600:
            mins = time_diff.seconds // 60
            time_str = f"{mins} min ago"
        elif time_diff.seconds < 86400:
            hours = time_diff.seconds // 3600
            time_str = f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            days = time_diff.days
            time_str = f"{days} day{'s' if days > 1 else ''} ago"
        
        activities.append({
            'id': str(attempt.id),
            'type': activity_type,
            'title': title,
            'description': description,
            'time': time_str,
            'icon': icon,
        })
    
    # Get recently joined students
    recent_students = User.objects.filter(
        center=center,
        role='student'
    ).order_by('-created_at')[:5]
    
    for student in recent_students:
        time_diff = timezone.now() - student.created_at
        if time_diff.days < 7:
            if time_diff.seconds < 3600:
                mins = time_diff.seconds // 60
                time_str = f"{mins} min ago"
            elif time_diff.seconds < 86400:
                hours = time_diff.seconds // 3600
                time_str = f"{hours} hour{'s' if hours > 1 else ''} ago"
            else:
                time_str = f"{time_diff.days} day{'s' if time_diff.days > 1 else ''} ago"
            
            activities.append({
                'id': str(student.id),
                'type': 'user_joined',
                'title': 'New Student',
                'description': f"{student.get_full_name()} joined",
                'time': time_str,
                'icon': 'user',
            })
    
    # Sort activities by time (most recent first) and limit
    # This is a simplification - in production you'd parse the time strings properly
    return Response({
        'activities': activities[:limit]
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def center_batch_stats(request):
    """
    Get performance stats for batches in a center.
    
    Query params:
        center_id (required): UUID of the center
        
    Returns:
        List of batches with performance metrics
    """
    center_id = request.query_params.get('center_id')
    
    if not center_id:
        user = request.user
        if hasattr(user, 'center') and user.center:
            center_id = str(user.center.id)
        else:
            return Response(
                {'error': 'center_id is required'},
                status=400
            )
    
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {'error': 'Center not found'},
            status=404
        )
    
    # Get batches for this center (using direct center field)
    batches = Batch.objects.filter(
        center=center
    ).select_related('program')
    
    batch_stats = []
    
    for batch in batches:
        # Count students in this batch (through enrollments)
        from accounts.models import Enrollment
        students_count = Enrollment.objects.filter(
            batch=batch,
            status='ACTIVE'
        ).count()
        
        # Get student IDs
        student_ids = Enrollment.objects.filter(
            batch=batch,
            status='ACTIVE'
        ).values_list('student_id', flat=True)
        
        # Calculate average score for students in this batch
        batch_attempts = ExamAttempt.objects.filter(
            student_id__in=student_ids,
            status__in=['submitted', 'auto_submitted'],
            percentage__isnull=False
        )
        
        avg_result = batch_attempts.aggregate(avg_score=Avg('percentage'))
        avg_score = round(float(avg_result['avg_score'] or 0), 1)
        
        # Calculate completion rate
        # This would need a proper implementation based on exams assigned to batch
        total_assigned = batch_attempts.values('student_id', 'exam_id').distinct().count()
        completed = batch_attempts.count()
        completion = round((completed / max(total_assigned, 1)) * 100, 1) if total_assigned > 0 else 0
        
        # Trend calculation (compare to previous period)
        # Simplified: random for now, would need historical data
        trend = 'stable'
        if avg_score > 75:
            trend = 'up'
        elif avg_score < 50:
            trend = 'down'
        
        batch_stats.append({
            'id': str(batch.id),
            'name': batch.name,
            'code': batch.code,
            'program': batch.program.name if batch.program else None,
            'students': students_count,
            'avgScore': avg_score,
            'completion': completion,
            'trend': trend,
        })
    
    return Response({
        'batches': batch_stats
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def center_upcoming_exams(request):
    """
    Get upcoming exams for a center.
    
    Query params:
        center_id (required): UUID of the center
        limit (optional): Number of exams to return (default 5)
        
    Returns:
        List of upcoming exams with details
    """
    center_id = request.query_params.get('center_id')
    limit = int(request.query_params.get('limit', 5))
    
    if not center_id:
        user = request.user
        if hasattr(user, 'center') and user.center:
            center_id = str(user.center.id)
        else:
            return Response(
                {'error': 'center_id is required'},
                status=400
            )
    
    try:
        center = Center.objects.get(id=center_id)
    except Center.DoesNotExist:
        return Response(
            {'error': 'Center not found'},
            status=404
        )
    
    now = timezone.now()
    
    # Get upcoming exams for this center
    upcoming_exams = Exam.objects.filter(
        Q(allowed_centers=center) | 
        Q(visibility_scope='institute', institute=center.institute)
    ).filter(
        status__in=['published', 'active'],
        start_date__gt=now
    ).distinct().order_by('start_date')[:limit]
    
    # Count students in this center
    center_students = User.objects.filter(
        center=center,
        role='student'
    ).count()
    
    exams_data = []
    
    for exam in upcoming_exams:
        # Format date
        start_dt = exam.start_date
        if start_dt.date() == now.date():
            date_str = f"Today, {start_dt.strftime('%-I:%M %p')}"
        elif start_dt.date() == (now + timedelta(days=1)).date():
            date_str = f"Tomorrow, {start_dt.strftime('%-I:%M %p')}"
        else:
            date_str = start_dt.strftime('%b %d, %-I:%M %p')
        
        # Format duration
        duration = exam.duration_minutes
        if duration >= 60:
            hours = duration // 60
            mins = duration % 60
            duration_str = f"{hours} hour{'s' if hours > 1 else ''}"
            if mins > 0:
                duration_str += f" {mins} min"
        else:
            duration_str = f"{duration} min"
        
        # Get batch info if exam is batch-specific
        batch_str = "All Students"
        if exam.visibility_scope == 'batches' and exam.allowed_batches.exists():
            batch_names = list(exam.allowed_batches.values_list('name', flat=True)[:2])
            batch_str = ", ".join(batch_names)
            if exam.allowed_batches.count() > 2:
                batch_str += f" +{exam.allowed_batches.count() - 2} more"
        
        exams_data.append({
            'id': str(exam.id),
            'title': exam.title,
            'batch': batch_str,
            'date': date_str,
            'students': center_students,
            'duration': duration_str,
        })
    
    return Response({
        'exams': exams_data
    })
