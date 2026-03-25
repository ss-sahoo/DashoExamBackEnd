from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Avg, Count, Sum, Q, F, Max, Min
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import statistics

from .models import ExamAttempt, Exam, QuestionEvaluation, EvaluationProgress
from questions.models import Question
from accounts.models import User


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def student_analytics_overview(request):
    """Get comprehensive analytics overview for a student"""
    if request.user.role not in ['student', 'STUDENT']:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    user = request.user
    
    # Get all attempts for this student
    attempts = ExamAttempt.objects.filter(student=user, status__in=['submitted', 'auto_submitted'])
    
    # Basic statistics
    total_exams_attempted = attempts.count()
    total_exams_passed = attempts.filter(percentage__gte=40).count()  # 40% passing threshold
    average_score = attempts.aggregate(avg=Avg('percentage'))['avg'] or 0
    highest_score = attempts.aggregate(max=Max('percentage'))['max'] or 0
    lowest_score = attempts.aggregate(min=Min('percentage'))['min'] or 0
    
    # Performance trends
    recent_attempts = attempts.order_by('-submitted_at')[:5]
    performance_trend = []
    for attempt in recent_attempts:
        performance_trend.append({
            'exam_title': attempt.exam.title,
            'score': float(attempt.percentage or 0),
            'date': attempt.submitted_at.isoformat(),
            'exam_id': attempt.exam.id
        })
    
    # Subject-wise performance (using exam title as subject for now)
    subject_performance = {}
    for attempt in attempts:
        exam = attempt.exam
        # Use exam title as subject since ExamPattern doesn't have subject field
        subject = exam.title
        if subject not in subject_performance:
            subject_performance[subject] = {
                'total_exams': 0,
                'total_score': 0,
                'highest_score': 0,
                'lowest_score': 100
            }
        
        subject_performance[subject]['total_exams'] += 1
        subject_performance[subject]['total_score'] += float(attempt.percentage or 0)
        subject_performance[subject]['highest_score'] = max(
            subject_performance[subject]['highest_score'], 
            float(attempt.percentage or 0)
        )
        subject_performance[subject]['lowest_score'] = min(
            subject_performance[subject]['lowest_score'], 
            float(attempt.percentage or 0)
        )
    
    # Calculate averages for subjects
    for subject in subject_performance:
        data = subject_performance[subject]
        data['average_score'] = data['total_score'] / data['total_exams']
    
    # Time analysis
    time_analysis = {
        'average_time_spent': attempts.aggregate(avg=Avg('time_spent'))['avg'] or 0,
        'total_time_spent': attempts.aggregate(total=Sum('time_spent'))['total'] or 0,
        'most_efficient_exam': None,
        'least_efficient_exam': None
    }
    
    if attempts.exists():
        # Find most and least efficient exams (score per minute)
        efficiency_data = []
        for attempt in attempts:
            if attempt.time_spent > 0:
                efficiency = float(attempt.percentage or 0) / (attempt.time_spent / 60)  # score per minute
                efficiency_data.append({
                    'exam_title': attempt.exam.title,
                    'efficiency': efficiency,
                    'score': float(attempt.percentage or 0),
                    'time_spent': attempt.time_spent
                })
        
        if efficiency_data:
            efficiency_data.sort(key=lambda x: x['efficiency'], reverse=True)
            time_analysis['most_efficient_exam'] = efficiency_data[0]
            time_analysis['least_efficient_exam'] = efficiency_data[-1]
    
    # Violation analysis
    violation_stats = {
        'total_violations': attempts.aggregate(total=Sum('violations_count'))['total'] or 0,
        'exams_with_violations': attempts.filter(violations_count__gt=0).count(),
        'average_violations_per_exam': 0
    }
    
    if total_exams_attempted > 0:
        violation_stats['average_violations_per_exam'] = violation_stats['total_violations'] / total_exams_attempted
    
    # Recent activity
    recent_activity = []
    for attempt in attempts.order_by('-submitted_at')[:10]:
        recent_activity.append({
            'type': 'exam_completed',
            'exam_title': attempt.exam.title,
            'score': float(attempt.percentage or 0),
            'date': attempt.submitted_at.isoformat(),
            'exam_id': attempt.exam.id,
            'violations': attempt.violations_count
        })
    
    # Performance categories
    performance_categories = {
        'excellent': attempts.filter(percentage__gte=80).count(),
        'good': attempts.filter(percentage__gte=60, percentage__lt=80).count(),
        'average': attempts.filter(percentage__gte=40, percentage__lt=60).count(),
        'needs_improvement': attempts.filter(percentage__lt=40).count()
    }
    
    return Response({
        'overview': {
            'total_exams_attempted': total_exams_attempted,
            'total_exams_passed': total_exams_passed,
            'pass_percentage': (total_exams_passed / total_exams_attempted * 100) if total_exams_attempted > 0 else 0,
            'average_score': round(average_score, 2),
            'highest_score': round(highest_score, 2),
            'lowest_score': round(lowest_score, 2),
            'current_rank': 1,  # TODO: Implement ranking system
            'total_violations': violation_stats['total_violations']
        },
        'performance_trend': performance_trend,
        'subject_performance': subject_performance,
        'time_analysis': time_analysis,
        'violation_stats': violation_stats,
        'recent_activity': recent_activity,
        'performance_categories': performance_categories
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def student_exam_analytics(request, exam_id):
    """Get detailed analytics for a specific exam attempt"""
    if request.user.role not in ['student', 'STUDENT']:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        attempt = ExamAttempt.objects.get(id=exam_id, student=request.user)
    except ExamAttempt.DoesNotExist:
        return Response({'error': 'Exam attempt not found'}, status=status.HTTP_404_NOT_FOUND)
    
    # Get question evaluations
    question_evals = QuestionEvaluation.objects.filter(attempt=attempt)
    
    # Question-wise analysis
    question_analysis = []
    for qe in question_evals:
        question_analysis.append({
            'question_number': qe.question_number,
            'question_text': qe.question.question_text,
            'question_type': qe.question.question_type,
            'student_answer': qe.student_answer,
            'correct_answer': qe.question.correct_answer,
            'is_correct': qe.is_correct,
            'marks_obtained': float(qe.marks_obtained or 0),
            'max_marks': float(qe.max_marks),
            'evaluation_status': qe.evaluation_status,
            'time_spent': qe.time_spent or 0
        })
    
    # Performance metrics
    total_questions = question_evals.count()
    correct_answers = question_evals.filter(is_correct=True).count()
    incorrect_answers = question_evals.filter(is_correct=False).count()
    unattempted = total_questions - question_evals.filter(is_answered=True).count()
    
    # Time analysis
    total_time_spent = attempt.time_spent or 0
    average_time_per_question = total_time_spent / total_questions if total_questions > 0 else 0
    
    # Difficulty analysis
    difficulty_analysis = {
        'easy': question_evals.filter(question__difficulty_level='easy').count(),
        'medium': question_evals.filter(question__difficulty_level='medium').count(),
        'hard': question_evals.filter(question__difficulty_level='hard').count()
    }
    
    # Performance by question type
    type_performance = {}
    for qe in question_evals:
        q_type = qe.question.question_type
        if q_type not in type_performance:
            type_performance[q_type] = {
                'total': 0,
                'correct': 0,
                'incorrect': 0,
                'unattempted': 0
            }
        
        type_performance[q_type]['total'] += 1
        if qe.is_correct:
            type_performance[q_type]['correct'] += 1
        elif qe.is_answered:
            type_performance[q_type]['incorrect'] += 1
        else:
            type_performance[q_type]['unattempted'] += 1
    
    # Calculate percentages for each type
    for q_type in type_performance:
        data = type_performance[q_type]
        if data['total'] > 0:
            data['accuracy'] = (data['correct'] / data['total']) * 100
        else:
            data['accuracy'] = 0
    
    return Response({
        'exam_info': {
            'exam_title': attempt.exam.title,
            'exam_id': attempt.exam.id,
            'attempt_id': attempt.id,
            'submitted_at': attempt.submitted_at.isoformat(),
            'duration_minutes': attempt.exam.duration_minutes,
            'total_marks': float(attempt.exam.total_marks),
            'total_questions': total_questions
        },
        'performance_summary': {
            'score': float(attempt.score or 0),
            'percentage': float(attempt.percentage or 0),
            'correct_answers': correct_answers,
            'incorrect_answers': incorrect_answers,
            'unattempted': unattempted,
            'accuracy': (correct_answers / total_questions * 100) if total_questions > 0 else 0
        },
        'time_analysis': {
            'total_time_spent': total_time_spent,
            'average_time_per_question': round(average_time_per_question, 2),
            'time_efficiency': (float(attempt.percentage or 0) / (total_time_spent / 60)) if total_time_spent > 0 else 0
        },
        'question_analysis': question_analysis,
        'difficulty_analysis': difficulty_analysis,
        'type_performance': type_performance,
        'violations': {
            'total_violations': attempt.violations_count,
            'violation_details': []  # TODO: Add detailed violation information
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def student_performance_trends(request):
    """Get performance trends over time for a student"""
    if request.user.role not in ['student', 'STUDENT']:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    user = request.user
    days = int(request.GET.get('days', 30))  # Default to 30 days
    
    # Get attempts from the last N days
    start_date = timezone.now() - timedelta(days=days)
    attempts = ExamAttempt.objects.filter(
        student=user,
        status__in=['submitted', 'auto_submitted'],
        submitted_at__gte=start_date
    ).order_by('submitted_at')
    
    # Daily performance
    daily_performance = {}
    for attempt in attempts:
        date = attempt.submitted_at.date().isoformat()
        if date not in daily_performance:
            daily_performance[date] = {
                'exams_taken': 0,
                'total_score': 0,
                'scores': []
            }
        
        daily_performance[date]['exams_taken'] += 1
        daily_performance[date]['total_score'] += float(attempt.percentage or 0)
        daily_performance[date]['scores'].append(float(attempt.percentage or 0))
    
    # Calculate averages
    for date in daily_performance:
        data = daily_performance[date]
        data['average_score'] = data['total_score'] / data['exams_taken']
        data['highest_score'] = max(data['scores'])
        data['lowest_score'] = min(data['scores'])
        del data['scores']  # Remove raw scores to reduce response size
    
    # Weekly performance
    weekly_performance = {}
    for attempt in attempts:
        week_start = attempt.submitted_at.date() - timedelta(days=attempt.submitted_at.weekday())
        week_key = week_start.isoformat()
        
        if week_key not in weekly_performance:
            weekly_performance[week_key] = {
                'exams_taken': 0,
                'total_score': 0,
                'scores': []
            }
        
        weekly_performance[week_key]['exams_taken'] += 1
        weekly_performance[week_key]['total_score'] += float(attempt.percentage or 0)
        weekly_performance[week_key]['scores'].append(float(attempt.percentage or 0))
    
    # Calculate weekly averages
    for week in weekly_performance:
        data = weekly_performance[week]
        data['average_score'] = data['total_score'] / data['exams_taken']
        data['highest_score'] = max(data['scores'])
        data['lowest_score'] = min(data['scores'])
        del data['scores']
    
    # Performance statistics
    scores = [float(attempt.percentage or 0) for attempt in attempts]
    performance_stats = {
        'trend_direction': 'improving' if len(scores) > 1 and scores[-1] > scores[0] else 'declining',
        'average_score': statistics.mean(scores) if scores else 0,
        'score_std_dev': statistics.stdev(scores) if len(scores) > 1 else 0,
        'consistency_score': 100 - (statistics.stdev(scores) if len(scores) > 1 else 0),
        'total_exams': len(scores)
    }
    
    return Response({
        'daily_performance': daily_performance,
        'weekly_performance': weekly_performance,
        'performance_stats': performance_stats,
        'period_days': days
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def student_weak_areas(request):
    """Identify weak areas for a student"""
    if request.user.role not in ['student', 'STUDENT']:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    user = request.user
    
    # Get all question evaluations for this student
    question_evals = QuestionEvaluation.objects.filter(
        attempt__student=user,
        attempt__status__in=['submitted', 'auto_submitted']
    )
    
    # Analyze by subject (using exam title as subject)
    subject_analysis = {}
    for qe in question_evals:
        exam = qe.attempt.exam
        # Use exam title as subject since ExamPattern doesn't have subject field
        subject = exam.title
        if subject not in subject_analysis:
            subject_analysis[subject] = {
                'total_questions': 0,
                'correct_answers': 0,
                'incorrect_answers': 0,
                'unattempted': 0,
                'total_marks_obtained': 0,
                'total_max_marks': 0
            }
        
        subject_analysis[subject]['total_questions'] += 1
        if qe.is_correct:
            subject_analysis[subject]['correct_answers'] += 1
        elif qe.is_answered:
            subject_analysis[subject]['incorrect_answers'] += 1
        else:
            subject_analysis[subject]['unattempted'] += 1
        
        subject_analysis[subject]['total_marks_obtained'] += float(qe.marks_obtained or 0)
        subject_analysis[subject]['total_max_marks'] += float(qe.max_marks)
    
    # Calculate performance metrics for each subject
    weak_areas = []
    for subject, data in subject_analysis.items():
        if data['total_questions'] > 0:
            accuracy = (data['correct_answers'] / data['total_questions']) * 100
            score_percentage = (data['total_marks_obtained'] / data['total_max_marks']) * 100 if data['total_max_marks'] > 0 else 0
            
            weak_areas.append({
                'subject': subject,
                'accuracy': round(accuracy, 2),
                'score_percentage': round(score_percentage, 2),
                'total_questions': data['total_questions'],
                'correct_answers': data['correct_answers'],
                'incorrect_answers': data['incorrect_answers'],
                'unattempted': data['unattempted'],
                'strength_level': 'strong' if accuracy >= 70 else 'moderate' if accuracy >= 50 else 'weak'
            })
    
    # Sort by accuracy (weakest first)
    weak_areas.sort(key=lambda x: x['accuracy'])
    
    # Analyze by question type
    type_analysis = {}
    for qe in question_evals:
        q_type = qe.question.question_type
        if q_type not in type_analysis:
            type_analysis[q_type] = {
                'total_questions': 0,
                'correct_answers': 0,
                'incorrect_answers': 0,
                'unattempted': 0
            }
        
        type_analysis[q_type]['total_questions'] += 1
        if qe.is_correct:
            type_analysis[q_type]['correct_answers'] += 1
        elif qe.is_answered:
            type_analysis[q_type]['incorrect_answers'] += 1
        else:
            type_analysis[q_type]['unattempted'] += 1
    
    # Calculate performance for each question type
    type_weak_areas = []
    for q_type, data in type_analysis.items():
        if data['total_questions'] > 0:
            accuracy = (data['correct_answers'] / data['total_questions']) * 100
            type_weak_areas.append({
                'question_type': q_type,
                'accuracy': round(accuracy, 2),
                'total_questions': data['total_questions'],
                'correct_answers': data['correct_answers'],
                'incorrect_answers': data['incorrect_answers'],
                'unattempted': data['unattempted'],
                'strength_level': 'strong' if accuracy >= 70 else 'moderate' if accuracy >= 50 else 'weak'
            })
    
    # Sort by accuracy (weakest first)
    type_weak_areas.sort(key=lambda x: x['accuracy'])
    
    # Generate recommendations
    recommendations = []
    for area in weak_areas[:3]:  # Top 3 weakest areas
        if area['strength_level'] == 'weak':
            recommendations.append({
                'type': 'subject',
                'area': area['subject'],
                'current_performance': area['accuracy'],
                'recommendation': f"Focus on {area['subject']} - your accuracy is {area['accuracy']}%. Consider reviewing fundamental concepts and practicing more questions.",
                'priority': 'high'
            })
        elif area['strength_level'] == 'moderate':
            recommendations.append({
                'type': 'subject',
                'area': area['subject'],
                'current_performance': area['accuracy'],
                'recommendation': f"Improve {area['subject']} - your accuracy is {area['accuracy']}%. Practice more questions and focus on weak topics.",
                'priority': 'medium'
            })
    
    for area in type_weak_areas[:2]:  # Top 2 weakest question types
        if area['strength_level'] == 'weak':
            recommendations.append({
                'type': 'question_type',
                'area': area['question_type'],
                'current_performance': area['accuracy'],
                'recommendation': f"Practice {area['question_type']} questions - your accuracy is {area['accuracy']}%. Focus on understanding the question format and solving techniques.",
                'priority': 'high'
            })
    
    return Response({
        'subject_weak_areas': weak_areas,
        'type_weak_areas': type_weak_areas,
        'recommendations': recommendations,
        'overall_performance': {
            'total_questions_attempted': sum(data['total_questions'] for data in subject_analysis.values()),
            'overall_accuracy': round(
                sum(data['correct_answers'] for data in subject_analysis.values()) / 
                sum(data['total_questions'] for data in subject_analysis.values()) * 100, 2
            ) if sum(data['total_questions'] for data in subject_analysis.values()) > 0 else 0
        }
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def student_achievements(request):
    """Get achievements and milestones for a student"""
    if request.user.role not in ['student', 'STUDENT']:
        return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)
    
    user = request.user
    attempts = ExamAttempt.objects.filter(student=user, status__in=['submitted', 'auto_submitted'])
    
    achievements = []
    
    # Basic achievements
    total_exams = attempts.count()
    if total_exams >= 1:
        achievements.append({
            'id': 'first_exam',
            'title': 'First Steps',
            'description': 'Completed your first exam',
            'icon': '🎯',
            'unlocked_at': attempts.order_by('submitted_at').first().submitted_at.isoformat(),
            'rarity': 'common'
        })
    
    if total_exams >= 5:
        achievements.append({
            'id': 'exam_warrior',
            'title': 'Exam Warrior',
            'description': 'Completed 5 exams',
            'icon': '⚔️',
            'unlocked_at': attempts.order_by('submitted_at')[4].submitted_at.isoformat(),
            'rarity': 'uncommon'
        })
    
    if total_exams >= 10:
        achievements.append({
            'id': 'exam_master',
            'title': 'Exam Master',
            'description': 'Completed 10 exams',
            'icon': '👑',
            'unlocked_at': attempts.order_by('submitted_at')[9].submitted_at.isoformat(),
            'rarity': 'rare'
        })
    
    # Score achievements
    high_scores = attempts.filter(percentage__gte=90)
    if high_scores.exists():
        achievements.append({
            'id': 'excellent_performer',
            'title': 'Excellent Performer',
            'description': 'Scored 90% or above in an exam',
            'icon': '🌟',
            'unlocked_at': high_scores.order_by('-percentage').first().submitted_at.isoformat(),
            'rarity': 'rare'
        })
    
    perfect_scores = attempts.filter(percentage=100)
    if perfect_scores.exists():
        achievements.append({
            'id': 'perfect_score',
            'title': 'Perfect Score',
            'description': 'Achieved 100% in an exam',
            'icon': '💯',
            'unlocked_at': perfect_scores.first().submitted_at.isoformat(),
            'rarity': 'legendary'
        })
    
    # Consistency achievements
    recent_attempts = attempts.order_by('-submitted_at')[:5]
    if len(recent_attempts) >= 5:
        recent_scores = [float(attempt.percentage or 0) for attempt in recent_attempts]
        if all(score >= 70 for score in recent_scores):
            achievements.append({
                'id': 'consistent_performer',
                'title': 'Consistent Performer',
                'description': 'Scored 70% or above in last 5 exams',
                'icon': '📈',
                'unlocked_at': recent_attempts[0].submitted_at.isoformat(),
                'rarity': 'epic'
            })
    
    # Speed achievements
    fast_attempts = attempts.filter(time_spent__lte=1800)  # 30 minutes or less
    if fast_attempts.exists():
        achievements.append({
            'id': 'speed_demon',
            'title': 'Speed Demon',
            'description': 'Completed an exam in 30 minutes or less',
            'icon': '⚡',
            'unlocked_at': fast_attempts.order_by('time_spent').first().submitted_at.isoformat(),
            'rarity': 'uncommon'
        })
    
    # Clean exam achievements
    clean_attempts = attempts.filter(violations_count=0)
    if clean_attempts.exists():
        achievements.append({
            'id': 'clean_exam',
            'title': 'Clean Exam',
            'description': 'Completed an exam with zero violations',
            'icon': '✨',
            'unlocked_at': clean_attempts.first().submitted_at.isoformat(),
            'rarity': 'common'
        })
    
    # Calculate progress towards next achievements
    next_achievements = []
    
    if total_exams < 5:
        next_achievements.append({
            'id': 'exam_warrior',
            'title': 'Exam Warrior',
            'description': 'Complete 5 exams',
            'progress': total_exams,
            'target': 5,
            'icon': '⚔️'
        })
    elif total_exams < 10:
        next_achievements.append({
            'id': 'exam_master',
            'title': 'Exam Master',
            'description': 'Complete 10 exams',
            'progress': total_exams,
            'target': 10,
            'icon': '👑'
        })
    
    # Calculate total points
    points_by_rarity = {
        'common': 10,
        'uncommon': 25,
        'rare': 50,
        'epic': 100,
        'legendary': 250
    }
    
    total_points = sum(points_by_rarity.get(achievement['rarity'], 0) for achievement in achievements)
    
    return Response({
        'achievements': achievements,
        'next_achievements': next_achievements,
        'total_points': total_points,
        'total_achievements': len(achievements)
    })
