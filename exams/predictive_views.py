"""
API views for predictive analytics
"""
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
import json

from .models import Exam, ExamAttempt
from .predictive_analytics import PerformancePredictor
from .serializers import ExamSerializer
from accounts.models import User

predictor = PerformancePredictor()


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_student_performance_prediction(request, student_id, exam_id):
    """Get AI-powered performance prediction for a specific student and exam"""
    try:
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT'] and user.id != student_id:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        if user.role in ['student', 'STUDENT'] and not user.can_view_exam(exam_id):
            return Response({'error': 'Access denied to this exam'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get prediction
        prediction = predictor.predict_student_performance(student_id, exam_id)
        
        if 'error' in prediction:
            return Response({'error': prediction['error']}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(prediction)
        
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get prediction: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_exam_difficulty_prediction(request, exam_id):
    """Get AI-powered difficulty prediction for an exam"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if not user.can_manage_exams() and not exam.is_public and user not in exam.allowed_users.all():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get prediction
        prediction = predictor.predict_exam_difficulty(exam_id)
        
        if 'error' in prediction:
            return Response({'error': prediction['error']}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(prediction)
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get difficulty prediction: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_at_risk_students(request, exam_id):
    """Get list of students at risk of poor performance"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if not user.can_manage_exams():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get prediction
        prediction = predictor.predict_at_risk_students(exam_id)
        
        if 'error' in prediction:
            return Response({'error': prediction['error']}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response(prediction)
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get at-risk students: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_performance_insights(request, exam_id):
    """Get comprehensive performance insights for an exam"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if not user.can_manage_exams() and not exam.is_public and user not in exam.allowed_users.all():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get various predictions and insights
        difficulty_prediction = predictor.predict_exam_difficulty(exam_id)
        at_risk_prediction = predictor.predict_at_risk_students(exam_id)
        
        # Get historical performance data
        historical_attempts = ExamAttempt.objects.filter(
            exam=exam,
            status='submitted'
        ).select_related('student')
        
        # Calculate historical statistics
        if historical_attempts.exists():
            scores = [attempt.score or 0 for attempt in historical_attempts]
            percentages = [attempt.percentage or 0 for attempt in historical_attempts]
            
            historical_stats = {
                'total_attempts': len(historical_attempts),
                'average_score': sum(scores) / len(scores),
                'average_percentage': sum(percentages) / len(percentages),
                'highest_score': max(scores),
                'lowest_score': min(scores),
                'pass_rate': len([p for p in percentages if p >= 50]) / len(percentages) * 100
            }
        else:
            historical_stats = {
                'total_attempts': 0,
                'average_score': 0,
                'average_percentage': 0,
                'highest_score': 0,
                'lowest_score': 0,
                'pass_rate': 0
            }
        
        # Combine insights
        insights = {
            'exam_id': exam_id,
            'exam_title': exam.title,
            'difficulty_analysis': difficulty_prediction.get('difficulty_analysis', {}),
            'performance_distribution': difficulty_prediction.get('performance_distribution', {}),
            'expected_statistics': difficulty_prediction.get('expected_statistics', {}),
            'at_risk_students': at_risk_prediction.get('at_risk_students', []),
            'historical_statistics': historical_stats,
            'recommendations': {
                'exam_recommendations': difficulty_prediction.get('recommendations', []),
                'intervention_recommendations': at_risk_prediction.get('intervention_recommendations', [])
            },
            'generated_at': timezone.now().isoformat()
        }
        
        return Response(insights)
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get performance insights: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_student_analytics_dashboard(request, student_id):
    """Get comprehensive analytics dashboard for a student"""
    try:
        user = request.user
        
        # Check permissions
        if user.role in ['student', 'STUDENT'] and user.id != student_id:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        student = User.objects.get(id=student_id)
        
        # Get student's exam attempts
        attempts = ExamAttempt.objects.filter(
            student=student,
            status='submitted'
        ).select_related('exam').order_by('-submitted_at')
        
        if not attempts.exists():
            return Response({
                'student_id': student_id,
                'student_name': student.get_full_name() or student.email,
                'message': 'No exam attempts found',
                'analytics': {
                    'total_exams': 0,
                    'average_performance': 0,
                    'performance_trend': 'stable',
                    'strengths': [],
                    'weaknesses': [],
                    'recommendations': ['Start taking exams to build your performance profile']
                }
            })
        
        # Calculate analytics
        scores = [attempt.score or 0 for attempt in attempts]
        percentages = [attempt.percentage or 0 for attempt in attempts]
        
        # Performance trend
        if len(percentages) >= 3:
            recent_avg = sum(percentages[:3]) / 3
            older_avg = sum(percentages[3:]) / len(percentages[3:]) if len(percentages) > 3 else recent_avg
            if recent_avg > older_avg + 5:
                trend = 'improving'
            elif recent_avg < older_avg - 5:
                trend = 'declining'
            else:
                trend = 'stable'
        else:
            trend = 'insufficient_data'
        
        # Subject-wise performance
        subject_performance = {}
        for attempt in attempts:
            subject = attempt.exam.subject or 'General'
            if subject not in subject_performance:
                subject_performance[subject] = []
            subject_performance[subject].append(attempt.percentage or 0)
        
        # Calculate subject averages
        for subject in subject_performance:
            subject_performance[subject] = {
                'average': sum(subject_performance[subject]) / len(subject_performance[subject]),
                'count': len(subject_performance[subject]),
                'trend': 'stable'  # Simplified
            }
        
        # Identify strengths and weaknesses
        strengths = []
        weaknesses = []
        
        for subject, data in subject_performance.items():
            if data['average'] >= 80:
                strengths.append(f"Strong performance in {subject}")
            elif data['average'] < 60:
                weaknesses.append(f"Needs improvement in {subject}")
        
        # Generate recommendations
        recommendations = []
        if trend == 'declining':
            recommendations.append("Recent performance shows declining trend - consider additional study time")
        if len(weaknesses) > 0:
            recommendations.append("Focus on improving performance in identified weak subjects")
        if len(strengths) > 0:
            recommendations.append("Continue building on your strengths")
        
        analytics = {
            'student_id': student_id,
            'student_name': student.get_full_name() or student.email,
            'analytics': {
                'total_exams': len(attempts),
                'average_performance': sum(percentages) / len(percentages),
                'best_performance': max(percentages),
                'worst_performance': min(percentages),
                'performance_trend': trend,
                'subject_performance': subject_performance,
                'strengths': strengths,
                'weaknesses': weaknesses,
                'recommendations': recommendations,
                'recent_exams': [
                    {
                        'exam_id': attempt.exam.id,
                        'exam_title': attempt.exam.title,
                        'score': attempt.score,
                        'percentage': attempt.percentage,
                        'submitted_at': attempt.submitted_at.isoformat()
                    }
                    for attempt in attempts[:5]
                ]
            },
            'generated_at': timezone.now().isoformat()
        }
        
        return Response(analytics)
        
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get student analytics: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def get_performance_comparison(request, exam_id):
    """Get performance comparison across different groups or time periods"""
    try:
        exam = Exam.objects.get(id=exam_id)
        user = request.user
        
        # Check permissions
        if not user.can_manage_exams():
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
        
        # Get all attempts for this exam
        attempts = ExamAttempt.objects.filter(
            exam=exam,
            status='submitted'
        ).select_related('student')
        
        if not attempts.exists():
            return Response({
                'exam_id': exam_id,
                'message': 'No attempts found for comparison',
                'comparisons': {}
            })
        
        # Group by different criteria
        comparisons = {}
        
        # Performance by time periods
        now = timezone.now()
        recent_attempts = attempts.filter(submitted_at__gte=now - timedelta(days=30))
        older_attempts = attempts.filter(submitted_at__lt=now - timedelta(days=30))
        
        if recent_attempts.exists() and older_attempts.exists():
            recent_avg = sum(attempt.percentage or 0 for attempt in recent_attempts) / len(recent_attempts)
            older_avg = sum(attempt.percentage or 0 for attempt in older_attempts) / len(older_attempts)
            
            comparisons['time_periods'] = {
                'recent_30_days': {
                    'average_percentage': recent_avg,
                    'attempt_count': len(recent_attempts)
                },
                'older_than_30_days': {
                    'average_percentage': older_avg,
                    'attempt_count': len(older_attempts)
                },
                'trend': 'improving' if recent_avg > older_avg else 'declining'
            }
        
        # Performance distribution
        percentages = [attempt.percentage or 0 for attempt in attempts]
        comparisons['performance_distribution'] = {
            'excellent': len([p for p in percentages if p >= 90]),
            'good': len([p for p in percentages if 80 <= p < 90]),
            'average': len([p for p in percentages if 60 <= p < 80]),
            'below_average': len([p for p in percentages if 40 <= p < 60]),
            'poor': len([p for p in percentages if p < 40])
        }
        
        # Overall statistics
        comparisons['overall_statistics'] = {
            'total_attempts': len(attempts),
            'average_percentage': sum(percentages) / len(percentages),
            'highest_percentage': max(percentages),
            'lowest_percentage': min(percentages),
            'pass_rate': len([p for p in percentages if p >= 50]) / len(percentages) * 100
        }
        
        return Response({
            'exam_id': exam_id,
            'exam_title': exam.title,
            'comparisons': comparisons,
            'generated_at': timezone.now().isoformat()
        })
        
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': f'Failed to get performance comparison: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
