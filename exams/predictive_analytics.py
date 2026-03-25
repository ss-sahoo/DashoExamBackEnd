"""
AI-powered predictive analytics for exam performance
"""
import numpy as np
import pandas as pd
from django.db.models import Avg, Count, Q, F
from django.utils import timezone
from datetime import timedelta
from typing import Dict, List, Tuple, Optional
import json
import logging

from .models import (
    Exam, ExamAttempt, QuestionEvaluation, 
    ExamAnalytics, QuestionAnalytics
)
from questions.models import Question
from accounts.models import User

logger = logging.getLogger(__name__)


class PerformancePredictor:
    """AI-powered performance prediction system"""
    
    def __init__(self):
        self.feature_weights = {
            'historical_performance': 0.3,
            'question_difficulty': 0.25,
            'time_management': 0.2,
            'subject_mastery': 0.15,
            'recent_trends': 0.1
        }
    
    def predict_student_performance(self, student_id: int, exam_id: int) -> Dict:
        """Predict student performance for a specific exam"""
        try:
            student = User.objects.get(id=student_id)
            exam = Exam.objects.get(id=exam_id)
            
            # Get student's historical data
            historical_data = self._get_historical_performance(student_id)
            
            # Get exam characteristics
            exam_characteristics = self._get_exam_characteristics(exam_id)
            
            # Calculate prediction features
            features = self._calculate_prediction_features(
                student_id, exam_id, historical_data, exam_characteristics
            )
            
            # Generate predictions
            predictions = self._generate_predictions(features, exam_characteristics)
            
            # Add confidence scores and recommendations
            result = {
                'student_id': student_id,
                'exam_id': exam_id,
                'predictions': predictions,
                'confidence_score': self._calculate_confidence_score(features),
                'recommendations': self._generate_recommendations(features, predictions),
                'risk_factors': self._identify_risk_factors(features),
                'strengths': self._identify_strengths(features),
                'generated_at': timezone.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error predicting performance: {e}")
            return {'error': str(e)}
    
    def predict_exam_difficulty(self, exam_id: int) -> Dict:
        """Predict overall difficulty and performance distribution for an exam"""
        try:
            exam = Exam.objects.get(id=exam_id)
            
            # Get question difficulty analysis
            question_difficulty = self._analyze_question_difficulty(exam_id)
            
            # Predict performance distribution
            performance_distribution = self._predict_performance_distribution(exam_id)
            
            # Calculate expected statistics
            expected_stats = self._calculate_expected_statistics(
                question_difficulty, performance_distribution
            )
            
            result = {
                'exam_id': exam_id,
                'difficulty_analysis': question_difficulty,
                'performance_distribution': performance_distribution,
                'expected_statistics': expected_stats,
                'recommendations': self._generate_exam_recommendations(
                    question_difficulty, performance_distribution
                ),
                'generated_at': timezone.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error predicting exam difficulty: {e}")
            return {'error': str(e)}
    
    def predict_at_risk_students(self, exam_id: int) -> Dict:
        """Identify students at risk of poor performance"""
        try:
            exam = Exam.objects.get(id=exam_id)
            
            # Get all students enrolled for this exam
            enrolled_students = self._get_enrolled_students(exam_id)
            
            at_risk_students = []
            for student in enrolled_students:
                risk_assessment = self._assess_student_risk(student['id'], exam_id)
                if risk_assessment['risk_level'] in ['high', 'medium']:
                    at_risk_students.append({
                        'student_id': student['id'],
                        'student_name': student['name'],
                        'student_email': student['email'],
                        'risk_level': risk_assessment['risk_level'],
                        'risk_factors': risk_assessment['risk_factors'],
                        'recommendations': risk_assessment['recommendations'],
                        'predicted_score': risk_assessment['predicted_score']
                    })
            
            # Sort by risk level and predicted score
            at_risk_students.sort(
                key=lambda x: (
                    {'high': 0, 'medium': 1, 'low': 2}[x['risk_level']],
                    x['predicted_score']
                )
            )
            
            result = {
                'exam_id': exam_id,
                'total_enrolled': len(enrolled_students),
                'at_risk_count': len(at_risk_students),
                'at_risk_students': at_risk_students,
                'intervention_recommendations': self._generate_intervention_recommendations(
                    at_risk_students
                ),
                'generated_at': timezone.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error predicting at-risk students: {e}")
            return {'error': str(e)}
    
    def _get_historical_performance(self, student_id: int) -> Dict:
        """Get student's historical performance data"""
        attempts = ExamAttempt.objects.filter(
            student_id=student_id,
            status='submitted'
        ).select_related('exam')
        
        if not attempts.exists():
            return {'has_history': False}
        
        # Calculate performance metrics
        scores = [attempt.score or 0 for attempt in attempts]
        percentages = [attempt.percentage or 0 for attempt in attempts]
        
        # Subject-wise performance
        subject_performance = {}
        for attempt in attempts:
            subject = attempt.exam.subject or 'General'
            if subject not in subject_performance:
                subject_performance[subject] = []
            subject_performance[subject].append(attempt.percentage or 0)
        
        # Calculate averages
        for subject in subject_performance:
            subject_performance[subject] = {
                'average': np.mean(subject_performance[subject]),
                'count': len(subject_performance[subject]),
                'trend': self._calculate_trend(subject_performance[subject])
            }
        
        return {
            'has_history': True,
            'total_attempts': len(attempts),
            'average_score': np.mean(scores),
            'average_percentage': np.mean(percentages),
            'best_performance': max(percentages),
            'worst_performance': min(percentages),
            'performance_consistency': 1 - np.std(percentages) / (np.mean(percentages) + 1e-6),
            'subject_performance': subject_performance,
            'recent_trend': self._calculate_recent_trend(attempts)
        }
    
    def _get_exam_characteristics(self, exam_id: int) -> Dict:
        """Get characteristics of the exam"""
        exam = Exam.objects.get(id=exam_id)
        
        # Get question difficulty distribution
        questions = Question.objects.filter(exam=exam)
        difficulties = [q.difficulty for q in questions]
        
        difficulty_distribution = {
            'easy': difficulties.count('easy'),
            'medium': difficulties.count('medium'),
            'hard': difficulties.count('hard')
        }
        
        # Calculate average difficulty score
        difficulty_scores = {'easy': 1, 'medium': 2, 'hard': 3}
        avg_difficulty = np.mean([
            difficulty_scores.get(d, 2) for d in difficulties
        ]) if difficulties else 2
        
        return {
            'total_questions': exam.total_questions,
            'duration_minutes': exam.duration_minutes,
            'total_marks': exam.total_marks,
            'subject': exam.subject,
            'difficulty_distribution': difficulty_distribution,
            'average_difficulty': avg_difficulty,
            'question_types': list(set([q.question_type for q in questions])),
            'time_per_question': exam.duration_minutes / exam.total_questions if exam.total_questions > 0 else 0
        }
    
    def _calculate_prediction_features(self, student_id: int, exam_id: int, 
                                     historical_data: Dict, exam_characteristics: Dict) -> Dict:
        """Calculate features for prediction"""
        features = {}
        
        # Historical performance feature
        if historical_data['has_history']:
            features['historical_performance'] = historical_data['average_percentage'] / 100
            features['performance_consistency'] = historical_data['performance_consistency']
            features['recent_trend'] = historical_data['recent_trend']
        else:
            features['historical_performance'] = 0.5  # Default for new students
            features['performance_consistency'] = 0.5
            features['recent_trend'] = 0
        
        # Question difficulty feature
        features['question_difficulty'] = 1 - (exam_characteristics['average_difficulty'] - 1) / 2
        
        # Time management feature
        if historical_data['has_history']:
            # Calculate average time per question from historical data
            attempts = ExamAttempt.objects.filter(
                student_id=student_id,
                status='submitted'
            ).select_related('exam')
            
            time_per_question_avg = np.mean([
                attempt.time_spent / (attempt.exam.total_questions * 60) 
                for attempt in attempts 
                if attempt.time_spent and attempt.exam.total_questions > 0
            ]) if attempts.exists() else 1
            
            features['time_management'] = min(1, exam_characteristics['time_per_question'] / time_per_question_avg)
        else:
            features['time_management'] = 0.5
        
        # Subject mastery feature
        if historical_data['has_history']:
            exam_subject = exam_characteristics['subject'] or 'General'
            if exam_subject in historical_data['subject_performance']:
                features['subject_mastery'] = historical_data['subject_performance'][exam_subject]['average'] / 100
            else:
                features['subject_mastery'] = historical_data['average_percentage'] / 100
        else:
            features['subject_mastery'] = 0.5
        
        # Recent trends feature
        features['recent_trends'] = historical_data.get('recent_trend', 0)
        
        return features
    
    def _generate_predictions(self, features: Dict, exam_characteristics: Dict) -> Dict:
        """Generate performance predictions based on features"""
        # Weighted prediction score
        prediction_score = sum(
            features[feature] * weight 
            for feature, weight in self.feature_weights.items()
        )
        
        # Convert to percentage
        predicted_percentage = min(100, max(0, prediction_score * 100))
        predicted_score = (predicted_percentage / 100) * exam_characteristics['total_marks']
        
        # Calculate grade
        grade = self._calculate_grade(predicted_percentage)
        
        # Calculate confidence intervals
        confidence_interval = self._calculate_confidence_interval(features)
        
        return {
            'predicted_percentage': round(predicted_percentage, 2),
            'predicted_score': round(predicted_score, 2),
            'predicted_grade': grade,
            'confidence_interval': confidence_interval,
            'probability_of_passing': self._calculate_passing_probability(predicted_percentage),
            'expected_rank': self._predict_rank(predicted_percentage, exam_characteristics)
        }
    
    def _calculate_confidence_score(self, features: Dict) -> float:
        """Calculate confidence score for the prediction"""
        # Higher confidence with more historical data and consistent performance
        consistency_factor = features.get('performance_consistency', 0.5)
        historical_factor = 1 if features.get('historical_performance', 0) > 0 else 0.5
        
        confidence = (consistency_factor * 0.6 + historical_factor * 0.4)
        return min(1, max(0, confidence))
    
    def _generate_recommendations(self, features: Dict, predictions: Dict) -> List[str]:
        """Generate personalized recommendations"""
        recommendations = []
        
        # Time management recommendations
        if features.get('time_management', 0.5) < 0.6:
            recommendations.append("Focus on improving time management skills through practice tests")
        
        # Subject mastery recommendations
        if features.get('subject_mastery', 0.5) < 0.7:
            recommendations.append("Review and strengthen understanding of core concepts")
        
        # Performance consistency recommendations
        if features.get('performance_consistency', 0.5) < 0.6:
            recommendations.append("Work on maintaining consistent performance through regular practice")
        
        # Recent trend recommendations
        if features.get('recent_trends', 0) < -0.1:
            recommendations.append("Recent performance shows declining trend - consider additional study time")
        
        # General recommendations based on predicted performance
        if predictions['predicted_percentage'] < 60:
            recommendations.append("Consider seeking additional help or tutoring")
        elif predictions['predicted_percentage'] > 85:
            recommendations.append("Maintain current study habits - you're on track for excellent performance")
        
        return recommendations
    
    def _identify_risk_factors(self, features: Dict) -> List[str]:
        """Identify risk factors for poor performance"""
        risk_factors = []
        
        if features.get('historical_performance', 0.5) < 0.4:
            risk_factors.append("Low historical performance")
        
        if features.get('performance_consistency', 0.5) < 0.4:
            risk_factors.append("Inconsistent performance")
        
        if features.get('time_management', 0.5) < 0.4:
            risk_factors.append("Poor time management")
        
        if features.get('subject_mastery', 0.5) < 0.4:
            risk_factors.append("Weak subject mastery")
        
        if features.get('recent_trends', 0) < -0.2:
            risk_factors.append("Declining performance trend")
        
        return risk_factors
    
    def _identify_strengths(self, features: Dict) -> List[str]:
        """Identify student strengths"""
        strengths = []
        
        if features.get('historical_performance', 0.5) > 0.7:
            strengths.append("Strong historical performance")
        
        if features.get('performance_consistency', 0.5) > 0.7:
            strengths.append("Consistent performance")
        
        if features.get('time_management', 0.5) > 0.7:
            strengths.append("Good time management")
        
        if features.get('subject_mastery', 0.5) > 0.7:
            strengths.append("Strong subject mastery")
        
        if features.get('recent_trends', 0) > 0.1:
            strengths.append("Improving performance trend")
        
        return strengths
    
    def _calculate_grade(self, percentage: float) -> str:
        """Calculate grade based on percentage"""
        if percentage >= 90:
            return 'A+'
        elif percentage >= 80:
            return 'A'
        elif percentage >= 70:
            return 'B+'
        elif percentage >= 60:
            return 'B'
        elif percentage >= 50:
            return 'C+'
        elif percentage >= 40:
            return 'C'
        else:
            return 'F'
    
    def _calculate_confidence_interval(self, features: Dict) -> Dict:
        """Calculate confidence interval for prediction"""
        # Base uncertainty on consistency and historical data
        base_uncertainty = 0.1
        consistency_factor = 1 - features.get('performance_consistency', 0.5)
        historical_factor = 0.5 if features.get('historical_performance', 0) == 0 else 0.1
        
        uncertainty = base_uncertainty + (consistency_factor * 0.05) + historical_factor
        
        return {
            'lower_bound': max(0, -uncertainty * 100),
            'upper_bound': min(100, uncertainty * 100)
        }
    
    def _calculate_passing_probability(self, predicted_percentage: float) -> float:
        """Calculate probability of passing (>= 50%)"""
        # Use sigmoid function to convert percentage to probability
        import math
        x = (predicted_percentage - 50) / 10  # Scale around 50%
        probability = 1 / (1 + math.exp(-x))
        return round(probability, 3)
    
    def _predict_rank(self, predicted_percentage: float, exam_characteristics: Dict) -> int:
        """Predict expected rank in the class"""
        # This is a simplified prediction - in reality, you'd need more data
        # about other students' expected performance
        if predicted_percentage >= 90:
            return 1
        elif predicted_percentage >= 80:
            return 2
        elif predicted_percentage >= 70:
            return 3
        elif predicted_percentage >= 60:
            return 4
        else:
            return 5
    
    def _calculate_trend(self, values: List[float]) -> float:
        """Calculate trend in a series of values"""
        if len(values) < 2:
            return 0
        
        # Simple linear trend calculation
        x = np.arange(len(values))
        y = np.array(values)
        
        # Calculate slope
        slope = np.polyfit(x, y, 1)[0]
        return slope / np.mean(y) if np.mean(y) != 0 else 0
    
    def _calculate_recent_trend(self, attempts) -> float:
        """Calculate recent performance trend"""
        if len(attempts) < 2:
            return 0
        
        # Get last 5 attempts
        recent_attempts = attempts.order_by('-submitted_at')[:5]
        percentages = [attempt.percentage or 0 for attempt in recent_attempts]
        
        return self._calculate_trend(percentages)
    
    def _analyze_question_difficulty(self, exam_id: int) -> Dict:
        """Analyze question difficulty for the exam"""
        questions = Question.objects.filter(exam_id=exam_id)
        
        difficulty_analysis = {
            'easy_questions': questions.filter(difficulty='easy').count(),
            'medium_questions': questions.filter(difficulty='medium').count(),
            'hard_questions': questions.filter(difficulty='hard').count(),
            'average_difficulty_score': 0,
            'difficulty_distribution': {}
        }
        
        if questions.exists():
            difficulty_scores = {'easy': 1, 'medium': 2, 'hard': 3}
            scores = [difficulty_scores.get(q.difficulty, 2) for q in questions]
            difficulty_analysis['average_difficulty_score'] = np.mean(scores)
            
            # Calculate distribution
            total = len(questions)
            difficulty_analysis['difficulty_distribution'] = {
                'easy': (difficulty_analysis['easy_questions'] / total) * 100,
                'medium': (difficulty_analysis['medium_questions'] / total) * 100,
                'hard': (difficulty_analysis['hard_questions'] / total) * 100
            }
        
        return difficulty_analysis
    
    def _predict_performance_distribution(self, exam_id: int) -> Dict:
        """Predict performance distribution for the exam"""
        # This is a simplified prediction - in reality, you'd use more sophisticated models
        return {
            'excellent': 15,  # 90%+
            'good': 25,       # 80-89%
            'average': 35,    # 60-79%
            'below_average': 20,  # 40-59%
            'poor': 5         # <40%
        }
    
    def _calculate_expected_statistics(self, question_difficulty: Dict, 
                                     performance_distribution: Dict) -> Dict:
        """Calculate expected statistics for the exam"""
        return {
            'expected_average': 65,  # Simplified calculation
            'expected_median': 68,
            'expected_standard_deviation': 15,
            'expected_pass_rate': 75,
            'expected_fail_rate': 25
        }
    
    def _generate_exam_recommendations(self, question_difficulty: Dict, 
                                     performance_distribution: Dict) -> List[str]:
        """Generate recommendations for the exam"""
        recommendations = []
        
        if question_difficulty['average_difficulty_score'] > 2.5:
            recommendations.append("Consider adding more easy questions to improve pass rate")
        
        if performance_distribution['poor'] > 10:
            recommendations.append("High failure rate expected - consider additional support")
        
        if question_difficulty['hard_questions'] > question_difficulty['easy_questions']:
            recommendations.append("Exam is heavily weighted towards difficult questions")
        
        return recommendations
    
    def _get_enrolled_students(self, exam_id: int) -> List[Dict]:
        """Get students enrolled for the exam"""
        # This would typically come from ExamInvitation or similar
        # For now, return a placeholder
        return []
    
    def _assess_student_risk(self, student_id: int, exam_id: int) -> Dict:
        """Assess risk level for a specific student"""
        # Get prediction for this student
        prediction = self.predict_student_performance(student_id, exam_id)
        
        if 'error' in prediction:
            return {'risk_level': 'unknown', 'risk_factors': [], 'recommendations': []}
        
        predicted_percentage = prediction['predictions']['predicted_percentage']
        
        # Determine risk level
        if predicted_percentage < 40:
            risk_level = 'high'
        elif predicted_percentage < 60:
            risk_level = 'medium'
        else:
            risk_level = 'low'
        
        return {
            'risk_level': risk_level,
            'risk_factors': prediction.get('risk_factors', []),
            'recommendations': prediction.get('recommendations', []),
            'predicted_score': predicted_percentage
        }
    
    def _generate_intervention_recommendations(self, at_risk_students: List[Dict]) -> List[str]:
        """Generate intervention recommendations for at-risk students"""
        recommendations = []
        
        high_risk_count = len([s for s in at_risk_students if s['risk_level'] == 'high'])
        medium_risk_count = len([s for s in at_risk_students if s['risk_level'] == 'medium'])
        
        if high_risk_count > 0:
            recommendations.append(f"Consider additional tutoring for {high_risk_count} high-risk students")
        
        if medium_risk_count > 0:
            recommendations.append(f"Provide extra study materials for {medium_risk_count} medium-risk students")
        
        if len(at_risk_students) > len(at_risk_students) * 0.3:
            recommendations.append("Consider reviewing exam difficulty or providing additional support")
        
        return recommendations
