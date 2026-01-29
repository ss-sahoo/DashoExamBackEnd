from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.db.models import Q, Count, Avg, Sum, Value
from django.db.models.functions import Concat
from django.contrib.auth import get_user_model
from accounts.models import User as AccountsUser
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, JsonResponse
from decimal import Decimal
import json
import csv
import io
import uuid
import pandas as pd
from datetime import datetime, timedelta
import statistics
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import xlsxwriter
from .models import (
    Exam,
    ExamAttempt,
    ExamResult,
    ExamInvitation,
    ExamAnalytics,
    ExamViolation,
    ExamProctoring,
    QuestionAnalytics,
    QuestionEvaluation,
    PublicExamAccessLog,
)
from questions.models import Question
from .serializers import (
    ExamSerializer, ExamCreateSerializer, ExamAttemptSerializer, ExamResultSerializer,
    ExamInvitationSerializer, ExamAnalyticsSerializer, ExamStartSerializer, ExamSubmitSerializer,
    ExamViolationSerializer, ExamProctoringSerializer, ViolationLogSerializer, 
    ExamAccessSerializer, SnapshotUploadSerializer, ExamRescheduleSerializer,
    ExamRescheduleRequestSerializer, ExamRescheduleReviewSerializer, TimezoneListSerializer,
    ProctoringIncidentSerializer
)

# Import evaluation views
from .evaluation_views import (
    evaluate_exam_attempt, get_evaluation_progress, get_question_evaluations,
    manual_evaluate_question, ai_evaluate_question, get_evaluation_batches,
    update_evaluation_settings, get_pending_evaluations, batch_ai_evaluate
)
from .ai_proctoring import mediapipe_proctoring as proctoring_analyzer
from .pdf_utils import ensure_answer_sheet_pdf

# proctoring_analyzer is now the MediaPipe system
from accounts.jwt_utils import get_tokens_for_user

User = get_user_model()


class ExamListView(generics.ListCreateAPIView):
    """List and create exams"""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ExamCreateSerializer
        return ExamSerializer



    def filter_queryset(self, queryset):
        """
        Apply filters to the queryset based on query parameters
        """
        # Search filter
        search_query = self.request.query_params.get('search')
        if search_query:
            queryset = queryset.filter(
                Q(title__icontains=search_query) |
                Q(description__icontains=search_query)
            )
            
        # Status filter
        status_filter = self.request.query_params.get('status')
        if status_filter and status_filter != 'All Status':
            queryset = queryset.filter(status=status_filter)
            
        # Visibility scope filter
        visibility_scope = self.request.query_params.get('visibility_scope')
        if visibility_scope:
            queryset = queryset.filter(visibility_scope=visibility_scope)
            
        # Center filter
        center_id = self.request.query_params.get('center_id')
        if center_id:
            # Show exams that are either institute-wide OR assigned to this center
            queryset = queryset.filter(
                Q(visibility_scope='institute') |
                Q(allowed_centers__id=center_id)
            ).distinct()
            
        # Batch filter
        batch_id = self.request.query_params.get('batch_id')
        if batch_id:
            # Show exams that are either institute-wide OR assigned to this batch
            queryset = queryset.filter(
                Q(visibility_scope='institute') |
                Q(allowed_batches__id=batch_id)
            ).distinct()
            
        return queryset

    def get_queryset(self):
        user = self.request.user
        
        queryset = Exam.objects.filter(institute=user.institute)
        
        if user.role in ['student', 'STUDENT']:
            # Students can only see published/active exams based on visibility scope
            base_filter = Q(status__in=['published', 'active'])
            
            # Build visibility scope filter
            visibility_filter = Q()
            
            # Institute-wide exams are visible to all students in the institute
            visibility_filter |= Q(visibility_scope='institute')
            
            # Center-specific exams - visible if student's center is in allowed_centers
            student_center = getattr(user, 'center', None)
            if student_center:
                visibility_filter |= Q(visibility_scope='centers', allowed_centers=student_center)
            
            # Batch-specific exams - visible if student is in any of the allowed batches
            student_batches = user.batches.all() if hasattr(user, 'batches') else []
            has_batches = student_batches.exists() if hasattr(student_batches, 'exists') else len(student_batches) > 0
            
            if has_batches:
                visibility_filter |= Q(visibility_scope='batches', allowed_batches__in=student_batches)
            
            # Also allow explicitly allowed users
            visibility_filter |= Q(allowed_users=user)
            
            queryset = queryset.filter(base_filter & visibility_filter).distinct()
            
            # Apply common filters for students too (e.g. search)
            queryset = self.filter_queryset(queryset)
            
        elif user.can_manage_exams():
            # Admins can see all exams, apply filters
            queryset = self.filter_queryset(queryset)
        
        return queryset.order_by('-created_at')


    def perform_create(self, serializer):
        user = self.request.user
        if not user.can_create_exams():
            raise permissions.PermissionDenied("You don't have permission to create exams")
        
        exam = serializer.save(
            institute=user.institute,
            created_by=user
        )
        
        # Log activity
        from accounts.utils import log_activity
        log_activity(
            institute=user.institute,
            log_type='exam',
            title='New Exam Created',
            description=f'Exam "{exam.title}" was created by {user.get_full_name()}.',
            user=user,
            status='success',
            request=self.request
        )


class ExamDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, and delete exams"""
    serializer_class = ExamSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.can_manage_exams():
            return Exam.objects.filter(institute=user.institute)
        elif user.role in ['student', 'STUDENT']:
            # Students can only see published/active exams they're allowed to take
            return Exam.objects.filter(institute=user.institute).filter(
                Q(is_public=True) | Q(allowed_users=user)
            ).filter(status__in=['published', 'active'])
        else:
            # For other roles, apply basic filtering
            return Exam.objects.filter(institute=user.institute).filter(
                Q(is_public=True) | Q(allowed_users=user)
            )

    def get_object(self):
        """Override get_object to provide better error handling"""
        try:
            return super().get_object()
        except Exam.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Exam not found or you don't have permission to access it.")

    def perform_destroy(self, instance):
        """Override destroy to add permission check"""
        user = self.request.user
        if not user.can_manage_exams():
            raise permissions.PermissionDenied("You don't have permission to delete exams")
        
        # Additional check: only allow deletion of exams from the same institute
        if instance.institute != user.institute:
            raise permissions.PermissionDenied("You can only delete exams from your institute")
        
        # Check if exam has any attempts (optional business logic)
        if instance.attempts.exists():
            # You might want to prevent deletion of exams with attempts
            # For now, we'll allow it but you can uncomment the line below to prevent it
            # raise permissions.PermissionDenied("Cannot delete exam with existing attempts")
            pass
        
        try:
            # Use transaction to ensure atomicity
            with transaction.atomic():
                instance.delete()
        except Exception as e:
            # Log the error and provide a more user-friendly message
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error deleting exam {instance.id}: {str(e)}")
            from rest_framework.exceptions import APIException
            raise APIException("Failed to delete exam. Please try again or contact support.")


class ExamAttemptListView(generics.ListCreateAPIView):
    """List and create exam attempts"""
    serializer_class = ExamAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Disable pagination for this view

    def get_queryset(self):
        user = self.request.user
        exam_id = self.kwargs.get('exam_id')
        
        if user.role in ['student', 'STUDENT']:
            return ExamAttempt.objects.filter(exam_id=exam_id, student=user)
        else:
            return ExamAttempt.objects.filter(exam_id=exam_id)


def filter_all_exam_attempts(request):
    """Shared filtering logic for listing/exporting exam attempts across exams."""
    user = request.user

    # Students are not allowed to view/export all attempts
    if getattr(user, 'role', None) == 'student':
        return ExamAttempt.objects.none()

    queryset = ExamAttempt.objects.select_related('exam', 'student', 'result').filter(
        exam__institute=user.institute
    )

    exam_id = request.query_params.get('exam_id')
    if exam_id:
        try:
            queryset = queryset.filter(exam_id=int(exam_id))
        except (TypeError, ValueError):
            queryset = queryset.none()

    status = request.query_params.get('status')
    if status:
        queryset = queryset.filter(status=status)

    student_name = request.query_params.get('student_name')
    if student_name:
        student_name = student_name.strip()
        tokens = [token.strip() for token in student_name.split() if token.strip()]
        queryset = queryset.annotate(
            student_full_name=Concat('student__first_name', Value(' '), 'student__last_name')
        )

        if tokens:
            for token in tokens:
                queryset = queryset.filter(
                    Q(student__first_name__icontains=token) |
                    Q(student__last_name__icontains=token) |
                    Q(student__email__icontains=token) |
                    Q(student_full_name__icontains=token)
                )
        else:
            queryset = queryset.filter(
                Q(student__first_name__icontains=student_name) |
                Q(student__last_name__icontains=student_name) |
                Q(student__email__icontains=student_name) |
                Q(student_full_name__icontains=student_name)
            )

    start_date = request.query_params.get('start_date')
    if start_date:
        try:
            start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            queryset = queryset.filter(started_at__gte=start_datetime)
        except (ValueError, AttributeError):
            pass

    end_date = request.query_params.get('end_date')
    if end_date:
        try:
            end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            queryset = queryset.filter(started_at__lte=end_datetime)
        except (ValueError, AttributeError):
            pass

    return queryset.order_by('-created_at')


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def clean_ip_ranges(ip_entries):
    if not ip_entries:
        return []

    candidates = []
    if isinstance(ip_entries, str):
        portions = ip_entries.replace(',', '\n').splitlines()
        candidates = [portion.strip() for portion in portions]
    else:
        for entry in ip_entries:
            if isinstance(entry, str):
                portions = entry.replace(',', '\n').splitlines()
                candidates.extend(part.strip() for part in portions)
            elif entry is not None:
                candidates.append(str(entry).strip())

    cleaned = []
    for candidate in candidates:
        if not candidate:
            continue
        try:
            if '/' in candidate:
                ipaddress.ip_network(candidate, strict=False)
            else:
                ipaddress.ip_address(candidate)
            cleaned.append(candidate)
        except ValueError:
            continue

    return cleaned


class AllExamAttemptsListView(generics.ListAPIView):
    """List all exam attempts across all exams (for admins) with filtering support"""
    serializer_class = ExamAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Disable pagination for this view

    def get_queryset(self):
        return filter_all_exam_attempts(self.request)


class ExamAttemptDetailView(generics.RetrieveUpdateAPIView):
    """Get and update exam attempts"""
    serializer_class = ExamAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['student', 'STUDENT']:
            return ExamAttempt.objects.filter(student=user)
        return ExamAttempt.objects.filter(exam__institute=user.institute)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def start_exam(request):
    """Start an exam attempt"""
    serializer = ExamStartSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    exam_id = serializer.validated_data['exam_id']
    user = request.user
    
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check visibility scope access
    if user.role in ['student', 'STUDENT']:
        if not exam.can_student_access(user) and user not in exam.allowed_users.all():
            return Response({'error': 'You are not authorized to take this exam'}, status=status.HTTP_403_FORBIDDEN)
    
    # Check if exam is active
    if not exam.is_active:
        return Response({'error': 'Exam is not currently active'}, status=status.HTTP_400_BAD_REQUEST)

    
    # Check existing attempts
    existing_attempts = ExamAttempt.objects.filter(exam=exam, student=user)
    if existing_attempts.count() >= exam.max_attempts:
        return Response({'error': 'Maximum attempts reached'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check for in-progress attempts
    in_progress = existing_attempts.filter(status='in_progress').first()
    if in_progress:
        return Response({
            'attempt': ExamAttemptSerializer(in_progress).data,
            'message': 'You have an ongoing attempt'
        })
    
    with transaction.atomic():
        attempt = ExamAttempt.objects.create(
            exam=exam,
            student=user,
            attempt_number=existing_attempts.count() + 1,
            status='in_progress',
            started_at=timezone.now(),
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
    
    return Response({
        'attempt': ExamAttemptSerializer(attempt).data,
        'message': 'Exam started successfully'
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def submit_exam(request):
    """Submit exam answers with comprehensive evaluation system"""
    serializer = ExamSubmitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    attempt_id = serializer.validated_data['attempt_id']
    answers = serializer.validated_data['answers']
    
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if attempt.status != 'in_progress':
        return Response({'error': 'Exam is not in progress'}, status=status.HTTP_400_BAD_REQUEST)
    
    with transaction.atomic():
        # Calculate time spent
        if attempt.started_at:
            time_spent = (timezone.now() - attempt.started_at).total_seconds()
            attempt.time_spent = int(time_spent)
        
        # Merge auto-saved answers with submitted answers
        # Priority: submission answers > auto-saved answers
        merged_answers = {}
        if hasattr(attempt, 'answers') and attempt.answers:
            # Start with auto-saved answers
            merged_answers = dict(attempt.answers)
        
        # Override with submitted answers
        if answers:
            merged_answers.update(answers)
        
        # Use merged answers for evaluation
        final_answers = merged_answers if merged_answers else answers
        
        # Update attempt status
        attempt.status = 'submitted'
        attempt.submitted_at = timezone.now()
        attempt.save()
        
        # Create result record
        result = ExamResult.objects.create(
            attempt=attempt,
            answers=final_answers,
            total_questions_attempted=len([a for a in final_answers.values() if a])
        )
        
        # Use the new evaluation system
        from .evaluation_service import EvaluationService
        evaluation_service = EvaluationService(attempt)
        
        # Pass the answers directly (evaluation service will handle format)
        evaluation_result = evaluation_service.evaluate_attempt(final_answers)
        
        # Update result with evaluation data
        result.total_correct_answers = evaluation_result['auto_evaluated']  # This will be updated as evaluations complete
        result.total_wrong_answers = result.total_questions_attempted - evaluation_result['auto_evaluated']
        result.total_unattempted = attempt.exam.total_questions - result.total_questions_attempted
        result.save()
        
        # Update attempt with initial score (auto-evaluated questions only)
        attempt.score = evaluation_result['final_score']
        attempt.percentage = (evaluation_result['final_score'] / attempt.exam.total_marks) * 100 if attempt.exam.total_marks > 0 else 0
        attempt.save()
    
    return Response({
        'attempt': ExamAttemptSerializer(attempt).data,
        'result': ExamResultSerializer(result).data,
        'evaluation_result': evaluation_result,
        'message': 'Exam submitted successfully. Evaluation in progress.'
    })


class ExamInvitationListView(generics.ListCreateAPIView):
    """List and create exam invitations"""
    serializer_class = ExamInvitationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        exam_id = self.kwargs.get('exam_id')
        
        if user.can_manage_exams():
            return ExamInvitation.objects.filter(exam_id=exam_id)
        return ExamInvitation.objects.filter(exam_id=exam_id, user=user)

    def perform_create(self, serializer):
        user = self.request.user
        if not user.can_manage_exams():
            raise permissions.PermissionDenied("You don't have permission to send invitations")
        
        serializer.save(invited_by=user)


class ExamAnalyticsView(generics.RetrieveAPIView):
    """Get exam analytics"""
    serializer_class = ExamAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.can_manage_exams():
            return ExamAnalytics.objects.filter(exam__institute=user.institute)
        return ExamAnalytics.objects.none()


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_dashboard(request, exam_id):
    """Get exam dashboard data"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get analytics
    analytics, created = ExamAnalytics.objects.get_or_create(exam=exam)
    
    # Get recent attempts
    recent_attempts = ExamAttempt.objects.filter(exam=exam).order_by('-created_at')[:10]
    
    # Get statistics
    stats = {
        'total_invited': ExamInvitation.objects.filter(exam=exam).count(),
        'total_started': ExamAttempt.objects.filter(exam=exam).count(),
        'total_completed': ExamAttempt.objects.filter(exam=exam, status__in=['submitted', 'auto_submitted']).count(),
        'average_score': ExamAttempt.objects.filter(exam=exam, score__isnull=False).aggregate(
            avg_score=Avg('score')
        )['avg_score'] or 0,
    }
    
    return Response({
        'exam': ExamSerializer(exam).data,
        'analytics': ExamAnalyticsSerializer(analytics).data,
        'recent_attempts': ExamAttemptSerializer(recent_attempts, many=True).data,
        'statistics': stats
    })


