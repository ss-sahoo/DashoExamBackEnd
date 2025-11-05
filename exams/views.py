from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db import transaction
from django.utils import timezone
from django.db.models import Q, Count, Avg, Sum
from django.contrib.auth import get_user_model
from django.http import HttpResponse, JsonResponse
from decimal import Decimal
import json
import csv
import io
import pandas as pd
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import xlsxwriter
from .models import Exam, ExamAttempt, ExamResult, ExamInvitation, ExamAnalytics, ExamViolation, ExamProctoring, QuestionAnalytics, QuestionEvaluation
from questions.models import Question
from .serializers import (
    ExamSerializer, ExamCreateSerializer, ExamAttemptSerializer, ExamResultSerializer,
    ExamInvitationSerializer, ExamAnalyticsSerializer, ExamStartSerializer, ExamSubmitSerializer,
    ExamViolationSerializer, ExamProctoringSerializer, ViolationLogSerializer, 
    ExamAccessSerializer, SnapshotUploadSerializer, ExamRescheduleSerializer,
    ExamRescheduleRequestSerializer, ExamRescheduleReviewSerializer, TimezoneListSerializer
)

# Import evaluation views
from .evaluation_views import (
    evaluate_exam_attempt, get_evaluation_progress, get_question_evaluations,
    manual_evaluate_question, ai_evaluate_question, get_evaluation_batches,
    update_evaluation_settings, get_pending_evaluations, batch_ai_evaluate
)
from .ai_proctoring import AIProctoringSystem

# Create a global instance
proctoring_analyzer = AIProctoringSystem()
from accounts.jwt_utils import get_tokens_for_user

User = get_user_model()


class ExamListView(generics.ListCreateAPIView):
    """List and create exams"""
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ExamCreateSerializer
        return ExamSerializer

    def get_queryset(self):
        user = self.request.user
        status_filter = self.request.query_params.get('status')
        
        queryset = Exam.objects.filter(institute=user.institute)
        
        if user.role == 'student':
            # Students can only see published/active exams they're allowed to take
            queryset = queryset.filter(
                Q(is_public=True) | Q(allowed_users=user)
            ).filter(status__in=['published', 'active'])
        elif user.can_manage_exams():
            # Admins can see all exams
            if status_filter:
                queryset = queryset.filter(status=status_filter)
        
        return queryset.order_by('-created_at')

    def perform_create(self, serializer):
        user = self.request.user
        if not user.can_create_exams():
            raise permissions.PermissionDenied("You don't have permission to create exams")
        
        serializer.save(
            institute=user.institute,
            created_by=user
        )


class ExamDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, and delete exams"""
    serializer_class = ExamSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.can_manage_exams():
            return Exam.objects.filter(institute=user.institute)
        elif user.role == 'student':
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
        
        if user.role == 'student':
            return ExamAttempt.objects.filter(exam_id=exam_id, student=user)
        else:
            return ExamAttempt.objects.filter(exam_id=exam_id)


class AllExamAttemptsListView(generics.ListAPIView):
    """List all exam attempts across all exams (for admins)"""
    serializer_class = ExamAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Disable pagination for this view

    def get_queryset(self):
        user = self.request.user
        
        # Only allow non-student users to see all attempts
        if user.role == 'student':
            return ExamAttempt.objects.none()  # Students can't see all attempts
        
        # For admins, return all attempts
        return ExamAttempt.objects.select_related('exam', 'student').order_by('-created_at')


class ExamAttemptDetailView(generics.RetrieveUpdateAPIView):
    """Get and update exam attempts"""
    serializer_class = ExamAttemptSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'student':
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
    
    # Check permissions
    if not exam.is_public and user not in exam.allowed_users.all():
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
        if request.user.role == 'student':
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
    """Upload webcam snapshot for proctoring analysis"""
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
        
        # Store snapshot info
        snapshot_info = {
            'timestamp': serializer.validated_data['timestamp'].isoformat(),
            'metadata': serializer.validated_data['metadata'],
            'analysis': analysis
        }
        
        proctoring.snapshots.append(snapshot_info)
        proctoring.save()
        
        # Log any violations found (only for proctoring snapshots, not identity verification)
        if not is_identity_verification and analysis.get('success') and analysis.get('violations'):
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
            'auto_disqualified': attempt.status == 'disqualified'
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
        if request.user.role == 'student':
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
    for section in pattern.sections.all():
        # Calculate section score from evaluations
        section_evaluations = QuestionEvaluation.objects.filter(
            attempt=attempt,
            question_number__gte=section.start_question,
            question_number__lte=section.end_question
        )
        
        section_score = sum(eval.marks_obtained for eval in section_evaluations)
        max_marks = section.marks_per_question * (section.end_question - section.start_question + 1)
        
        # For objective questions, show immediate results
        if section.question_type in ['mcq', 'single_mcq', 'multiple_mcq', 'numerical']:
            section_results[str(section.id)] = {
                'section_name': section.name,
                'question_type': section.question_type,
                'score': section_score,
                'max_marks': max_marks,
                'status': 'available',
                'feedback': 'Immediate feedback available'
            }
        else:
            # For subjective questions, show pending status
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
    
    # Calculate correct answers from evaluations
    correct_answers_count = QuestionEvaluation.objects.filter(
        attempt=attempt,
        is_correct=True
    ).count()
    
    # Calculate total questions from pattern or evaluations
    if result:
        total_questions = result.total_questions_attempted
    else:
        # Count from evaluations or pattern
        total_questions = QuestionEvaluation.objects.filter(attempt=attempt).count()
        if total_questions == 0:
            # Fallback to pattern total questions
            total_questions = exam.total_questions
    
    return Response({
        'attempt': ExamAttemptSerializer(attempt).data,
        'overall_score': correct_answers_count,  # Use actual correct answers count
        'total_questions': total_questions,
        'percentage': attempt.percentage,
        'section_results': section_results,
        'detailed_answers': detailed_answers,
        'submitted_at': attempt.submitted_at,
        'time_spent': attempt.time_spent
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
    if request.user.role != 'student':
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    user = request.user
    now = timezone.now()
    
    # Get available exams (published/active, within time window, not exceeded attempts)
    available_exams = Exam.objects.filter(
        Q(is_public=True) | Q(allowed_users=user),
        status__in=['published', 'active'],
        start_date__lte=now,
        end_date__gte=now
    ).exclude(
        attempts__student=user,
        attempts__status__in=['submitted', 'auto_submitted']
    ).distinct()
    
    # Get scheduled exams (future exams that students can see)
    scheduled_exams = Exam.objects.filter(
        Q(is_public=True) | Q(allowed_users=user),
        status__in=['published', 'active'],
        start_date__gt=now,
        end_date__gte=now
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
    """Get comprehensive analytics dashboard for an exam"""
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    
    user = request.user
    if not user.can_manage_exams() or exam.institute != user.institute:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    # Get or create analytics
    analytics, created = ExamAnalytics.objects.get_or_create(exam=exam)
    
    # Get all attempts for this exam
    attempts = ExamAttempt.objects.filter(exam=exam, status__in=['submitted', 'auto_submitted'])
    
    # Calculate statistics
    scores = [float(attempt.score) for attempt in attempts if attempt.score is not None]
    times = [attempt.time_spent for attempt in attempts if attempt.time_spent > 0]
    
    # Basic statistics
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
    
    # Heat map data (subject-wise performance)
    heatmap_data = []
    if hasattr(exam, 'pattern') and exam.pattern:
        for section in exam.pattern.sections.all():
            section_scores = []
            for attempt in attempts:
                if hasattr(attempt, 'result') and attempt.result:
                    section_score = attempt.result.section_scores.get(str(section.id), 0)
                    section_scores.append(section_score)
            
            questions_count = section.end_question - section.start_question + 1
            total_marks = section.marks_per_question * questions_count
            heatmap_data.append({
                'section_name': section.name,
                'subject': section.subject,
                'average_score': sum(section_scores) / len(section_scores) if section_scores else 0,
                'max_marks': total_marks,
                'total_questions': questions_count
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
    user = request.user
    
    # Check if user has admin privileges
    if not user.can_manage_exams():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    institute = user.institute
    
    # Calculate statistics
    total_exams = Exam.objects.filter(institute=institute).count()
    active_exams = Exam.objects.filter(institute=institute, status='active').count()
    published_exams = Exam.objects.filter(institute=institute, status='published').count()
    draft_exams = Exam.objects.filter(institute=institute, status='draft').count()
    
    # Get total students (users with student role)
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

@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def public_exam_access(request):
    """Allow public access to exams with temporary user creation"""
    try:
        exam_id = request.data.get('exam_id')
        first_name = request.data.get('first_name')
        last_name = request.data.get('last_name')
        email = request.data.get('email')
        phone = request.data.get('phone', '')
        student_id = request.data.get('student_id', '')
        
        if not all([exam_id, first_name, last_name, email]):
            return Response({
                'error': 'Missing required fields: exam_id, first_name, last_name, email'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get the exam
        try:
            exam = Exam.objects.get(id=exam_id)
        except Exam.DoesNotExist:
            return Response({
                'error': 'Exam not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if exam is public and within time window
        now = timezone.now()
        if not exam.is_public:
            return Response({
                'error': 'This exam is not publicly accessible'
            }, status=status.HTTP_403_FORBIDDEN)
        
        if now < exam.start_date:
            return Response({
                'error': 'This exam has not started yet'
            }, status=status.HTTP_403_FORBIDDEN)
        
        if now > exam.end_date:
            return Response({
                'error': 'This exam has ended'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Create or get a temporary user for this exam
        username = f"temp_{email}_{exam_id}_{int(timezone.now().timestamp())}"
        
        # Check if user already exists with this email for this exam
        existing_user = User.objects.filter(email=email, institute=exam.institute).first()
        
        if existing_user:
            user = existing_user
        else:
            # Create temporary user
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
            user.set_unusable_password()  # No password for temporary users
            user.save()
        
        # Generate JWT token for the user
        tokens = get_tokens_for_user(user)
        
        return Response({
            'access_token': tokens['access'],
            'refresh_token': tokens['refresh'],
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
        
    except Exception as e:
        return Response({
            'error': 'Failed to grant exam access',
            'detail': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
        if user.role == 'student':
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
        if user.role == 'student':
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
        if user.role == 'student':
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