from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone

from .models import Exam, ExamAttempt, QuestionEvaluation, EvaluationBatch, EvaluationSettings, EvaluationProgress
from .evaluation_service import EvaluationService
from .serializers import (
    QuestionEvaluationSerializer, 
    EvaluationBatchSerializer, 
    EvaluationSettingsSerializer,
    EvaluationProgressSerializer
)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def evaluate_exam_attempt(request, attempt_id):
    """Evaluate an exam attempt using the evaluation service"""
    try:
        attempt = get_object_or_404(ExamAttempt, id=attempt_id)
        
        # Check permissions
        user = request.user
        if user.role == 'student' and attempt.student != user:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        if not user.can_manage_exams() and attempt.student != user:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get answers from request
        answers = request.data.get('answers', {})
        if not answers:
            return Response({'error': 'No answers provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Initialize evaluation service
        evaluation_service = EvaluationService(attempt)
        
        # Perform evaluation
        evaluation_result = evaluation_service.evaluate_attempt(answers)
        
        # Update attempt with final score
        final_score = evaluation_result['final_score']
        attempt.score = final_score
        attempt.percentage = (final_score / attempt.exam.total_marks) * 100 if attempt.exam.total_marks > 0 else 0
        attempt.save()
        
        return Response({
            'success': True,
            'message': 'Evaluation completed successfully',
            'evaluation_result': evaluation_result,
            'final_score': final_score,
            'percentage': attempt.percentage
        })
        
    except Exception as e:
        return Response({
            'error': f'Evaluation failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_evaluation_progress(request, exam_id):
    """Get evaluation progress for an exam"""
    try:
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Check permissions
        user = request.user
        if not user.can_manage_exams() or exam.institute != user.institute:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        progress, created = EvaluationProgress.objects.get_or_create(exam=exam)
        serializer = EvaluationProgressSerializer(progress)
        
        return Response(serializer.data)
    except Exception as e:
        return Response({
            'error': f'Failed to get evaluation progress: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_question_evaluations(request, attempt_id):
    """Get question evaluations for an attempt"""
    try:
        attempt = get_object_or_404(ExamAttempt, id=attempt_id)
        
        # Check permissions
        user = request.user
        if user.role == 'student' and attempt.student != user:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        if not user.can_manage_exams() and attempt.student != user:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        question_evaluations = QuestionEvaluation.objects.filter(attempt=attempt).order_by('question_number')
        serializer = QuestionEvaluationSerializer(question_evaluations, many=True)
        
        return Response(serializer.data)
        
    except Exception as e:
        return Response({
            'error': f'Failed to get question evaluations: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def manual_evaluate_question(request, evaluation_id):
    """Manually evaluate a question"""
    try:
        question_eval = get_object_or_404(QuestionEvaluation, id=evaluation_id)
        
        # Check permissions
        user = request.user
        if not user.can_manage_exams() or question_eval.attempt.exam.institute != user.institute:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get evaluation data
        marks_obtained = request.data.get('marks_obtained', 0)
        is_correct = request.data.get('is_correct', False)
        feedback = request.data.get('feedback', '')
        
        # Validate marks
        if marks_obtained < 0 or marks_obtained > float(question_eval.max_marks):
            return Response({
                'error': f'Marks must be between 0 and {question_eval.max_marks}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update evaluation
        with transaction.atomic():
            question_eval.marks_obtained = marks_obtained
            question_eval.is_correct = is_correct
            question_eval.evaluation_status = 'manually_evaluated'
            question_eval.evaluated_by = user
            question_eval.evaluated_at = timezone.now()
            question_eval.manual_feedback = feedback
            question_eval.save()
            
            # Update evaluation progress
            progress = EvaluationProgress.objects.get(exam=question_eval.attempt.exam)
            progress.manually_evaluated += 1
            progress.pending_evaluation -= 1
            progress.save()
            
            # Update attempt score
            attempt = question_eval.attempt
            evaluation_service = EvaluationService(attempt)
            final_score = evaluation_service._calculate_final_score()
            attempt.score = final_score
            attempt.percentage = (final_score / attempt.exam.total_marks) * 100 if attempt.exam.total_marks > 0 else 0
            attempt.save()
        
        return Response({
            'success': True,
            'message': 'Question evaluated successfully',
            'evaluation': QuestionEvaluationSerializer(question_eval).data
        })
        
    except Exception as e:
        return Response({
            'error': f'Manual evaluation failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ai_evaluate_question(request, evaluation_id):
    """Evaluate a question using AI"""
    try:
        question_eval = get_object_or_404(QuestionEvaluation, id=evaluation_id)
        
        # Check permissions
        user = request.user
        if not user.can_manage_exams() or question_eval.attempt.exam.institute != user.institute:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if AI evaluation is enabled
        settings = EvaluationSettings.objects.get(exam=question_eval.attempt.exam)
        if not settings.enable_ai_evaluation:
            return Response({
                'error': 'AI evaluation is not enabled for this exam'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Perform AI evaluation
        attempt = question_eval.attempt
        evaluation_service = EvaluationService(attempt)
        ai_result = evaluation_service.evaluate_with_ai(question_eval)
        
        if ai_result['success']:
            # Update evaluation progress
            progress = EvaluationProgress.objects.get(exam=question_eval.attempt.exam)
            progress.ai_evaluated += 1
            progress.pending_evaluation -= 1
            progress.save()
            
            # Update attempt score
            final_score = evaluation_service._calculate_final_score()
            attempt.score = final_score
            attempt.percentage = (final_score / attempt.exam.total_marks) * 100 if attempt.exam.total_marks > 0 else 0
            attempt.save()
        
        return Response({
            'success': ai_result['success'],
            'message': 'AI evaluation completed' if ai_result['success'] else 'AI evaluation failed',
            'result': ai_result,
            'evaluation': QuestionEvaluationSerializer(question_eval).data
        })
        
    except Exception as e:
        return Response({
            'error': f'AI evaluation failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_evaluation_batches(request, exam_id):
    """Get evaluation batches for an exam"""
    try:
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Check permissions
        user = request.user
        if not user.can_manage_exams() or exam.institute != user.institute:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        batches = EvaluationBatch.objects.filter(exam=exam).order_by('-created_at')
        serializer = EvaluationBatchSerializer(batches, many=True)
        
        return Response(serializer.data)
        
    except Exception as e:
        return Response({
            'error': f'Failed to get evaluation batches: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def update_evaluation_settings(request, exam_id):
    """Update evaluation settings for an exam"""
    try:
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Check permissions
        user = request.user
        if not user.can_manage_exams() or exam.institute != user.institute:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        settings, created = EvaluationSettings.objects.get_or_create(exam=exam)
        
        if request.method == 'GET':
            # Return current settings
            serializer = EvaluationSettingsSerializer(settings)
            return Response({
                'success': True,
                'settings': serializer.data
            })
        else:
            # Update settings (POST)
            serializer = EvaluationSettingsSerializer(settings, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response({
                    'success': True,
                    'message': 'Evaluation settings updated successfully',
                    'settings': serializer.data
                })
            else:
                return Response({
                    'error': 'Invalid settings data',
                    'details': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
        
    except Exception as e:
        return Response({
            'error': f'Failed to update evaluation settings: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_pending_evaluations(request, exam_id):
    """Get pending evaluations for manual review"""
    try:
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Check permissions
        user = request.user
        if not user.can_manage_exams() or exam.institute != user.institute:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get pending evaluations
        pending_evaluations = QuestionEvaluation.objects.filter(
            attempt__exam=exam,
            evaluation_status='pending'
        ).order_by('question_number')
        
        serializer = QuestionEvaluationSerializer(pending_evaluations, many=True)
        
        return Response({
            'pending_count': pending_evaluations.count(),
            'evaluations': serializer.data
        })
        
    except Exception as e:
        return Response({
            'error': f'Failed to get pending evaluations: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def batch_ai_evaluate(request, exam_id):
    """Batch evaluate multiple questions using AI"""
    try:
        exam = get_object_or_404(Exam, id=exam_id)
        
        # Check permissions
        user = request.user
        if not user.can_manage_exams() or exam.institute != user.institute:
            return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if AI evaluation is enabled
        settings = EvaluationSettings.objects.get(exam=exam)
        if not settings.enable_ai_evaluation:
            return Response({
                'error': 'AI evaluation is not enabled for this exam'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get pending AI evaluations
        pending_evaluations = QuestionEvaluation.objects.filter(
            attempt__exam=exam,
            evaluation_status='pending',
            evaluation_type='ai'
        )
        
        if not pending_evaluations.exists():
            return Response({
                'message': 'No pending AI evaluations found'
            })
        
        # Create evaluation batch
        batch = EvaluationBatch.objects.create(
            exam=exam,
            batch_type='ai',
            questions_count=pending_evaluations.count(),
            status='in_progress',
            started_at=timezone.now(),
            processed_by=user
        )
        
        # Process each evaluation
        success_count = 0
        failed_count = 0
        
        for q_eval in pending_evaluations:
            try:
                attempt = q_eval.attempt
                evaluation_service = EvaluationService(attempt)
                result = evaluation_service.evaluate_with_ai(q_eval)
                
                if result['success']:
                    success_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                failed_count += 1
                q_eval.evaluation_notes = f"AI evaluation failed: {str(e)}"
                q_eval.save()
        
        # Update batch status
        batch.evaluated_count = success_count
        batch.failed_count = failed_count
        batch.status = 'completed' if failed_count == 0 else 'failed'
        batch.completed_at = timezone.now()
        batch.save()
        
        # Update evaluation progress
        progress = EvaluationProgress.objects.get(exam=exam)
        progress.ai_evaluated += success_count
        progress.pending_evaluation -= (success_count + failed_count)
        progress.save()
        
        return Response({
            'success': True,
            'message': f'Batch AI evaluation completed. Success: {success_count}, Failed: {failed_count}',
            'batch_id': batch.id,
            'success_count': success_count,
            'failed_count': failed_count
        })
        
    except Exception as e:
        return Response({
            'error': f'Batch AI evaluation failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
