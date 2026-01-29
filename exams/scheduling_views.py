from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from .models import Exam, ExamReschedule
from .serializers import (
    ExamRescheduleSerializer, ExamRescheduleRequestSerializer, 
    ExamRescheduleReviewSerializer, TimezoneListSerializer
)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_timezones(request):
    """Get list of available timezones"""
    import pytz
    from datetime import datetime
    
    timezones = []
    for tz_name in pytz.all_timezones:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        utc_offset = now.strftime('%z')
        offset_hours = int(utc_offset[:3])
        offset_minutes = int(utc_offset[3:])
        offset_str = f"{offset_hours:+03d}:{offset_minutes:02d}"
        
        # Create a more readable label
        label_parts = tz_name.split('/')
        if len(label_parts) > 1:
            label = f"{label_parts[-1].replace('_', ' ')} ({label_parts[0]})"
        else:
            label = tz_name.replace('_', ' ')
        
        timezones.append({
            'value': tz_name,
            'label': label,
            'offset': offset_str,
            'utc_offset': utc_offset
        })
    
    # Sort by UTC offset
    timezones.sort(key=lambda x: x['utc_offset'])
    
    return Response(timezones)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_exam_schedule_info(request, exam_id):
    """Get detailed scheduling information for an exam"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT'] and not exam.is_public and user not in exam.allowed_users.all():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get timezone-aware information
        timezone_info = exam.get_timezone_aware_dates()
        remaining_time = exam.get_remaining_time()
        
        # Get reschedule information if applicable
        reschedule_info = None
        if exam.reschedule_allowed and user.role in ['student', 'STUDENT']:
            # Check if student has any pending reschedule requests
            pending_request = ExamReschedule.objects.filter(
                exam=exam, student=user, status='pending'
            ).first()
            
            if pending_request:
                reschedule_info = {
                    'has_pending_request': True,
                    'request_id': pending_request.id,
                    'requested_dates': {
                        'start': pending_request.new_start_date,
                        'end': pending_request.new_end_date
                    },
                    'reason': pending_request.reason
                }
            else:
                reschedule_info = {
                    'has_pending_request': False,
                    'can_request': exam.is_available_for_reschedule,
                    'max_reschedules': exam.max_reschedules,
                    'reschedule_deadline': exam.reschedule_deadline
                }
        
        return Response({
            'exam_id': exam.id,
            'title': exam.title,
            'timezone_info': timezone_info,
            'remaining_time': remaining_time,
            'is_accessible': exam.is_accessible,
            'is_active': exam.is_active,
            'reschedule_info': reschedule_info,
            'scheduling_settings': {
                'grace_period_minutes': exam.grace_period_minutes,
                'buffer_time_minutes': exam.buffer_time_minutes,
                'auto_start': exam.auto_start,
                'auto_end': exam.auto_end,
                'reschedule_allowed': exam.reschedule_allowed
            }
        })
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get schedule info: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def request_exam_reschedule(request, exam_id):
    """Request to reschedule an exam"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check if user is a student
        if user.role not in ['student', 'STUDENT']:
            return Response({'error': 'Only students can request reschedules'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if rescheduling is allowed
        if not exam.reschedule_allowed:
            return Response({'error': 'Rescheduling is not allowed for this exam'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not exam.is_available_for_reschedule:
            return Response({'error': 'Rescheduling deadline has passed'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if student has already reached max reschedules
        approved_reschedules = ExamReschedule.objects.filter(
            exam=exam, student=user, status='approved'
        ).count()
        
        if approved_reschedules >= exam.max_reschedules:
            return Response({'error': 'Maximum reschedule limit reached'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if there's already a pending request
        existing_request = ExamReschedule.objects.filter(
            exam=exam, student=user, status='pending'
        ).first()
        
        if existing_request:
            return Response({'error': 'You already have a pending reschedule request'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate request data
        serializer = ExamRescheduleRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create reschedule request
        reschedule = ExamReschedule.objects.create(
            exam=exam,
            student=user,
            original_start_date=exam.start_date,
            original_end_date=exam.end_date,
            new_start_date=serializer.validated_data['new_start_date'],
            new_end_date=serializer.validated_data['new_end_date'],
            reason=serializer.validated_data['reason']
        )
        
        return Response({
            'success': True,
            'message': 'Reschedule request submitted successfully',
            'reschedule': ExamRescheduleSerializer(reschedule).data
        })
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to submit reschedule request: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_reschedule_requests(request, exam_id):
    """Get reschedule requests for an exam (admin only)"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get reschedule requests
        requests = ExamReschedule.objects.filter(exam=exam).order_by('-created_at')
        
        return Response({
            'reschedule_requests': ExamRescheduleSerializer(requests, many=True).data
        })
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get reschedule requests: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def review_reschedule_request(request, reschedule_id):
    """Review a reschedule request (admin only)"""
    try:
        reschedule = ExamReschedule.objects.get(id=reschedule_id)
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Validate request data
        serializer = ExamRescheduleReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Update reschedule request
        reschedule.status = serializer.validated_data['status']
        reschedule.reviewed_by = user
        reschedule.review_notes = serializer.validated_data.get('review_notes', '')
        reschedule.reviewed_at = timezone.now()
        reschedule.save()
        
        # If approved, update exam dates
        if reschedule.status == 'approved':
            exam = reschedule.exam
            exam.start_date = reschedule.new_start_date
            exam.end_date = reschedule.new_end_date
            exam.save()
        
        return Response({
            'success': True,
            'message': f'Reschedule request {reschedule.status}',
            'reschedule': ExamRescheduleSerializer(reschedule).data
        })
        
    except ExamReschedule.DoesNotExist:
        return Response({'error': 'Reschedule request not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to review reschedule request: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_student_reschedule_requests(request):
    """Get reschedule requests for the current student"""
    user = request.user
    
    if user.role not in ['student', 'STUDENT']:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    requests = ExamReschedule.objects.filter(student=user).order_by('-created_at')
    
    return Response({
        'reschedule_requests': ExamRescheduleSerializer(requests, many=True).data
    })