# Security and Proctoring APIs

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def log_violation(request, attempt_id):
    """Log a security violation during exam attempt"""
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if attempt.status != 'in_progress':
        return Response({'error': 'Exam is not in progress'}, status=status.HTTP_400_BAD_REQUEST)
    
    serializer = ViolationLogSerializer(data=request.data, context={'attempt': attempt})
    if serializer.is_valid():
        violation = serializer.save()
        
        # Update violation count
        attempt.violations_count += 1
        attempt.save()
        
        # Log activity
        from accounts.utils import log_activity
        log_activity(
            institute=attempt.exam.institute,
            log_type='violation',
            title='Security Violation',
            description=f'Student {attempt.student.get_full_name()} triggered a {violation.get_violation_type_display()} during "{attempt.exam.title}".',
            user=attempt.student,
            status='error',
            request=request,
            metadata={'violation_id': violation.id, 'attempt_id': attempt.id}
        )

        # Check if max violations exceeded
        if attempt.violations_count >= attempt.max_violations_allowed:
            attempt.status = 'disqualified'
            attempt.save()
            
            # Create proctoring record if it doesn't exist
            proctoring, created = ExamProctoring.objects.get_or_create(attempt=attempt)
            proctoring.auto_disqualified = True
            proctoring.save()
            
            return Response({
                'violation_logged': True,
                'violation_count': attempt.violations_count,
                'auto_disqualified': True,
                'message': 'Maximum violations exceeded. Exam disqualified.'
            }, status=status.HTTP_200_OK)
        
        return Response({
            'violation_logged': True,
            'violation_count': attempt.violations_count,
            'auto_disqualified': False
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def auto_save_answers(request, attempt_id):
    """Auto-save student answers during exam"""
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if attempt.status != 'in_progress':
        return Response({'error': 'Exam is not in progress'}, status=status.HTTP_400_BAD_REQUEST)
    
    answers_data = request.data.get('answers', {})
    
    # Update the attempt with new answers
    if not hasattr(attempt, 'answers') or attempt.answers is None:
        attempt.answers = {}
    
    attempt.answers.update(answers_data)
    attempt.save()
    
    return Response({
        'success': True,
        'message': 'Answers saved successfully',
        'saved_at': attempt.updated_at.isoformat()
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_violations(request, attempt_id):
    """Get violation history for an exam attempt"""
    try:
        # Allow students to view their own violations, admins to view any violations
        if request.user.role in ['student', 'STUDENT']:
            attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
        else:
            attempt = ExamAttempt.objects.get(id=attempt_id)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    violations = ExamViolation.objects.filter(attempt=attempt)
    serializer = ExamViolationSerializer(violations, many=True)
    
    return Response({
        'violations': serializer.data,
        'total_count': violations.count(),
        'attempt_status': attempt.status
    })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def upload_snapshot(request, attempt_id):
    """
    Upload webcam snapshot for proctoring analysis.
    
    Storage Optimization (Selective Storage):
    - If violations detected: Store full snapshot (timestamp, metadata, full analysis)
    - If no violations: Store minimal metadata only (timestamp, face count, success flag)
    This reduces storage by ~90% since most snapshots have no violations.
    """
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Allow photo upload for identity verification even before exam starts
    # Only restrict after exam is completed or submitted
    if attempt.status in ['completed', 'submitted']:
        return Response({'error': 'Exam is already completed'}, status=status.HTTP_400_BAD_REQUEST)
    
    serializer = SnapshotUploadSerializer(data=request.data)
    if serializer.is_valid():
        # Get or create proctoring record
        proctoring, created = ExamProctoring.objects.get_or_create(attempt=attempt)
        
        # Check if this is pre-exam identity verification (skip AI analysis)
        metadata = serializer.validated_data.get('metadata', {})
        is_identity_verification = metadata.get('type') == 'identity_verification'
        
        if is_identity_verification:
            # For identity verification, just store the photo without AI analysis
            analysis = {
                'success': True,
                'type': 'identity_verification',
                'message': 'Identity photo captured successfully'
            }
        else:
            # Analyze the snapshot using AI for proctoring
            try:
                analysis = proctoring_analyzer.analyze_snapshot(serializer.validated_data['image_data'])
            except Exception as e:
                # If AI analysis fails, still store the snapshot
                analysis = {
                    'success': False,
                    'error': str(e),
                    'message': 'AI analysis failed but snapshot stored'
                }
        
        # Check if violations were detected
        has_violations = (
            not is_identity_verification and 
            analysis.get('success', False) and 
            len(analysis.get('violations', [])) > 0
        )
        
        # ALWAYS store full snapshot with image for review purposes
        # Store full snapshot info with image data
        snapshot_info = {
            'timestamp': serializer.validated_data['timestamp'].isoformat(),
            'metadata': serializer.validated_data['metadata'],
            'analysis': analysis,
            'image_data': serializer.validated_data['image_data'],  # Always store image
            'stored_reason': 'violation_detected' if has_violations else 'monitoring',
            'has_violations': has_violations
        }
        proctoring.snapshots.append(snapshot_info)
        
        proctoring.save()
        
        # Log any violations found (only for proctoring snapshots, not identity verification)
        if has_violations:
            for violation_data in analysis['violations']:
                ExamViolation.objects.create(
                    attempt=attempt,
                    violation_type=violation_data['type'],
                    metadata={
                        'confidence': violation_data.get('confidence', 0),
                        'message': violation_data.get('message', ''),
                        'analysis_data': analysis
                    }
                )
                
                # Update violation count
                attempt.violations_count += 1
                attempt.save()
                
                # Check for auto-disqualification
                if attempt.violations_count >= attempt.max_violations_allowed:
                    attempt.status = 'disqualified'
                    attempt.save()
                    proctoring.auto_disqualified = True
                    proctoring.save()
                    break
        
        return Response({
            'snapshot_uploaded': True,
            'analysis': analysis,
            'violation_count': attempt.violations_count,
            'auto_disqualified': attempt.status == 'disqualified',
            'storage_type': 'full' if has_violations else 'metadata_only'  # Indicates what was stored
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def log_proctoring_incident(request, attempt_id):
    """Persist client-side proctoring incidents (tab switch, camera errors, etc.)."""
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)

    if attempt.status in ['submitted', 'completed', 'disqualified']:
        return Response({'error': 'Exam attempt already finished'}, status=status.HTTP_400_BAD_REQUEST)

    serializer = ProctoringIncidentSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    incident = serializer.validated_data
    timestamp = incident.get('timestamp') or timezone.now()

    proctoring, _ = ExamProctoring.objects.get_or_create(attempt=attempt)
    entry = {
        'event_type': incident['event_type'],
        'severity': incident.get('severity', 'info'),
        'timestamp': timestamp.isoformat(),
        'details': incident.get('details', {})
    }

    incidents = list(proctoring.incidents or [])
    incidents.append(entry)
    proctoring.incidents = incidents[-200:]  # keep recent incidents
    proctoring.save(update_fields=['incidents'])

    violation_map = {
        'tab_hidden': 'tab_switch',
        'window_blur': 'window_blur',
        'camera_error': 'no_face',
        'camera_denied': 'no_face',
        'snapshot_failed': 'no_face'
    }

    violation_created = False
    mapped_violation = violation_map.get(incident['event_type'])

    if mapped_violation and incident.get('severity') in ['medium', 'high']:
        ExamViolation.objects.create(
            attempt=attempt,
            violation_type=mapped_violation,
            metadata={
                'source': 'client_incident',
                'incident': entry
            }
        )
        attempt.violations_count += 1
        attempt.save(update_fields=['violations_count'])
        proctoring.total_violations = attempt.violations_count
        proctoring.save(update_fields=['total_violations'])
        violation_created = True

        if attempt.violations_count >= attempt.max_violations_allowed:
            attempt.status = 'disqualified'
            attempt.save(update_fields=['status'])
            proctoring.auto_disqualified = True
            proctoring.save(update_fields=['auto_disqualified'])

    return Response({
        'incident_logged': True,
        'violation_created': violation_created,
        'violation_count': attempt.violations_count,
        'auto_disqualified': attempt.status == 'disqualified'
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_proctoring_snapshots(request, attempt_id):
    """
    Get all proctoring snapshots for an attempt (admin view).
    Returns snapshots with images (base64) for violation review.
    """
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check permissions: student can see their own, admins can see any
    user = request.user
    if user.role in ['student', 'STUDENT'] and attempt.student != user:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Check if user has admin access to this exam
    if user.role not in ['student', 'STUDENT'] and attempt.exam.institute != user.institute:
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        proctoring = ExamProctoring.objects.get(attempt=attempt)
    except ExamProctoring.DoesNotExist:
        return Response({
            'snapshots': [],
            'total_count': 0,
            'violation_snapshots': 0,
            'metadata_only_snapshots': 0
        }, status=status.HTTP_200_OK)
    
    snapshots = proctoring.snapshots or []
    
    # Filter to show only violation snapshots (with images) for admins
    # Students see all their snapshots
    filter_violations_only = request.query_params.get('violations_only', 'false').lower() == 'true'
    
    if filter_violations_only and user.role not in ['student', 'STUDENT']:
        violation_snapshots = [
            s for s in snapshots 
            if s.get('stored_reason') == 'violation_detected' and s.get('image_data')
        ]
        snapshots = violation_snapshots
    
    # Format response with image data
    formatted_snapshots = []
    for snapshot in snapshots:
        formatted = {
            'timestamp': snapshot.get('timestamp'),
            'stored_reason': snapshot.get('stored_reason', 'unknown'),
            'has_image': bool(snapshot.get('image_data')),
            'image_data': snapshot.get('image_data'),  # Base64 image (only for violations)
            'metadata': snapshot.get('metadata', {}),
            'analysis': snapshot.get('analysis', {}),
            'violations': snapshot.get('analysis', {}).get('violations', []),
            'faces_detected': snapshot.get('analysis', {}).get('faces_detected', snapshot.get('faces_detected', 0))
        }
        formatted_snapshots.append(formatted)
    
    # Count statistics
    violation_count = len([s for s in snapshots if s.get('stored_reason') == 'violation_detected'])
    metadata_count = len([s for s in snapshots if s.get('stored_reason') == 'metadata_only'])
    
    return Response({
        'snapshots': formatted_snapshots,
        'total_count': len(snapshots),
        'violation_snapshots': violation_count,
        'metadata_only_snapshots': metadata_count,
        'attempt_id': attempt_id,
        'student_name': attempt.student.get_full_name() or attempt.student.email,
        'exam_title': attempt.exam.title
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
def validate_exam_access(request):
    """Validate exam access via invitation code or scheduled access"""
    serializer = ExamAccessSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    access_code = serializer.validated_data.get('access_code')
    exam_id = serializer.validated_data.get('exam_id')
    
    if access_code:
        # Check invitation code
        try:
            invitation = ExamInvitation.objects.get(access_code=access_code)
            if not invitation.is_valid_now():
                return Response({'error': 'Access code is not valid at this time'}, status=status.HTTP_400_BAD_REQUEST)
            
            if not invitation.can_attempt():
                return Response({'error': 'Maximum attempts exceeded'}, status=status.HTTP_400_BAD_REQUEST)
            
            exam = invitation.exam
            user = invitation.user
            
        except ExamInvitation.DoesNotExist:
            return Response({'error': 'Invalid access code'}, status=status.HTTP_400_BAD_REQUEST)
    
    elif exam_id:
        # Check scheduled access
        try:
            exam = Exam.objects.get(id=exam_id)
            user = request.user if request.user.is_authenticated else None
            
            if not user:
                return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
            
            # Check if user is allowed to take this exam
            if not (exam.is_public or user in exam.allowed_users.all()):
                return Response({'error': 'You are not authorized to take this exam'}, status=status.HTTP_403_FORBIDDEN)
            
        except Exam.DoesNotExist:
            return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Check exam status and timing
    now = timezone.now()
    if exam.status != 'active':
        return Response({'error': 'Exam is not currently active'}, status=status.HTTP_400_BAD_REQUEST)
    
    if now < exam.start_date:
        return Response({
            'error': 'Exam has not started yet',
            'starts_at': exam.start_date,
            'time_remaining': (exam.start_date - now).total_seconds()
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if now > exam.end_date:
        return Response({'error': 'Exam has ended'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check existing attempts
    existing_attempts = ExamAttempt.objects.filter(exam=exam, student=user)
    if existing_attempts.exists() and exam.max_attempts > 0:
        completed_attempts = existing_attempts.filter(status__in=['submitted', 'auto_submitted'])
        if completed_attempts.count() >= exam.max_attempts:
            return Response({'error': 'Maximum attempts exceeded'}, status=status.HTTP_400_BAD_REQUEST)
    
    return Response({
        'access_granted': True,
        'exam': ExamSerializer(exam).data,
        'user': user.get_full_name() if user else None,
        'time_remaining': (exam.end_date - now).total_seconds()
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_exam_result(request, attempt_id):
    """Get exam results with progressive display"""
    try:
        # Allow students to view their own results, admins to view any results
        if request.user.role in ['student', 'STUDENT']:
            attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
        else:
            attempt = ExamAttempt.objects.get(id=attempt_id)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if attempt.status not in ['submitted', 'auto_submitted', 'disqualified']:
        return Response({'error': 'Exam not completed yet'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Determine what results to show based on question types
    exam = attempt.exam
    pattern = exam.pattern
    
    # Try to get result data, but don't fail if it doesn't exist
    result = None
    try:
        result = attempt.result
    except ExamResult.DoesNotExist:
        # For disqualified exams or exams without ExamResult, we'll build from evaluations
        pass
    
    # Get section-wise results
    section_results = {}
    if pattern:
        for section in pattern.sections.all():
            section_evaluations = QuestionEvaluation.objects.filter(
                attempt=attempt,
                question_number__gte=section.start_question,
                question_number__lte=section.end_question
            )
            
            section_score = sum(eval.marks_obtained for eval in section_evaluations)
            max_marks = section.marks_per_question * (section.end_question - section.start_question + 1)
            
            if section.question_type in ['mcq', 'single_mcq', 'multiple_mcq', 'numerical', 'true_false', 'fill_blank']:
                section_results[str(section.id)] = {
                    'section_name': section.name,
                    'question_type': section.question_type,
                    'score': section_score,
                    'max_marks': max_marks,
                    'status': 'available',
                    'feedback': 'Immediate feedback available'
                }
            else:
                section_results[str(section.id)] = {
                    'section_name': section.name,
                    'question_type': section.question_type,
                    'score': section_score if section_evaluations.exists() else None,
                    'max_marks': max_marks,
                    'status': 'available' if section_evaluations.exists() else 'pending_review',
                    'feedback': 'Graded' if section_evaluations.exists() else 'Under teacher review'
                }
    
    # Get detailed answers with evaluation data
    detailed_answers = {}
    evaluations = QuestionEvaluation.objects.filter(attempt=attempt).order_by('question_number')
    
    for evaluation in evaluations:
        question = evaluation.question
        detailed_answers[str(evaluation.question_number)] = {
            'question_text': question.question_text,
            'question_type': question.question_type,
            'user_answer': evaluation.student_answer,
            'correct_answer': question.correct_answer if hasattr(question, 'correct_answer') else 'N/A',
            'is_correct': evaluation.is_correct,
            'marks_obtained': evaluation.marks_obtained,
            'max_marks': evaluation.max_marks,
            'explanation': evaluation.evaluation_notes or 'No explanation available'
        }
    
    # Calculate aggregates from evaluations
    evaluations_qs = QuestionEvaluation.objects.filter(attempt=attempt)
    correct_answers_count = evaluations_qs.filter(is_correct=True).count()
    attempted_questions = evaluations_qs.filter(is_answered=True).count()
    marks_obtained = sum(eval.marks_obtained for eval in evaluations_qs)
    total_marks_available = sum(eval.max_marks for eval in evaluations_qs) or exam.total_marks
    
    # Determine total questions from pattern/exam definition
    total_questions = exam.total_questions
    if not total_questions:
        total_questions = evaluations_qs.count() or Question.objects.filter(exam=exam).count() or (result.total_questions_attempted if result else 0)
    
    answer_sheet_payload = ensure_answer_sheet_pdf(attempt)
    answer_sheet_data = None
    if answer_sheet_payload and getattr(attempt, 'answer_sheet_pdf', None):
        pdf_url = attempt.answer_sheet_pdf.url if attempt.answer_sheet_pdf else None
        if pdf_url:
            pdf_url = request.build_absolute_uri(pdf_url)
        branding_info = answer_sheet_payload.get('branding', {})
        answer_sheet_data = {
            'url': pdf_url,
            'generated_at': attempt.answer_sheet_generated_at,
            'branding': {
                'logo_url': branding_info.get('institute_logo_url'),
                'primary_hex': branding_info.get('primary_hex'),
            },
            'grading': answer_sheet_payload.get('grading'),
            'invigilator_placeholders': answer_sheet_payload.get('invigilator_placeholders'),
            'question_breakdown': answer_sheet_payload.get('question_breakdown'),
        }
    
    return Response({
        'attempt': ExamAttemptSerializer(attempt).data,
        'overall_score': correct_answers_count,
        'total_questions': total_questions,
        'attempted_questions': attempted_questions,
        'total_marks': total_marks_available,
        'marks_obtained': marks_obtained,
        'percentage': attempt.percentage,
        'section_results': section_results,
        'detailed_answers': detailed_answers,
        'submitted_at': attempt.submitted_at,
        'time_spent': attempt.time_spent,
        'answer_sheet_pdf': answer_sheet_data
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_answer_sheet_pdf(request, attempt_id):
    """Return (and optionally regenerate) the answer sheet PDF link for an attempt."""
    try:
        if request.user.role in ['student', 'STUDENT']:
            attempt = ExamAttempt.objects.get(id=attempt_id, student=request.user)
        else:
            attempt = ExamAttempt.objects.get(id=attempt_id)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.role not in ['student', 'STUDENT'] and request.user.role not in ['super_admin', 'SUPER_ADMIN']:
            if attempt.exam.institute != request.user.institute:
                return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

    regenerate_flag = str(request.query_params.get('regenerate', '')).lower() in ['1', 'true', 'yes']
    context = ensure_answer_sheet_pdf(
        attempt,
        force_regenerate=regenerate_flag and request.user.role not in ['student', 'STUDENT']
    )
    if not context or not attempt.answer_sheet_pdf:
        return Response(
            {'error': 'No evaluated questions available to build the answer sheet.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    pdf_url = request.build_absolute_uri(attempt.answer_sheet_pdf.url)
    branding_info = context.get('branding', {})
    return Response({
        'pdf_url': pdf_url,
        'generated_at': attempt.answer_sheet_generated_at,
        'branding': {
            'logo_url': branding_info.get('institute_logo_url'),
            'primary_hex': branding_info.get('primary_hex'),
        },
        'grading': context.get('grading'),
        'invigilator_placeholders': context.get('invigilator_placeholders'),
        'question_breakdown': context.get('question_breakdown'),
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def violation_dashboard(request):
    """Get violation dashboard for teachers"""
    user = request.user
    if not user.can_manage_exams():
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get all attempts with violations from user's institute
    attempts_with_violations = ExamAttempt.objects.filter(
        exam__institute=user.institute,
        violations_count__gt=0
    ).select_related('exam', 'student').prefetch_related('violations')
    
    # Get violation summary
    violation_summary = {}
    for attempt in attempts_with_violations:
        for violation in attempt.violations.all():
            vtype = violation.violation_type
            if vtype not in violation_summary:
                violation_summary[vtype] = {
                    'count': 0,
                    'attempts': []
                }
            violation_summary[vtype]['count'] += 1
            if attempt.id not in violation_summary[vtype]['attempts']:
                violation_summary[vtype]['attempts'].append(attempt.id)
    
    # Get recent violations
    recent_violations = ExamViolation.objects.filter(
        attempt__exam__institute=user.institute
    ).select_related('attempt__exam', 'attempt__student').order_by('-timestamp')[:50]
    
    return Response({
        'violation_summary': violation_summary,
        'recent_violations': ExamViolationSerializer(recent_violations, many=True).data,
        'total_attempts_with_violations': attempts_with_violations.count(),
        'auto_disqualified_count': attempts_with_violations.filter(status='disqualified').count()
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def student_dashboard_data(request):
    """Get comprehensive dashboard data for students"""
    # Check if user is a student (case-insensitive)
    if request.user.role.lower() != 'student':
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    user = request.user
    now = timezone.now()
    
    # Check if user has institute
    if not user.institute:
        return Response({
            'error': 'No institute assigned',
            'stats': {
                'total_exams_attempted': 0,
                'average_score': 0,
                'total_violations': 0,
                'current_rank': 1
            },
            'student_info': {
                'name': user.get_full_name(),
                'email': user.email,
                'institute': None,
                'center': None,
                'center_location': None,
            },
            'available_exams': [],
            'scheduled_exams': [],
            'ongoing_exams': [],
            'completed_exams': [],
            'disqualified_exams': []
        })
    
    # Filter exams by student's institute only (simplified for now)
    # Get available exams (published/active, within time window, not exceeded attempts)
    available_exams = Exam.objects.filter(
        institute=user.institute,
        status__in=['published', 'active'],
        start_date__lte=now,
        end_date__gte=now
    ).filter(
        Q(is_public=True) | Q(allowed_users=user)
    ).exclude(
        attempts__student=user,
        attempts__status__in=['submitted', 'auto_submitted']
    ).distinct()
    
    # Get scheduled exams (future exams that students can see)
    scheduled_exams = Exam.objects.filter(
        institute=user.institute,
        status__in=['published', 'active'],
        start_date__gt=now,
        end_date__gte=now
    ).filter(
        Q(is_public=True) | Q(allowed_users=user)
    ).distinct()
    
    # Get ongoing exams (started but not submitted)
    ongoing_attempts = ExamAttempt.objects.filter(
        student=user,
        status='in_progress'
    ).select_related('exam')
    
    # Get completed exams with results
    completed_attempts = ExamAttempt.objects.filter(
        student=user,
        status__in=['submitted', 'auto_submitted']
    ).select_related('exam').order_by('-submitted_at')[:10]
    
    # Get disqualified exams
    disqualified_attempts = ExamAttempt.objects.filter(
        student=user,
        status='disqualified'
    ).select_related('exam').order_by('-submitted_at')[:10]
    
    # Calculate stats (exclude disqualified exams from average)
    total_attempts = ExamAttempt.objects.filter(student=user).count()
    completed_count = completed_attempts.count()
    average_score = 0
    if completed_count > 0:
        total_score = sum(attempt.percentage or 0 for attempt in completed_attempts)
        average_score = total_score / completed_count
    
    total_violations = ExamAttempt.objects.filter(student=user).aggregate(
        total=Sum('violations_count')
    )['total'] or 0
    
    # Format available exams
    available_exams_data = []
    for exam in available_exams:
        # Check if student has remaining attempts
        used_attempts = ExamAttempt.objects.filter(
            student=user, exam=exam
        ).count()
        
        if used_attempts < exam.max_attempts:
            available_exams_data.append({
                'id': exam.id,
                'title': exam.title,
                'description': exam.description,
                'start_date': exam.start_date,
                'end_date': exam.end_date,
                'duration_minutes': exam.duration_minutes,
                'total_marks': exam.total_marks,
                'total_questions': exam.total_questions,
                'max_attempts': exam.max_attempts,
                'used_attempts': used_attempts,
                'time_remaining': (exam.end_date - now).total_seconds(),
                'can_start': True,
                'status': 'available'
            })
    
    # Format ongoing exams
    ongoing_exams_data = []
    for attempt in ongoing_attempts:
        time_remaining = attempt.exam.duration_minutes * 60 - attempt.time_spent
        ongoing_exams_data.append({
            'id': attempt.id,
            'attempt_id': attempt.id,
            'exam_id': attempt.exam.id,
            'exam_title': attempt.exam.title,
            'title': attempt.exam.title,
            'started_at': attempt.started_at,
            'time_remaining': max(0, time_remaining),
            'total_marks': attempt.exam.total_marks,
            'total_questions': attempt.exam.total_questions,
            'violations_count': attempt.violations_count,
            'status': attempt.status,
            'can_resume': True
        })
    
    # Format completed exams
    completed_exams_data = []
    for attempt in completed_attempts:
        completed_exams_data.append({
            'id': attempt.exam.id,  # Use exam ID for frontend compatibility
            'attempt_id': attempt.id,
            'exam_id': attempt.exam.id,
            'exam_title': attempt.exam.title,
            'title': attempt.exam.title,
            'started_at': attempt.started_at,
            'submitted_at': attempt.submitted_at,
            'score': attempt.score,
            'percentage': attempt.percentage,
            'total_marks': attempt.exam.total_marks,
            'total_questions': attempt.exam.total_questions,
            'time_spent': attempt.time_spent,
            'violations_count': attempt.violations_count,
            'status': attempt.status
        })
    
    # Format scheduled exams
    scheduled_exams_data = []
    for exam in scheduled_exams:
        scheduled_exams_data.append({
            'id': exam.id,
            'title': exam.title,
            'description': exam.description,
            'start_date': exam.start_date,
            'end_date': exam.end_date,
            'duration_minutes': exam.duration_minutes,
            'total_marks': exam.total_marks,
            'total_questions': exam.total_questions,
            'max_attempts': exam.max_attempts,
            'time_remaining': (exam.start_date - now).total_seconds(),
            'can_start': False,
            'status': 'scheduled'
        })
    
    # Format disqualified exams
    disqualified_exams_data = []
    for attempt in disqualified_attempts:
        disqualified_exams_data.append({
            'id': attempt.exam.id,  # Use exam ID for frontend compatibility
            'attempt_id': attempt.id,
            'exam_id': attempt.exam.id,
            'exam_title': attempt.exam.title,
            'title': attempt.exam.title,
            'started_at': attempt.started_at,
            'submitted_at': attempt.submitted_at,
            'score': attempt.score,
            'percentage': attempt.percentage,
            'total_marks': attempt.exam.total_marks,
            'total_questions': attempt.exam.total_questions,
            'time_spent': attempt.time_spent,
            'violations_count': attempt.violations_count,
            'status': 'disqualified'
        })
    
    return Response({
        'stats': {
            'total_exams_attempted': total_attempts,
            'average_score': round(average_score, 2),
            'total_violations': total_violations,
            'current_rank': 1  # TODO: Implement ranking system
        },
        'student_info': {
            'name': user.get_full_name(),
            'email': user.email,
            'institute': user.institute.name if user.institute else None,
            'center': getattr(user.center, 'name', None) if hasattr(user, 'center') else None,
            'center_location': getattr(user.center, 'location', None) if hasattr(user, 'center') else None,
        },
        'available_exams': available_exams_data,
        'scheduled_exams': scheduled_exams_data,
        'ongoing_exams': ongoing_exams_data,
        'completed_exams': completed_exams_data,
        'disqualified_exams': disqualified_exams_data
    })


# Analytics Views

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_analytics_dashboard(request, exam_id):
    """Get comprehensive analytics dashboard for an exam with advanced filtering"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    score_min = request.GET.get('score_min')
    score_max = request.GET.get('score_max')
    status_filter = request.GET.get('status', 'all')
    section_id = request.GET.get('section_id')
    subject = request.GET.get('subject')
    violations_only = request.GET.get('violations_only', 'false').lower() == 'true'
    
    # Get or create analytics
    analytics, created = ExamAnalytics.objects.get_or_create(exam=exam)
    
    # Get all attempts for this exam with filters
    attempts = ExamAttempt.objects.filter(exam=exam)
    
    # Apply status filter
    if status_filter == 'all':
        attempts = attempts.filter(status__in=['submitted', 'auto_submitted'])
    else:
        attempts = attempts.filter(status=status_filter)
    
    # Apply date range filter
    if date_from:
        try:
            from datetime import datetime as dt
            date_from_obj = dt.fromisoformat(date_from.replace('Z', '+00:00'))
            if timezone.is_aware(date_from_obj):
                date_from_obj = timezone.make_naive(date_from_obj, timezone.utc)
            attempts = attempts.filter(submitted_at__gte=date_from_obj)
        except (ValueError, AttributeError, TypeError):
            pass
    
    if date_to:
        try:
            from datetime import datetime as dt
            date_to_obj = dt.fromisoformat(date_to.replace('Z', '+00:00'))
            if timezone.is_aware(date_to_obj):
                date_to_obj = timezone.make_naive(date_to_obj, timezone.utc)
            attempts = attempts.filter(submitted_at__lte=date_to_obj)
        except (ValueError, AttributeError, TypeError):
            pass
    
    # Apply violations filter
    if violations_only:
        attempts = attempts.filter(violations_count__gt=0)
    
    # Calculate statistics
    scores = [float(attempt.score) for attempt in attempts if attempt.score is not None]
    times = [attempt.time_spent for attempt in attempts if attempt.time_spent > 0]
    
    # Apply score range filter
    if score_min:
        try:
            score_min_float = float(score_min)
            scores = [s for s in scores if s >= score_min_float]
        except (ValueError, TypeError):
            pass
    
    if score_max:
        try:
            score_max_float = float(score_max)
            scores = [s for s in scores if s <= score_max_float]
        except (ValueError, TypeError):
            pass
    
    # Calculate percentiles
    def calculate_percentile(data, percentile):
        if not data:
            return 0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    # Basic statistics with percentiles
    stats = {
        'total_attempts': attempts.count(),
        'total_invited': ExamInvitation.objects.filter(exam=exam).count(),
        'completion_rate': (attempts.count() / max(1, ExamInvitation.objects.filter(exam=exam).count())) * 100,
        'average_score': sum(scores) / len(scores) if scores else 0,
        'highest_score': max(scores) if scores else 0,
        'lowest_score': min(scores) if scores else 0,
        'median_score': sorted(scores)[len(scores)//2] if scores else 0,
        'mode_score': max(set(scores), key=scores.count) if scores else 0,
        'range_score': max(scores) - min(scores) if scores else 0,
        'std_deviation': calculate_std_deviation(scores) if scores else 0,
        'variance': calculate_variance(scores) if scores else 0,
        'average_time_spent': sum(times) / len(times) if times else 0,
        'percentiles': {
            'p25': calculate_percentile(scores, 25),
            'p50': calculate_percentile(scores, 50),
            'p75': calculate_percentile(scores, 75),
            'p90': calculate_percentile(scores, 90),
            'p95': calculate_percentile(scores, 95),
        } if scores else {},
    }
    
    # Score distribution (histogram data)
    score_ranges = [(0, 10), (11, 20), (21, 30), (31, 40), (41, 50), 
                   (51, 60), (61, 70), (71, 80), (81, 90), (91, 100)]
    histogram_data = []
    for min_score, max_score in score_ranges:
        count = len([s for s in scores if min_score <= s <= max_score])
        histogram_data.append({
            'range': f"{min_score}-{max_score}",
            'count': count,
            'percentage': (count / len(scores) * 100) if scores else 0
        })
    
    # Question-wise analysis
    question_analytics = []
    for i in range(1, exam.total_questions + 1):
        qa, created = QuestionAnalytics.objects.get_or_create(
            exam=exam, 
            question_number=i,
            defaults={'question_text': f'Question {i}'}
        )
        
        # Calculate question statistics
        correct_count = 0
        wrong_count = 0
        unattempted_count = 0
        total_attempts = 0
        
        for attempt in attempts:
            if hasattr(attempt, 'result') and attempt.result:
                answers = attempt.result.answers
                if str(i) in answers:
                    total_attempts += 1
                    answer_data = answers[str(i)]
                    if answer_data.get('is_correct', False):
                        correct_count += 1
                    else:
                        wrong_count += 1
                else:
                    unattempted_count += 1
        
        # Update question analytics
        qa.total_attempts = total_attempts
        qa.correct_attempts = correct_count
        qa.wrong_attempts = wrong_count
        qa.unattempted = unattempted_count
        from decimal import Decimal
        qa.average_score = Decimal(str(correct_count / max(1, total_attempts))) * Decimal(str(qa.max_marks))
        qa.save()
        
        question_analytics.append({
            'question_number': i,
            'total_attempts': total_attempts,
            'correct_attempts': correct_count,
            'wrong_attempts': wrong_count,
            'unattempted': unattempted_count,
            'success_rate': (correct_count / max(1, total_attempts)) * 100,
            'average_score': qa.average_score,
            'max_marks': qa.max_marks
        })
    
    # Heat map data (subject-wise performance) with section/subject filtering
    heatmap_data = []
    if hasattr(exam, 'pattern') and exam.pattern:
        sections = exam.pattern.sections.all()
        
        # Apply section filter
        if section_id:
            try:
                sections = sections.filter(id=int(section_id))
            except (ValueError, TypeError):
                pass
        
        # Apply subject filter
        if subject:
            sections = sections.filter(subject__icontains=subject)
        
        for section in sections:
            section_scores = []
            for attempt in attempts:
                if hasattr(attempt, 'result') and attempt.result:
                    section_score = attempt.result.section_scores.get(str(section.id), 0)
                    section_scores.append(section_score)
            
            questions_count = section.end_question - section.start_question + 1
            total_marks = section.marks_per_question * questions_count
            heatmap_data.append({
                'section_id': section.id,
                'section_name': section.name,
                'subject': section.subject,
                'average_score': sum(section_scores) / len(section_scores) if section_scores else 0,
                'max_marks': total_marks,
                'total_questions': questions_count,
                'total_attempts': len(section_scores)
            })
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
            'total_questions': exam.total_questions,
            'total_marks': exam.total_marks
        },
        'statistics': stats,
        'histogram_data': histogram_data,
        'question_analytics': question_analytics,
        'heatmap_data': heatmap_data,
        'box_plot_data': {
            'scores': scores,
            'quartiles': calculate_quartiles(scores) if scores else {}
        }
    })


def get_filtered_attempts(exam, request):
    """Helper function to get filtered attempts based on query parameters"""
    attempts = ExamAttempt.objects.filter(exam=exam)
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    score_min = request.GET.get('score_min')
    score_max = request.GET.get('score_max')
    status_filter = request.GET.get('status', 'all')
    section_id = request.GET.get('section_id')
    subject = request.GET.get('subject')
    violations_only = request.GET.get('violations_only', 'false').lower() == 'true'
    
    # Apply status filter
    if status_filter == 'all':
        attempts = attempts.filter(status__in=['submitted', 'auto_submitted'])
    else:
        attempts = attempts.filter(status=status_filter)
    
    # Apply date range filter
    if date_from:
        try:
            from datetime import datetime as dt
            date_from_obj = dt.fromisoformat(date_from.replace('Z', '+00:00'))
            if timezone.is_aware(date_from_obj):
                date_from_obj = timezone.make_naive(date_from_obj, timezone.utc)
            attempts = attempts.filter(submitted_at__gte=date_from_obj)
        except (ValueError, AttributeError, TypeError):
            pass
    
    if date_to:
        try:
            from datetime import datetime as dt
            date_to_obj = dt.fromisoformat(date_to.replace('Z', '+00:00'))
            if timezone.is_aware(date_to_obj):
                date_to_obj = timezone.make_naive(date_to_obj, timezone.utc)
            attempts = attempts.filter(submitted_at__lte=date_to_obj)
        except (ValueError, AttributeError, TypeError):
            pass
    
    # Apply violations filter
    if violations_only:
        attempts = attempts.filter(violations_count__gt=0)
    
    return attempts, {
        'date_from': date_from,
        'date_to': date_to,
        'score_min': score_min,
        'score_max': score_max,
        'status': status_filter,
        'section_id': section_id,
        'subject': subject,
        'violations_only': violations_only
    }


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_statistics_detailed(request, exam_id):
    """Get detailed statistics for an exam with advanced filtering"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    attempts, filters = get_filtered_attempts(exam, request)
    
    # Calculate statistics
    scores = [float(attempt.score) for attempt in attempts if attempt.score is not None]
    times = [attempt.time_spent for attempt in attempts if attempt.time_spent > 0]
    percentages = [float(attempt.percentage) for attempt in attempts if attempt.percentage is not None]
    
    # Apply score range filter
    score_min = request.GET.get('score_min')
    score_max = request.GET.get('score_max')
    if score_min:
        try:
            score_min_float = float(score_min)
            scores = [s for s in scores if s >= score_min_float]
            percentages = [p for p in percentages if p >= (score_min_float / exam.total_marks * 100) if exam.total_marks > 0]
        except (ValueError, TypeError):
            pass
    
    if score_max:
        try:
            score_max_float = float(score_max)
            scores = [s for s in scores if s <= score_max_float]
            percentages = [p for p in percentages if p <= (score_max_float / exam.total_marks * 100) if exam.total_marks > 0]
        except (ValueError, TypeError):
            pass
    
    def calculate_percentile(data, percentile):
        if not data:
            return 0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    # Detailed statistics
    stats = {
        'total_attempts': attempts.count(),
        'total_invited': ExamInvitation.objects.filter(exam=exam).count(),
        'completion_rate': (attempts.count() / max(1, ExamInvitation.objects.filter(exam=exam).count())) * 100,
        'average_score': sum(scores) / len(scores) if scores else 0,
        'highest_score': max(scores) if scores else 0,
        'lowest_score': min(scores) if scores else 0,
        'median_score': calculate_percentile(scores, 50) if scores else 0,
        'mode_score': max(set(scores), key=scores.count) if scores else 0,
        'range_score': max(scores) - min(scores) if scores else 0,
        'std_deviation': calculate_std_deviation(scores) if scores else 0,
        'variance': calculate_variance(scores) if scores else 0,
        'average_time_spent': sum(times) / len(times) if times else 0,
        'min_time_spent': min(times) if times else 0,
        'max_time_spent': max(times) if times else 0,
        'average_percentage': sum(percentages) / len(percentages) if percentages else 0,
        'percentiles': {
            'p25': calculate_percentile(scores, 25),
            'p50': calculate_percentile(scores, 50),
            'p75': calculate_percentile(scores, 75),
            'p90': calculate_percentile(scores, 90),
            'p95': calculate_percentile(scores, 95),
        } if scores else {},
        'violation_stats': {
            'total_violations': sum(attempt.violations_count for attempt in attempts),
            'attempts_with_violations': attempts.filter(violations_count__gt=0).count(),
            'average_violations': sum(attempt.violations_count for attempt in attempts) / max(1, attempts.count()),
        },
        'time_distribution': {
            'submissions_by_hour': {},
        }
    }
    
    # Time-based analytics
    for attempt in attempts:
        if attempt.submitted_at:
            hour = attempt.submitted_at.hour
            stats['time_distribution']['submissions_by_hour'][hour] = stats['time_distribution']['submissions_by_hour'].get(hour, 0) + 1
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
            'total_questions': exam.total_questions,
            'total_marks': exam.total_marks
        },
        'statistics': stats,
        'filters_applied': filters
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_heatmap_data(request, exam_id):
    """Get enhanced heatmap data with section/subject breakdown"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    attempts, filters = get_filtered_attempts(exam, request)
    
    # Heat map data (subject-wise performance)
    heatmap_data = []
    if hasattr(exam, 'pattern') and exam.pattern:
        sections = exam.pattern.sections.all()
        
        # Apply section filter
        if filters['section_id']:
            try:
                sections = sections.filter(id=int(filters['section_id']))
            except (ValueError, TypeError):
                pass
        
        # Apply subject filter
        if filters['subject']:
            sections = sections.filter(subject__icontains=filters['subject'])
        
        for section in sections:
            section_scores = []
            section_percentages = []
            
            for attempt in attempts:
                if hasattr(attempt, 'result') and attempt.result:
                    section_score = attempt.result.section_scores.get(str(section.id), 0)
                    if section_score > 0:
                        section_scores.append(float(section_score))
                        questions_count = section.end_question - section.start_question + 1
                        total_marks = section.marks_per_question * questions_count
                        if total_marks > 0:
                            section_percentages.append((section_score / total_marks) * 100)
            
            questions_count = section.end_question - section.start_question + 1
            total_marks = section.marks_per_question * questions_count
            
            avg_score = sum(section_scores) / len(section_scores) if section_scores else 0
            avg_percentage = sum(section_percentages) / len(section_percentages) if section_percentages else 0
            
            heatmap_data.append({
                'section_id': section.id,
                'section_name': section.name,
                'subject': section.subject,
                'average_score': round(avg_score, 2),
                'average_percentage': round(avg_percentage, 2),
                'max_marks': total_marks,
                'total_questions': questions_count,
                'total_attempts': len(section_scores),
                'performance_level': 'excellent' if avg_percentage >= 80 else 'good' if avg_percentage >= 60 else 'average' if avg_percentage >= 40 else 'poor'
            })
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
        },
        'heatmap_data': heatmap_data,
        'filters_applied': filters
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_histogram_data(request, exam_id):
    """Get histogram data with customizable bins and filters"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    attempts, filters = get_filtered_attempts(exam, request)
    
    # Get bin size from query params (default: 10)
    bin_size = int(request.GET.get('bin_size', 10))
    use_percentage = request.GET.get('use_percentage', 'false').lower() == 'true'
    
    # Calculate scores
    if use_percentage:
        scores = [float(attempt.percentage) for attempt in attempts if attempt.percentage is not None]
        max_value = 100
    else:
        scores = [float(attempt.score) for attempt in attempts if attempt.score is not None]
        max_value = float(exam.total_marks) if exam.total_marks else 100
    
    # Apply score range filter
    score_min = request.GET.get('score_min')
    score_max = request.GET.get('score_max')
    if score_min:
        try:
            score_min_float = float(score_min)
            scores = [s for s in scores if s >= score_min_float]
        except (ValueError, TypeError):
            pass
    
    if score_max:
        try:
            score_max_float = float(score_max)
            scores = [s for s in scores if s <= score_max_float]
        except (ValueError, TypeError):
            pass
    
    # Create bins
    histogram_data = []
    num_bins = int(max_value / bin_size) + (1 if max_value % bin_size > 0 else 0)
    
    for i in range(num_bins):
        min_score = i * bin_size
        max_score = min((i + 1) * bin_size - 1, max_value)
        count = len([s for s in scores if min_score <= s <= max_score])
        percentage = (count / len(scores) * 100) if scores else 0
        
        histogram_data.append({
            'range': f"{min_score}-{max_score}",
            'min': min_score,
            'max': max_score,
            'count': count,
            'percentage': round(percentage, 2)
        })
    
    # Calculate statistics for overlay
    mean_score = sum(scores) / len(scores) if scores else 0
    median_score = sorted(scores)[len(scores)//2] if scores else 0
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
        },
        'histogram_data': histogram_data,
        'statistics': {
            'mean': round(mean_score, 2),
            'median': round(median_score, 2),
            'total_data_points': len(scores),
        },
        'filters_applied': filters,
        'bin_size': bin_size,
        'use_percentage': use_percentage
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_boxplot_data(request, exam_id):
    """Get enhanced box plot data with outliers"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        attempts, filters = get_filtered_attempts(exam, request)
        
        # Get section filter for comparison
        section_id = request.GET.get('section_id')
        compare_by_section = section_id is None and hasattr(exam, 'pattern') and exam.pattern
        
        scores = [float(attempt.score) for attempt in attempts if attempt.score is not None]
        
        # Apply score range filter
        score_min = request.GET.get('score_min')
        score_max = request.GET.get('score_max')
        if score_min:
            try:
                score_min_float = float(score_min)
                scores = [s for s in scores if s >= score_min_float]
            except (ValueError, TypeError):
                pass
        
        if score_max:
            try:
                score_max_float = float(score_max)
                scores = [s for s in scores if s <= score_max_float]
            except (ValueError, TypeError):
                pass
        
        if compare_by_section:
            # Return box plot data for each section
            boxplot_data = []
            for section in exam.pattern.sections.all():
                section_scores = []
                for attempt in attempts:
                    if hasattr(attempt, 'result') and attempt.result:
                        section_scores_data = attempt.result.section_scores or {}
                        section_score = section_scores_data.get(str(section.id), 0)
                        if section_score > 0:
                            section_scores.append(float(section_score))
                
                if section_scores:
                    quartiles = calculate_quartiles(section_scores)
                    iqr = quartiles.get('q3', 0) - quartiles.get('q1', 0)
                    lower_bound = quartiles.get('q1', 0) - 1.5 * iqr
                    upper_bound = quartiles.get('q3', 0) + 1.5 * iqr
                    outliers = [s for s in section_scores if s < lower_bound or s > upper_bound]
                    
                    boxplot_data.append({
                        'section_id': section.id,
                        'section_name': section.name,
                        'subject': section.subject,
                        'scores': section_scores,
                        'quartiles': quartiles,
                        'outliers': outliers,
                        'iqr': iqr,
                        'lower_bound': lower_bound,
                        'upper_bound': upper_bound
                    })
            
            return Response({
                'exam': {
                    'id': exam.id,
                    'title': exam.title,
                },
                'boxplot_data': boxplot_data,
                'filters_applied': filters
            })
        else:
            # Single box plot for all scores
            quartiles = calculate_quartiles(scores) if scores else {'min': 0, 'q1': 0, 'median': 0, 'q3': 0, 'max': 0}
            iqr = quartiles.get('q3', 0) - quartiles.get('q1', 0)
            lower_bound = quartiles.get('q1', 0) - 1.5 * iqr
            upper_bound = quartiles.get('q3', 0) + 1.5 * iqr
            outliers = [s for s in scores if s < lower_bound or s > upper_bound] if scores else []
            
            return Response({
                'exam': {
                    'id': exam.id,
                    'title': exam.title,
                },
                'boxplot_data': {
                    'scores': scores,
                    'quartiles': quartiles,
                    'outliers': outliers,
                    'iqr': iqr,
                    'lower_bound': lower_bound,
                    'upper_bound': upper_bound
                },
                'filters_applied': filters
            })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': f'Failed to load boxplot data: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_question_analytics(request, exam_id):
    """Get detailed question-wise analysis with filters"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        attempts, filters = get_filtered_attempts(exam, request)
        attempts_count = attempts.count()
        
        # Question-wise analysis
        question_analytics = []
        from .models import QuestionEvaluation
        
        # Handle case where exam has no questions
        total_questions = exam.total_questions or 0
        
        for i in range(1, total_questions + 1):
            qa, created = QuestionAnalytics.objects.get_or_create(
                exam=exam, 
                question_number=i,
                defaults={'question_text': f'Question {i}'}
            )
            
            # Get question evaluations for filtered attempts
            evaluations = QuestionEvaluation.objects.filter(
                attempt__in=attempts,
                question_number=i
            )
            
            correct_count = evaluations.filter(is_correct=True).count()
            wrong_count = evaluations.filter(is_correct=False, is_answered=True).count()
            answered_count = evaluations.filter(is_answered=True).count()
            unattempted_count = max(0, attempts_count - answered_count)
            total_attempts = evaluations.count()
            
            # Calculate average score
            avg_score = evaluations.aggregate(avg_score=Avg('marks_obtained'))['avg_score'] or 0
            
            success_rate = (correct_count / max(1, total_attempts)) * 100
            
            question_analytics.append({
                'question_number': i,
                'question_text': qa.question_text,
                'total_attempts': total_attempts,
                'correct_attempts': correct_count,
                'wrong_attempts': wrong_count,
                'unattempted': unattempted_count,
                'success_rate': success_rate,
                'average_score': float(avg_score) if avg_score else 0.0,
                'max_marks': float(qa.max_marks),
                'average_time_spent': 0.0,  # QuestionEvaluation doesn't track time per question
                'difficulty_level': 'easy' if success_rate >= 70 else 'medium' if success_rate >= 40 else 'hard'
            })
        
        return Response({
            'exam': {
                'id': exam.id,
                'title': exam.title,
                'total_questions': total_questions,
            },
            'question_analytics': question_analytics,
            'filters_applied': filters
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': f'Failed to load question analytics: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_evaluation_analytics(request, exam_id):
    """Get evaluation progress and grading analytics"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    attempts, filters = get_filtered_attempts(exam, request)
    
    from .models import QuestionEvaluation, EvaluationProgress, EvaluationBatch
    
    # Get evaluation progress
    progress, created = EvaluationProgress.objects.get_or_create(exam=exam)
    
    # Get all evaluations for filtered attempts
    evaluations = QuestionEvaluation.objects.filter(attempt__in=attempts)
    
    # Calculate evaluation statistics
    total_questions = exam.total_questions * attempts.count()
    evaluated_questions = evaluations.count()
    pending_questions = total_questions - evaluated_questions
    
    # Evaluation status breakdown
    auto_evaluated = evaluations.filter(evaluation_status='auto_evaluated').count()
    manually_evaluated = evaluations.filter(evaluation_status='manually_evaluated').count()
    pending_evaluation = evaluations.filter(evaluation_status='pending').count()
    
    # Question-wise evaluation status
    question_eval_status = []
    for i in range(1, exam.total_questions + 1):
        q_evaluations = evaluations.filter(question_number=i)
        q_total = attempts.count()
        q_evaluated = q_evaluations.count()
        q_pending = q_total - q_evaluated
        
        question_eval_status.append({
            'question_number': i,
            'total_attempts': q_total,
            'evaluated': q_evaluated,
            'pending': q_pending,
            'completion_rate': (q_evaluated / q_total * 100) if q_total > 0 else 0
        })
    
    # Batch evaluation progress
    batches = EvaluationBatch.objects.filter(exam=exam).order_by('-created_at')
    batch_progress = []
    for batch in batches[:10]:  # Last 10 batches
        batch_progress.append({
            'id': batch.id,
            'created_at': batch.created_at.isoformat(),
            'total_questions': batch.total_questions,
            'evaluated_questions': batch.evaluated_questions,
            'status': batch.status,
            'progress_percentage': (batch.evaluated_questions / batch.total_questions * 100) if batch.total_questions > 0 else 0
        })
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
            'total_questions': exam.total_questions,
        },
        'evaluation_statistics': {
            'total_questions': total_questions,
            'evaluated_questions': evaluated_questions,
            'pending_questions': pending_questions,
            'completion_rate': (evaluated_questions / total_questions * 100) if total_questions > 0 else 0,
            'auto_evaluated': auto_evaluated,
            'manually_evaluated': manually_evaluated,
            'pending_evaluation': pending_evaluation,
        },
        'question_evaluation_status': question_eval_status,
        'batch_progress': batch_progress,
        'filters_applied': filters
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_performance_graphs(request, exam_id):
    """Get time-series and trend graphs data"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    attempts, filters = get_filtered_attempts(exam, request)
    
    # Score trend over time
    score_trend = []
    for attempt in attempts.order_by('submitted_at'):
        if attempt.submitted_at and attempt.score is not None:
            score_trend.append({
                'date': attempt.submitted_at.isoformat(),
                'score': float(attempt.score),
                'percentage': float(attempt.percentage) if attempt.percentage else 0,
                'time_spent': attempt.time_spent
            })
    
    # Submission time distribution (by hour)
    submission_distribution = {}
    for attempt in attempts:
        if attempt.submitted_at:
            hour = attempt.submitted_at.hour
            submission_distribution[hour] = submission_distribution.get(hour, 0) + 1
    
    # Performance by section
    section_performance = []
    if hasattr(exam, 'pattern') and exam.pattern:
        for section in exam.pattern.sections.all():
            section_scores = []
            for attempt in attempts:
                if hasattr(attempt, 'result') and attempt.result:
                    section_score = attempt.result.section_scores.get(str(section.id), 0)
                    if section_score > 0:
                        section_scores.append(float(section_score))
            
            if section_scores:
                questions_count = section.end_question - section.start_question + 1
                total_marks = section.marks_per_question * questions_count
                avg_score = sum(section_scores) / len(section_scores)
                avg_percentage = (avg_score / total_marks * 100) if total_marks > 0 else 0
                
                section_performance.append({
                    'section_name': section.name,
                    'subject': section.subject,
                    'average_score': round(avg_score, 2),
                    'average_percentage': round(avg_percentage, 2),
                    'total_attempts': len(section_scores)
                })
    
    # Time vs Score scatter plot data
    time_score_data = []
    for attempt in attempts:
        if attempt.time_spent > 0 and attempt.score is not None:
            time_score_data.append({
                'time_spent': attempt.time_spent,
                'score': float(attempt.score),
                'percentage': float(attempt.percentage) if attempt.percentage else 0
            })
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
        },
        'score_trend': score_trend,
        'submission_distribution': submission_distribution,
        'section_performance': section_performance,
        'time_score_data': time_score_data,
        'filters_applied': filters
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_results_dashboard(request, exam_id):
    """Get results dashboard with search and sorting capabilities"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get query parameters
    search = request.GET.get('search', '')
    sort_by = request.GET.get('sort_by', 'submitted_at')
    sort_order = request.GET.get('sort_order', 'desc')
    status_filter = request.GET.get('status', 'all')
    
    # Get attempts
    attempts = ExamAttempt.objects.filter(exam=exam)
    
    # Apply status filter
    if status_filter != 'all':
        attempts = attempts.filter(status=status_filter)
    
    # Apply search
    if search:
        attempts = attempts.filter(
            Q(student__first_name__icontains=search) |
            Q(student__last_name__icontains=search) |
            Q(student__email__icontains=search)
        )
    
    # Apply sorting
    if sort_by == 'score':
        attempts = attempts.order_by(f'{"-" if sort_order == "desc" else ""}score')
    elif sort_by == 'percentage':
        attempts = attempts.order_by(f'{"-" if sort_order == "desc" else ""}percentage')
    elif sort_by == 'time_spent':
        attempts = attempts.order_by(f'{"-" if sort_order == "desc" else ""}time_spent')
    elif sort_by == 'submitted_at':
        attempts = attempts.order_by(f'{"-" if sort_order == "desc" else ""}submitted_at')
    else:
        attempts = attempts.order_by('-submitted_at')
    
    # Format results
    results = []
    for i, attempt in enumerate(attempts, 1):
        results.append({
            's_no': i,
            'task_no': attempt.attempt_number,
            'student_id': attempt.student.id,
            'student_name': attempt.student.get_full_name(),
            'student_email': attempt.student.email,
            'phone': attempt.student.phone or '',
            'score': float(attempt.score) if attempt.score else 0,
            'percentage': float(attempt.percentage) if attempt.percentage else 0,
            'time_spent': attempt.time_spent,
            'submitted_at': attempt.submitted_at,
            'status': attempt.status,
            'violations_count': attempt.violations_count,
            'rank': i  # Simple ranking based on sort order
        })
    
    # Calculate subject-wise totals (if applicable)
    subject_totals = {}
    if hasattr(exam, 'pattern') and exam.pattern:
        for section in exam.pattern.sections.all():
            questions_count = section.end_question - section.start_question + 1
            total_marks = section.marks_per_question * questions_count
            subject_totals[section.subject] = {
                'total_marks': total_marks,
                'questions': questions_count
            }
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
            'total_questions': exam.total_questions,
            'total_marks': exam.total_marks
        },
        'results': results,
        'subject_totals': subject_totals,
        'total_count': len(results),
        'filters': {
            'search': search,
            'sort_by': sort_by,
            'sort_order': sort_order,
            'status': status_filter
        }
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_student_result_detail(request, exam_id, student_id):
    """Get detailed result for a specific student in an exam"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Get the student
        student = User.objects.get(id=student_id)
        
        # Get the attempt for this student and exam
        attempt = ExamAttempt.objects.filter(exam=exam, student=student).order_by('-created_at').first()
        
        if not attempt:
            return Response({'error': 'No attempt found for this student'}, status=status.HTTP_404_NOT_FOUND)
        
        # Get question evaluations
        from .models import QuestionEvaluation, ExamViolation
        from questions.models import Question
        evaluations = QuestionEvaluation.objects.filter(attempt=attempt).select_related('question').order_by('question_number')
        
        question_responses = []
        for eval in evaluations:
            # Get question details from the related Question model
            question = eval.question
            question_text = question.question_text if question else f'Question {eval.question_number}'
            question_type = question.question_type if question else 'single_mcq'
            correct_answer = question.correct_answer if question else ''
            
            question_responses.append({
                'question_number': eval.question_number,
                'question_text': question_text[:200] + '...' if len(question_text) > 200 else question_text,
                'question_type': question_type,
                'student_answer': eval.student_answer or '',
                'correct_answer': correct_answer,
                'is_correct': eval.is_correct,
                'is_answered': eval.is_answered,
                'marks_obtained': float(eval.marks_obtained) if eval.marks_obtained else 0,
                'max_marks': float(eval.max_marks) if eval.max_marks else 1,
                'time_spent': 0,  # Not tracked per question
            })
        
        # Get violations
        violations = ExamViolation.objects.filter(attempt=attempt).order_by('timestamp')
        violations_list = []
        for v in violations:
            violations_list.append({
                'type': v.get_violation_type_display(),
                'timestamp': v.timestamp.isoformat() if v.timestamp else '',
                'description': v.metadata.get('details', '') if v.metadata else '',
            })
        
        # Calculate section scores if pattern exists
        section_scores = {}
        if hasattr(exam, 'pattern') and exam.pattern:
            for section in exam.pattern.sections.all():
                section_evals = evaluations.filter(
                    question_number__gte=section.start_question,
                    question_number__lte=section.end_question
                )
                correct = section_evals.filter(is_correct=True).count()
                wrong = section_evals.filter(is_correct=False, is_answered=True).count()
                unattempted = section_evals.filter(is_answered=False).count()
                score = sum(float(e.marks_obtained or 0) for e in section_evals)
                max_marks = (section.end_question - section.start_question + 1) * section.marks_per_question
                
                section_scores[str(section.id)] = {
                    'section_name': section.name,
                    'subject': section.subject,
                    'score': score,
                    'max_marks': max_marks,
                    'correct': correct,
                    'wrong': wrong,
                    'unattempted': unattempted,
                }
        
        return Response({
            'attempt_id': attempt.id,
            'student': {
                'id': student.id,
                'name': student.get_full_name() or student.email,
                'email': student.email,
                'phone': student.phone or '',
            },
            'exam': {
                'id': exam.id,
                'title': exam.title,
                'total_questions': exam.total_questions,
                'total_marks': exam.total_marks,
            },
            'score': float(attempt.score) if attempt.score else 0,
            'percentage': float(attempt.percentage) if attempt.percentage else 0,
            'time_spent': attempt.time_spent or 0,
            'started_at': attempt.started_at.isoformat() if attempt.started_at else None,
            'submitted_at': attempt.submitted_at.isoformat() if attempt.submitted_at else None,
            'status': attempt.status,
            'violations_count': attempt.violations_count or 0,
            'violations': violations_list,
            'question_responses': question_responses,
            'section_scores': section_scores,
        })
        
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response({'error': f'Failed to load student result: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def calculate_std_deviation(scores):
    """Calculate standard deviation"""
    if not scores:
        return 0
    mean = sum(scores) / len(scores)
    variance = sum((x - mean) ** 2 for x in scores) / len(scores)
    return variance ** 0.5


def calculate_variance(scores):
    """Calculate variance"""
    if not scores:
        return 0
    mean = sum(scores) / len(scores)
    return sum((x - mean) ** 2 for x in scores) / len(scores)


def calculate_quartiles(scores):
    """Calculate quartiles for box plot"""
    if not scores:
        return {}
    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    
    q1_index = n // 4
    q2_index = n // 2
    q3_index = 3 * n // 4
    
    return {
        'min': min(scores),
        'q1': sorted_scores[q1_index] if q1_index < n else min(scores),
        'median': sorted_scores[q2_index] if q2_index < n else min(scores),
        'q3': sorted_scores[q3_index] if q3_index < n else min(scores),
        'max': max(scores)
    }


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def admin_dashboard_data(request):
    """Get admin dashboard statistics and data"""
    try:
        user = request.user
        
        # Check if user has admin privileges
        if not user.can_manage_exams():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Safely get institute - handle cases where it might be None or cause type errors
        try:
            institute = user.institute
        except Exception as e:
            # If there's a type mismatch or other error accessing institute, treat as None
            institute = None
        
        # Handle super admin or users without institute
        if not institute:
            # Super admin can see all data across all institutes
            if user.role in ['super_admin', 'SUPER_ADMIN']:
                # Return aggregated data for all institutes
                total_exams = Exam.objects.all().count()
                active_exams = Exam.objects.filter(status='active').count()
                published_exams = Exam.objects.filter(status='published').count()
                draft_exams = Exam.objects.filter(status='draft').count()
                User = get_user_model()
                total_students = User.objects.filter(role='student').count()
                total_attempts = ExamAttempt.objects.all().count()
                completed_attempts = ExamAttempt.objects.filter(status='submitted').count()
                in_progress_attempts = ExamAttempt.objects.filter(status='in_progress').count()
                disqualified_attempts = ExamAttempt.objects.filter(status='disqualified').count()
                recent_exams = Exam.objects.all().order_by('-created_at')[:5]
                recent_attempts = ExamAttempt.objects.all().order_by('-created_at')[:10]
                completed_attempts_with_scores = ExamAttempt.objects.filter(
                    status='submitted',
                    score__isnull=False
                )
                average_score = completed_attempts_with_scores.aggregate(avg_score=Avg('score'))['avg_score'] or 0
                total_violations = ExamViolation.objects.all().count()
                total_questions = Question.objects.all().count()
                verified_questions = Question.objects.filter(is_verified=True).count()
                
                return Response({
                    'stats': {
                        'total_exams': total_exams,
                        'active_exams': active_exams,
                        'published_exams': published_exams,
                        'draft_exams': draft_exams,
                        'total_students': total_students,
                        'total_attempts': total_attempts,
                        'completed_attempts': completed_attempts,
                        'in_progress_attempts': in_progress_attempts,
                        'disqualified_attempts': disqualified_attempts,
                        'average_score': round(float(average_score), 2),
                        'total_violations': total_violations,
                        'total_questions': total_questions,
                        'verified_questions': verified_questions,
                    },
                    'recent_exams': ExamSerializer(recent_exams, many=True).data,
                    'recent_attempts': ExamAttemptSerializer(recent_attempts, many=True).data,
                    'institute': None,
                    'is_super_admin': True,
                })
            else:
                return Response({'error': 'User must be associated with an institute'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Calculate statistics for users with institute
        total_exams = Exam.objects.filter(institute=institute).count()
        active_exams = Exam.objects.filter(institute=institute, status='active').count()
        published_exams = Exam.objects.filter(institute=institute, status='published').count()
        draft_exams = Exam.objects.filter(institute=institute, status='draft').count()
        
        # Get total students (users with student role)
        User = get_user_model()
        total_students = User.objects.filter(institute=institute, role='student').count()
        
        # Get exam attempts statistics
        total_attempts = ExamAttempt.objects.filter(exam__institute=institute).count()
        completed_attempts = ExamAttempt.objects.filter(exam__institute=institute, status='submitted').count()
        in_progress_attempts = ExamAttempt.objects.filter(exam__institute=institute, status='in_progress').count()
        disqualified_attempts = ExamAttempt.objects.filter(exam__institute=institute, status='disqualified').count()
        
        # Get recent exams (last 5)
        recent_exams = Exam.objects.filter(institute=institute).order_by('-created_at')[:5]
        
        # Get recent attempts (last 10)
        recent_attempts = ExamAttempt.objects.filter(exam__institute=institute).order_by('-created_at')[:10]
        
        # Calculate average score
        completed_attempts_with_scores = ExamAttempt.objects.filter(
            exam__institute=institute, 
            status='submitted',
            score__isnull=False
        )
        average_score = completed_attempts_with_scores.aggregate(avg_score=Avg('score'))['avg_score'] or 0
        
        # Get violation statistics
        total_violations = ExamViolation.objects.filter(attempt__exam__institute=institute).count()
        
        # Get questions statistics
        total_questions = Question.objects.filter(institute=institute).count()
        verified_questions = Question.objects.filter(institute=institute, is_verified=True).count()
        
        return Response({
            'stats': {
                'total_exams': total_exams,
                'active_exams': active_exams,
                'published_exams': published_exams,
                'draft_exams': draft_exams,
                'total_students': total_students,
                'total_attempts': total_attempts,
                'completed_attempts': completed_attempts,
                'in_progress_attempts': in_progress_attempts,
                'disqualified_attempts': disqualified_attempts,
                'average_score': round(float(average_score), 2),
                'total_violations': total_violations,
                'total_questions': total_questions,
                'verified_questions': verified_questions,
            },
            'recent_exams': ExamSerializer(recent_exams, many=True).data,
            'recent_attempts': ExamAttemptSerializer(recent_attempts, many=True).data,
            'institute': {
                'id': institute.id,
                'name': institute.name,
            }
        })
    except Exception as e:
        import traceback
        return Response({
            'error': 'Failed to load dashboard data',
            'detail': str(e),
            'traceback': traceback.format_exc() if settings.DEBUG else None
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def public_exam_details(request, token):
    """Fetch public exam details using the secure token."""
    try:
        token_uuid = uuid.UUID(str(token))
    except ValueError:
        return Response({'error': 'Invalid exam link'}, status=status.HTTP_404_NOT_FOUND)

    exam = get_object_or_404(Exam.objects.select_related('pattern', 'institute', 'created_by'), public_access_token=token_uuid)

    if not exam.is_public:
        return Response({'error': 'This exam is not publicly accessible'}, status=status.HTTP_403_FORBIDDEN)

    if exam.is_public_link_expired():
        return Response({'error': 'This exam link has expired.'}, status=status.HTTP_403_FORBIDDEN)

    now = timezone.now()
    if now < exam.start_date:
        return Response({'error': 'This exam has not started yet'}, status=status.HTTP_403_FORBIDDEN)

    if now > exam.end_date:
        return Response({'error': 'This exam has ended'}, status=status.HTTP_403_FORBIDDEN)

    pattern = exam.pattern

    return Response({
        'exam_id': exam.id,
        'token': str(exam.public_access_token),
        'title': exam.title,
        'description': exam.description,
        'start_date': exam.start_date,
        'end_date': exam.end_date,
        'duration_minutes': exam.duration_minutes,
        'total_questions': exam.total_questions,
        'total_marks': exam.total_marks,
        'max_attempts': exam.max_attempts,
        'is_public': exam.is_public,
        'institute_name': exam.institute.name,
        'created_by_name': exam.created_by.get_full_name() if exam.created_by else '',
        'pattern': {
            'id': pattern.id if pattern else None,
            'name': pattern.name if pattern else '',
            'total_questions': pattern.total_questions if pattern else 0,
            'total_duration': pattern.total_duration if pattern else 0,
            'total_marks': pattern.total_marks if pattern else 0,
        },
        'public_allow_multiple_devices': exam.public_allow_multiple_devices,
        'public_allowed_ip_ranges': exam.public_allowed_ip_ranges,
        'public_token_expires_at': exam.public_token_expires_at,
    })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def public_exam_access(request):
    """Allow public access to exams with secure token validation and logging."""
    token_value = request.data.get('token')
    first_name = request.data.get('first_name')
    last_name = request.data.get('last_name')
    email = request.data.get('email')
    phone = request.data.get('phone', '')
    student_id = request.data.get('student_id', '')

    if not token_value:
        return Response({'error': 'Exam link token is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        token_uuid = uuid.UUID(str(token_value))
        exam = Exam.objects.select_related('institute').get(public_access_token=token_uuid)
    except (ValueError, Exam.DoesNotExist):
        return Response({'error': 'Invalid or expired exam link'}, status=status.HTTP_404_NOT_FOUND)

    if not all([first_name, last_name, email]):
        return Response({'error': 'Missing required fields: first_name, last_name, email'}, status=status.HTTP_400_BAD_REQUEST)

    client_ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')

    def deny(message, reason, status_code=status.HTTP_403_FORBIDDEN):
        PublicExamAccessLog.objects.create(
            exam=exam,
            access_token=exam.public_access_token,
            status='denied',
            reason=reason,
            student_email=email or '',
            ip_address=client_ip,
            user_agent=user_agent or ''
        )
        return Response({'error': message}, status=status_code)

    if not exam.is_public:
        return deny('This exam is not publicly accessible', 'exam_not_public')

    if exam.is_public_link_expired():
        return deny('This exam link has expired.', 'link_expired')

    now = timezone.now()
    if now < exam.start_date:
        return deny('This exam has not started yet', 'exam_not_started')

    if now > exam.end_date:
        return deny('This exam has ended', 'exam_ended')

    if not exam.is_ip_allowed(client_ip):
        return deny('This exam link is not available from your location.', 'ip_not_allowed')

    if not exam.public_allow_multiple_devices:
        existing_granted = PublicExamAccessLog.objects.filter(
            exam=exam,
            access_token=exam.public_access_token,
            status='granted'
        ).first()
        if existing_granted and (existing_granted.ip_address and client_ip and existing_granted.ip_address != client_ip):
            return deny('This exam link is restricted to a single device.', 'multiple_devices_blocked')

    # Create or fetch a temporary user
    username = f"temp_{email}_{exam.id}_{int(timezone.now().timestamp())}"
    existing_user = User.objects.filter(email=email).first()

    if existing_user:
        user = existing_user
        if existing_user.institute_id != exam.institute_id:
            existing_user.institute = exam.institute
            existing_user.save(update_fields=['institute'])
    else:
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                role='student',
                institute=exam.institute,
                is_active=True,
                is_verified=False
            )
            user.set_unusable_password()
            user.save()
        except IntegrityError:
            # Email was created concurrently or belongs to another institute. Reuse existing record.
            user = User.objects.get(email=email)
            if user.institute_id != exam.institute_id:
                user.institute = exam.institute
                user.save(update_fields=['institute'])

    tokens = get_tokens_for_user(user)

    exam.public_link_usage_count += 1
    exam.public_link_last_used_at = timezone.now()
    exam.save(update_fields=['public_link_usage_count', 'public_link_last_used_at'])

    PublicExamAccessLog.objects.create(
        exam=exam,
        access_token=exam.public_access_token,
        status='granted',
        reason='access_granted',
        student_email=email or '',
        ip_address=client_ip,
        user_agent=user_agent or ''
    )

    return Response({
        'access_token': tokens['access'],
        'refresh_token': tokens['refresh'],
        'exam_id': exam.id,
        'user': {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'institute': {
                'id': exam.institute.id,
                'name': exam.institute.name
            }
        },
        'exam': {
            'id': exam.id,
            'title': exam.title,
            'duration_minutes': exam.duration_minutes,
            'total_questions': exam.total_questions,
            'total_marks': exam.total_marks
        },
        'message': 'Access granted successfully'
    })


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def public_exam_link_details(request, exam_id):
    """View or update public exam link configuration for an exam."""
    exam = get_object_or_404(Exam, id=exam_id)

    if exam.institute != request.user.institute or not request.user.can_manage_exams():
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'POST':
        regenerate = request.data.get('regenerate_token', False)
        expires_at_raw = request.data.get('expires_at')
        allowed_ips_raw = request.data.get('allowed_ips')
        allow_multiple_devices = request.data.get('allow_multiple_devices')

        update_fields = []

        if regenerate:
            exam.regenerate_public_token()
            exam.refresh_from_db()

        if expires_at_raw is not None:
            if expires_at_raw == '' or expires_at_raw is False:
                exam.public_token_expires_at = None
            else:
                try:
                    expires_at = datetime.fromisoformat(str(expires_at_raw).replace('Z', '+00:00'))
                    if timezone.is_naive(expires_at):
                        expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
                    exam.public_token_expires_at = expires_at
                except ValueError:
                    return Response({'error': 'Invalid expiry datetime format'}, status=status.HTTP_400_BAD_REQUEST)
            update_fields.append('public_token_expires_at')

        if allowed_ips_raw is not None:
            exam.public_allowed_ip_ranges = clean_ip_ranges(allowed_ips_raw)
            update_fields.append('public_allowed_ip_ranges')

        if allow_multiple_devices is not None:
            exam.public_allow_multiple_devices = bool(allow_multiple_devices)
            update_fields.append('public_allow_multiple_devices')

        if update_fields:
            exam.save(update_fields=update_fields)
            exam.refresh_from_db()

    recent_logs = exam.public_access_logs.all().order_by('-accessed_at')[:5]
    recent_logs_data = [
        {
            'status': log.status,
            'reason': log.reason,
            'student_email': log.student_email,
            'ip_address': log.ip_address,
            'accessed_at': log.accessed_at,
        }
        for log in recent_logs
    ]

    return Response({
        'token': str(exam.public_access_token),
        'share_url': f"{settings.FRONTEND_URL}/public-exam/{exam.public_access_token}",
        'expires_at': exam.public_token_expires_at,
        'allowed_ips': exam.public_allowed_ip_ranges,
        'allow_multiple_devices': exam.public_allow_multiple_devices,
        'usage_count': exam.public_link_usage_count,
        'last_used_at': exam.public_link_last_used_at,
        'created_at': exam.public_link_created_at,
        'is_expired': exam.is_public_link_expired(),
        'recent_logs': recent_logs_data,
    })


# Export Data APIs

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_export_data(request, exam_id):
    """Export exam data in various formats (CSV, Excel, PDF)"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    export_format = request.GET.get('format', 'csv').lower()
    
    if export_format == 'csv':
        return export_results_csv(exam)
    elif export_format == 'excel':
        return export_results_excel(exam)
    elif export_format == 'pdf':
        return export_results_pdf(exam)
    else:
        return Response({'error': 'Invalid format. Use csv, excel, or pdf'}, status=status.HTTP_400_BAD_REQUEST)


def export_results_csv(exam):
    """Export student results as CSV"""
    # Get all attempts for this exam
    attempts = ExamAttempt.objects.filter(
        exam=exam, 
        status__in=['submitted', 'auto_submitted']
    ).select_related('student', 'result').order_by('-submitted_at')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="exam_{exam.id}_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    
    # Write header
    writer.writerow([
        'Student ID', 'Student Name', 'Email', 'Score', 'Percentage', 
        'Grade', 'Time Spent (minutes)', 'Submitted At', 'Status',
        'Correct Answers', 'Wrong Answers', 'Unattempted'
    ])
    
    # Write data
    for attempt in attempts:
        result = attempt.result
        correct_count = 0
        wrong_count = 0
        unattempted_count = 0
        
        if result and result.answers:
            for q_id, answer_data in result.answers.items():
                if answer_data.get('is_correct'):
                    correct_count += 1
                elif answer_data.get('is_answered', False):
                    wrong_count += 1
                else:
                    unattempted_count += 1
        
        # Calculate grade
        percentage = (float(attempt.score) / exam.total_marks * 100) if attempt.score and exam.total_marks > 0 else 0
        if percentage >= 90:
            grade = 'A+'
        elif percentage >= 80:
            grade = 'A'
        elif percentage >= 70:
            grade = 'B+'
        elif percentage >= 60:
            grade = 'B'
        elif percentage >= 50:
            grade = 'C'
        else:
            grade = 'F'
        
        writer.writerow([
            attempt.student.id,
            f"{attempt.student.first_name} {attempt.student.last_name}".strip(),
            attempt.student.email,
            attempt.score or 0,
            f"{percentage:.2f}%",
            grade,
            attempt.time_spent or 0,
            attempt.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if attempt.submitted_at else '',
            attempt.status,
            correct_count,
            wrong_count,
            unattempted_count
        ])
    
    return response


def export_results_excel(exam):
    """Export student results as Excel (CSV format for now)"""
    # For now, return CSV format. In production, you'd use openpyxl or xlsxwriter
    return export_results_csv(exam)


def export_results_pdf(exam):
    """Export analytics report as PDF (CSV format for now)"""
    # For now, return CSV format. In production, you'd use reportlab or weasyprint
    return export_results_csv(exam)


# AI-Powered Insights API

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def exam_ai_insights(request, exam_id):
    """Get AI-powered insights and recommendations for exam performance"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get exam data
    attempts = ExamAttempt.objects.filter(
        exam=exam, 
        status__in=['submitted', 'auto_submitted']
    ).select_related('student', 'result')
    
    if not attempts.exists():
        return Response({
            'insights': [],
            'recommendations': [],
            'anomalies': [],
            'message': 'No data available for analysis'
        })
    
    # Calculate basic metrics
    scores = [float(attempt.score) for attempt in attempts if attempt.score is not None]
    times = [attempt.time_spent for attempt in attempts if attempt.time_spent > 0]
    
    insights = []
    recommendations = []
    anomalies = []
    
    # Performance Insights
    avg_score = sum(scores) / len(scores) if scores else 0
    completion_rate = (attempts.count() / max(1, ExamInvitation.objects.filter(exam=exam).count())) * 100
    
    if avg_score < 50:
        insights.append({
            'type': 'performance',
            'title': 'Low Average Performance',
            'description': f'Average score is {avg_score:.1f}%, indicating students are struggling with the content.',
            'severity': 'high',
            'metric': 'average_score',
            'value': avg_score
        })
        recommendations.append({
            'category': 'content',
            'title': 'Review Question Difficulty',
            'description': 'Consider reviewing question difficulty levels and providing additional study materials.',
            'priority': 'high'
        })
    elif avg_score > 85:
        insights.append({
            'type': 'performance',
            'title': 'High Performance',
            'description': f'Average score is {avg_score:.1f}%, indicating good content mastery.',
            'severity': 'low',
            'metric': 'average_score',
            'value': avg_score
        })
    
    # Time Analysis
    if times:
        avg_time = sum(times) / len(times)
        if avg_time < exam.duration_minutes * 0.3:
            insights.append({
                'type': 'time',
                'title': 'Rushed Completion',
                'description': f'Students are completing the exam in {avg_time:.1f} minutes (30% of allocated time).',
                'severity': 'medium',
                'metric': 'average_time',
                'value': avg_time
            })
            recommendations.append({
                'category': 'assessment',
                'title': 'Increase Question Complexity',
                'description': 'Consider adding more challenging questions or increasing time limits.',
                'priority': 'medium'
            })
    
    # Completion Rate Analysis
    if completion_rate < 70:
        insights.append({
            'type': 'engagement',
            'title': 'Low Completion Rate',
            'description': f'Only {completion_rate:.1f}% of invited students completed the exam.',
            'severity': 'high',
            'metric': 'completion_rate',
            'value': completion_rate
        })
        recommendations.append({
            'category': 'engagement',
            'title': 'Improve Student Engagement',
            'description': 'Consider sending reminders, improving exam instructions, or offering incentives.',
            'priority': 'high'
        })
    
    # Anomaly Detection
    if len(scores) > 5:  # Need sufficient data for anomaly detection
        std_dev = calculate_std_deviation(scores)
        mean_score = sum(scores) / len(scores)
        
        # Detect unusually high or low scores
        for attempt in attempts:
            if attempt.score:
                score = float(attempt.score)
                z_score = abs((score - mean_score) / std_dev) if std_dev > 0 else 0
                
                if z_score > 2.5:  # More than 2.5 standard deviations from mean
                    anomalies.append({
                        'type': 'score_anomaly',
                        'student_id': attempt.student.id,
                        'student_name': f"{attempt.student.first_name} {attempt.student.last_name}".strip(),
                        'score': score,
                        'z_score': z_score,
                        'description': f'Unusually {"high" if score > mean_score else "low"} score detected'
                    })
    
    # Question Analysis Insights
    question_analytics = QuestionAnalytics.objects.filter(exam=exam)
    difficult_questions = []
    
    for qa in question_analytics:
        if qa.total_attempts > 0:
            success_rate = (qa.correct_attempts / qa.total_attempts) * 100
            if success_rate < 30:
                difficult_questions.append(qa)
    
    if difficult_questions:
        insights.append({
            'type': 'questions',
            'title': 'Difficult Questions Detected',
            'description': f'{len(difficult_questions)} questions have success rates below 30%.',
            'severity': 'medium',
            'metric': 'difficult_questions',
            'value': len(difficult_questions)
        })
        recommendations.append({
            'category': 'content',
            'title': 'Review Difficult Questions',
            'description': 'Review questions with low success rates for clarity and appropriateness.',
            'priority': 'medium'
        })
    
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
            'total_attempts': attempts.count(),
            'completion_rate': completion_rate,
            'average_score': avg_score
        },
        'insights': insights,
        'recommendations': recommendations,
        'anomalies': anomalies,
        'generated_at': datetime.now().isoformat()
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_latest_exam_attempt(request, exam_id):
    """Get the latest exam attempt for a specific exam by the current user"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Get the latest attempt for this exam by this user (including disqualified)
        latest_attempt = ExamAttempt.objects.filter(
            exam=exam,
            student=user,
            status__in=['submitted', 'auto_submitted', 'disqualified']
        ).order_by('-submitted_at').first()
        
        if not latest_attempt:
            return Response(
                {'error': 'No completed attempts found for this exam'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response({
            'attempt_id': str(latest_attempt.id),
            'exam_id': exam_id,
            'submitted_at': latest_attempt.submitted_at,
            'score': latest_attempt.score,
            'percentage': latest_attempt.percentage,
            'status': latest_attempt.status
        })
        
    except Exam.DoesNotExist:
        return Response(
            {'error': 'Exam not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': f'Failed to get latest attempt: {str(e)}'}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_exam_results_csv(request, exam_id):
    """Export exam results to CSV"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get all attempts for this exam
        attempts = ExamAttempt.objects.filter(exam=exam, status='submitted').select_related('student')
        
        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="exam_{exam_id}_results_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        
        writer = csv.writer(response)
        
        # Write header
        writer.writerow([
            'Student ID', 'Student Name', 'Student Email', 'Attempt Number',
            'Started At', 'Submitted At', 'Time Spent (minutes)', 'Score',
            'Percentage', 'Status'
        ])
        
        # Write data
        for attempt in attempts:
            time_spent_minutes = attempt.time_spent / 60 if attempt.time_spent else 0
            writer.writerow([
                attempt.student.id,
                f"{attempt.student.first_name} {attempt.student.last_name}".strip(),
                attempt.student.email,
                attempt.attempt_number,
                attempt.started_at.strftime('%Y-%m-%d %H:%M:%S') if attempt.started_at else '',
                attempt.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if attempt.submitted_at else '',
                round(time_spent_minutes, 2),
                attempt.score or 0,
                attempt.percentage or 0,
                attempt.status
            ])
        
        return response
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Export failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_exam_results_excel(request, exam_id):
    """Export exam results to Excel"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get all attempts for this exam
        attempts = ExamAttempt.objects.filter(exam=exam, status='submitted').select_related('student')
        
        # Create Excel response
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="exam_{exam_id}_results_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'
        
        # Create workbook and worksheet
        workbook = xlsxwriter.Workbook(response)
        worksheet = workbook.add_worksheet('Exam Results')
        
        # Define formats
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1
        })
        
        data_format = workbook.add_format({'border': 1})
        number_format = workbook.add_format({'num_format': '0.00', 'border': 1})
        
        # Write headers
        headers = [
            'Student ID', 'Student Name', 'Student Email', 'Attempt Number',
            'Started At', 'Submitted At', 'Time Spent (minutes)', 'Score',
            'Percentage', 'Status'
        ]
        
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        # Write data
        for row, attempt in enumerate(attempts, 1):
            time_spent_minutes = attempt.time_spent / 60 if attempt.time_spent else 0
            data = [
                attempt.student.id,
                f"{attempt.student.first_name} {attempt.student.last_name}".strip(),
                attempt.student.email,
                attempt.attempt_number,
                attempt.started_at.strftime('%Y-%m-%d %H:%M:%S') if attempt.started_at else '',
                attempt.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if attempt.submitted_at else '',
                round(time_spent_minutes, 2),
                attempt.score or 0,
                attempt.percentage or 0,
                attempt.status
            ]
            
            for col, value in enumerate(data):
                if col in [6, 7, 8]:  # Numeric columns
                    worksheet.write(row, col, value, number_format)
                else:
                    worksheet.write(row, col, value, data_format)
        
        # Auto-fit columns
        worksheet.set_column('A:J', 15)
        
        workbook.close()
        return response
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Export failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_exam_results_pdf(request, exam_id):
    """Export exam results to PDF"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT']:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get all attempts for this exam
        attempts = ExamAttempt.objects.filter(exam=exam, status='submitted').select_related('student')
        
        # Create PDF response
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="exam_{exam_id}_results_{timezone.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        
        # Create PDF document
        doc = SimpleDocTemplate(response, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=1  # Center alignment
        )
        story.append(Paragraph(f"Exam Results Report: {exam.title}", title_style))
        story.append(Spacer(1, 12))
        
        # Exam details
        exam_info = [
            ['Exam Title:', exam.title],
            ['Description:', exam.description or 'No description'],
            ['Duration:', f"{exam.duration_minutes} minutes"],
            ['Total Questions:', str(exam.total_questions)],
            ['Total Marks:', str(exam.total_marks)],
            ['Generated On:', timezone.now().strftime('%Y-%m-%d %H:%M:%S')]
        ]
        
        exam_table = Table(exam_info, colWidths=[2*inch, 4*inch])
        exam_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(exam_table)
        story.append(Spacer(1, 20))
        
        # Results table
        story.append(Paragraph("Student Results", styles['Heading2']))
        story.append(Spacer(1, 12))
        
        # Table headers
        headers = [
            'Student Name', 'Email', 'Attempt', 'Score', 'Percentage', 
            'Time Spent (min)', 'Submitted At'
        ]
        
        # Table data
        data = [headers]
        for attempt in attempts:
            time_spent_minutes = attempt.time_spent / 60 if attempt.time_spent else 0
            data.append([
                f"{attempt.student.first_name} {attempt.student.last_name}".strip(),
                attempt.student.email,
                str(attempt.attempt_number),
                str(attempt.score or 0),
                f"{attempt.percentage or 0:.2f}%",
                f"{time_spent_minutes:.2f}",
                attempt.submitted_at.strftime('%Y-%m-%d %H:%M') if attempt.submitted_at else 'N/A'
            ])
        
        results_table = Table(data, colWidths=[1.5*inch, 2*inch, 0.7*inch, 0.7*inch, 0.8*inch, 1*inch, 1.2*inch])
        results_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8)
        ]))
        
        story.append(results_table)
        
        # Summary statistics
        if attempts.exists():
            story.append(Spacer(1, 20))
            story.append(Paragraph("Summary Statistics", styles['Heading2']))
            story.append(Spacer(1, 12))
            
            total_attempts = attempts.count()
            avg_score = attempts.aggregate(avg_score=Avg('score'))['avg_score'] or 0
            avg_percentage = attempts.aggregate(avg_percentage=Avg('percentage'))['avg_percentage'] or 0
            avg_time = attempts.aggregate(avg_time=Avg('time_spent'))['avg_time'] or 0
            avg_time_minutes = avg_time / 60
            
            summary_data = [
                ['Total Attempts:', str(total_attempts)],
                ['Average Score:', f"{avg_score:.2f}"],
                ['Average Percentage:', f"{avg_percentage:.2f}%"],
                ['Average Time Spent:', f"{avg_time_minutes:.2f} minutes"]
            ]
            
            summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('BACKGROUND', (1, 0), (1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            
            story.append(summary_table)
        
        # Build PDF
        doc.build(story)
        return response
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Export failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def export_all_attempts(request):
    """Export filtered exam attempts across all exams (CSV only for now)."""
    if getattr(request.user, 'role', None) == 'student':
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

    export_format = request.query_params.get('format', 'csv').lower()
    queryset = filter_all_exam_attempts(request)

    if export_format != 'csv':
        return Response({'error': 'Only CSV export is supported currently.'}, status=status.HTTP_400_BAD_REQUEST)

    filename = f"all_exam_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Exam ID', 'Exam Title', 'Student ID', 'Student Name', 'Email', 'Status',
        'Score', 'Percentage', 'Time Spent (seconds)', 'Started At', 'Submitted At',
        'Violations', 'Attempt Number'
    ])

    for attempt in queryset:
        if attempt.percentage is not None:
            percentage = float(attempt.percentage)
        elif attempt.score is not None and attempt.exam.total_marks:
            percentage = float(attempt.score) / attempt.exam.total_marks * 100
        else:
            percentage = 0.0

        writer.writerow([
            attempt.exam.id,
            attempt.exam.title,
            attempt.student.id,
            f"{attempt.student.first_name} {attempt.student.last_name}".strip(),
            attempt.student.email,
            attempt.status,
            attempt.score or 0,
            f"{percentage:.2f}",
            attempt.time_spent or 0,
            attempt.started_at.isoformat() if attempt.started_at else '',
            attempt.submitted_at.isoformat() if attempt.submitted_at else '',
            attempt.violations_count,
            attempt.attempt_number,
        ])

    return response



# Geolocation API Endpoints
@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def capture_location(request):
    """
    Capture and store geolocation data for an exam attempt.
    
    POST /api/exams/capture-location/
    
    Request body:
    {
        "attempt_id": 123,
        "latitude": 27.7172,
        "longitude": 85.3240,
        "permission_denied": false
    }
    
    Implements requirements 2.2, 2.3 from exam-security-enhancements spec.
    """
    from .geolocation_service import GeolocationService
    from .serializers import GeolocationCaptureSerializer
    from django.core.exceptions import ValidationError
    
    # Validate request data
    serializer = GeolocationCaptureSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    attempt_id = serializer.validated_data['attempt_id']
    latitude = serializer.validated_data.get('latitude')
    longitude = serializer.validated_data.get('longitude')
    permission_denied = serializer.validated_data.get('permission_denied', False)
    
    # Get exam attempt and verify ownership
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id)
    except ExamAttempt.DoesNotExist:
        return Response(
            {'error': 'Exam attempt not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Verify that the user owns this attempt
    if attempt.student != request.user:
        return Response(
            {'error': 'You do not have permission to update this exam attempt'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Capture geolocation using the service
    try:
        result = GeolocationService.capture_location(
            exam_attempt=attempt,
            latitude=latitude,
            longitude=longitude,
            permission_denied=permission_denied
        )
        
        return Response(result, status=status.HTTP_200_OK)
        
    except ValidationError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {'error': f'Failed to capture geolocation: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_attempt_location(request, attempt_id):
    """
    Retrieve geolocation data for a specific exam attempt.
    
    GET /api/exams/attempt/{attempt_id}/location/
    
    Implements requirements 2.2, 2.3 from exam-security-enhancements spec.
    """
    from .geolocation_service import GeolocationService
    from .serializers import GeolocationDataSerializer
    from django.core.exceptions import ValidationError
    
    # Get exam attempt
    try:
        attempt = ExamAttempt.objects.get(id=attempt_id)
    except ExamAttempt.DoesNotExist:
        return Response(
            {'error': 'Exam attempt not found'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Check permissions
    # Students can only view their own attempts
    # Admins can view any attempt from their institute
    user = request.user
    if user.role in ['student', 'STUDENT']:
        if attempt.student != user:
            return Response(
                {'error': 'You do not have permission to view this exam attempt'},
                status=status.HTTP_403_FORBIDDEN
            )
    else:
        # Admin/teacher check - must be from same institute
        if not user.can_manage_exams() or attempt.exam.institute != user.institute:
            return Response(
                {'error': 'You do not have permission to view this exam attempt'},
                status=status.HTTP_403_FORBIDDEN
            )
    
    # Retrieve geolocation data
    try:
        location_data = GeolocationService.get_location_for_attempt(attempt_id)
        
        if location_data is None:
            return Response(
                {'error': 'Exam attempt not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Serialize and return the data
        serializer = GeolocationDataSerializer(location_data)
        return Response(serializer.data, status=status.HTTP_200_OK)
        
    except ValidationError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {'error': f'Failed to retrieve geolocation: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
