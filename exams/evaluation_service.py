import json
import re
from decimal import Decimal
from typing import Dict, List, Tuple, Optional
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from .models import ExamAttempt, QuestionEvaluation, EvaluationBatch, EvaluationSettings, EvaluationProgress
from questions.models import Question


class EvaluationService:
    """Service class for handling different types of question evaluation"""
    
    def __init__(self, exam_attempt: ExamAttempt):
        self.attempt = exam_attempt
        self.exam = exam_attempt.exam
        self.settings = self._get_evaluation_settings()
    
    def _get_evaluation_settings(self) -> EvaluationSettings:
        """Get or create evaluation settings for the exam"""
        settings, created = EvaluationSettings.objects.get_or_create(
            exam=self.exam,
            defaults={
                'enable_auto_evaluation': True,
                'enable_manual_evaluation': True,
                'enable_ai_evaluation': False,
            }
        )
        return settings
    
    def evaluate_attempt(self, answers: Dict[str, str]) -> Dict:
        """Main method to evaluate an exam attempt"""
        with transaction.atomic():
            # Create evaluation progress if it doesn't exist
            progress, _ = EvaluationProgress.objects.get_or_create(exam=self.exam)
            
            # Get all questions for this exam
            questions = self._get_exam_questions()
            progress.total_questions = len(questions)
            progress.save()
            
            # If answers is empty, try to get from ExamResult
            if not answers:
                try:
                    from .models import ExamResult
                    result = ExamResult.objects.get(attempt=self.attempt)
                    # Extract answers from ExamResult format
                    answers = {}
                    
                    # Create mapping from question ID to question number
                    id_to_number = {}
                    for i, question in enumerate(questions, 1):
                        id_to_number[question.id] = i
                    
                    for q_id, answer_data in result.answers.items():
                        if isinstance(answer_data, dict) and 'answer' in answer_data:
                            question_number = id_to_number.get(int(q_id))
                            if question_number:
                                answers[str(question_number)] = answer_data['answer']
                        else:
                            question_number = id_to_number.get(int(q_id))
                            if question_number:
                                answers[str(question_number)] = str(answer_data)
                except:
                    pass
            
            # Process each question
            evaluation_results = []
            auto_evaluated_count = 0
            manual_evaluation_required = []
            ai_evaluation_required = []
            
            for question in questions:
                question_number = self._get_question_number(question)
                
                # Try to get answer by question ID first, then by question number
                answer_data = answers.get(str(question.id)) or answers.get(str(question_number))
                
                # Extract actual answer from the data
                if isinstance(answer_data, dict) and 'answer' in answer_data:
                    student_answer = str(answer_data['answer'])
                elif answer_data:
                    student_answer = str(answer_data)
                else:
                    student_answer = ''
                
                # Create question evaluation record
                q_eval, created = QuestionEvaluation.objects.get_or_create(
                    attempt=self.attempt,
                    question=question,
                    defaults={
                        'question_number': question_number,
                        'student_answer': student_answer,
                        'is_answered': bool(student_answer.strip()),
                        'max_marks': Decimal(str(question.marks)),
                    }
                )
                
                if not created:
                    q_eval.student_answer = student_answer
                    q_eval.is_answered = bool(student_answer.strip())
                    q_eval.save()
                
                # Determine evaluation type and process
                eval_type = self._determine_evaluation_type(question)
                q_eval.evaluation_type = eval_type
                
                if eval_type == 'auto':
                    result = self._auto_evaluate_question(q_eval, question, student_answer)
                    auto_evaluated_count += 1
                elif eval_type == 'manual':
                    q_eval.evaluation_status = 'pending'
                    manual_evaluation_required.append(q_eval)
                elif eval_type == 'ai':
                    q_eval.evaluation_status = 'pending'
                    ai_evaluation_required.append(q_eval)
                
                q_eval.save()
                evaluation_results.append(result if eval_type == 'auto' else None)
            
            # Update progress
            progress.auto_evaluated = auto_evaluated_count
            progress.pending_evaluation = len(manual_evaluation_required) + len(ai_evaluation_required)
            progress.save()
            
            # Create evaluation batches if needed
            if manual_evaluation_required and self.settings.enable_manual_evaluation:
                self._create_evaluation_batch('manual', manual_evaluation_required)
            
            if ai_evaluation_required and self.settings.enable_ai_evaluation:
                self._create_evaluation_batch('ai', ai_evaluation_required)
            
            # Calculate final score
            final_score = self._calculate_final_score()
            
            return {
                'evaluation_results': evaluation_results,
                'auto_evaluated': auto_evaluated_count,
                'manual_required': len(manual_evaluation_required),
                'ai_required': len(ai_evaluation_required),
                'final_score': final_score,
                'evaluation_progress': progress.completion_percentage
            }
    
    def _get_exam_questions(self) -> List[Question]:
        """Get all questions for the exam honoring pattern sections with safe fallbacks"""
        collected: List[Question] = []
        seen_ids = set()

        def add_questions(queryset):
            for question in queryset:
                if question.id not in seen_ids:
                    collected.append(question)
                    seen_ids.add(question.id)

        pattern = getattr(self.exam, 'pattern', None)
        if pattern and hasattr(pattern, 'sections'):
            for section in pattern.sections.all().order_by('start_question'):
                before_count = len(collected)

                add_questions(
                    Question.objects.filter(
                        pattern_section_id=section.id
                    ).order_by('question_number_in_pattern', 'question_number', 'id')
                )

                if len(collected) == before_count and section.name:
                    add_questions(
                        Question.objects.filter(
                            exam=self.exam,
                            pattern_section_name=section.name
                        ).order_by('question_number_in_pattern', 'question_number', 'id')
                    )

                if len(collected) == before_count:
                    add_questions(
                        Question.objects.filter(
                            exam=self.exam,
                            subject__iexact=section.subject,
                            question_number__gte=section.start_question,
                            question_number__lte=section.end_question
                        ).order_by('question_number', 'id')
                    )

        if not collected:
            add_questions(
                Question.objects.filter(exam=self.exam).order_by('question_number_in_pattern', 'question_number', 'id')
            )

        return collected
    
    def _get_question_number(self, question: Question) -> int:
        """Get the question number within the exam"""
        return question.question_number_in_pattern or 1
    
    def _determine_evaluation_type(self, question: Question) -> str:
        """Determine the evaluation type for a question"""
        question_type = question.question_type
        
        # Auto-evaluation for objective questions
        if question_type in ['single_mcq', 'multiple_mcq', 'true_false', 'numerical', 'fill_blank']:
            if self.settings.enable_auto_evaluation:
                return 'auto'
        
        # Manual evaluation for subjective questions
        if question_type == 'subjective':
            if self.settings.enable_ai_evaluation and self.settings.ai_fallback_to_manual:
                return 'ai'  # Try AI first, fallback to manual
            elif self.settings.enable_manual_evaluation:
                return 'manual'
        
        # Default to manual if nothing else is configured
        return 'manual'
    
    def _auto_evaluate_question(self, q_eval: QuestionEvaluation, question: Question, student_answer: str) -> Dict:
        """Auto-evaluate objective questions"""
        try:
            if question.question_type == 'single_mcq':
                result = self._evaluate_single_mcq(question, student_answer)
            elif question.question_type == 'multiple_mcq':
                result = self._evaluate_multiple_mcq(question, student_answer)
            elif question.question_type == 'true_false':
                result = self._evaluate_true_false(question, student_answer)
            elif question.question_type == 'numerical':
                result = self._evaluate_numerical(question, student_answer)
            elif question.question_type == 'fill_blank':
                result = self._evaluate_fill_blank(question, student_answer)
            else:
                result = {'is_correct': False, 'marks_obtained': 0, 'feedback': 'Unsupported question type for auto-evaluation'}
            
            # Update question evaluation
            q_eval.marks_obtained = Decimal(str(result['marks_obtained']))
            q_eval.is_correct = result['is_correct']
            q_eval.evaluation_status = 'auto_evaluated'
            q_eval.evaluated_at = timezone.now()
            q_eval.evaluation_notes = result.get('feedback', '')
            q_eval.save()
            
            return result
            
        except Exception as e:
            # Mark as failed and require manual evaluation
            q_eval.evaluation_status = 'pending'
            q_eval.evaluation_notes = f"Auto-evaluation failed: {str(e)}"
            q_eval.save()
            
            return {
                'is_correct': False,
                'marks_obtained': 0,
                'feedback': f"Auto-evaluation failed: {str(e)}",
                'error': True
            }
    
    def _evaluate_single_mcq(self, question: Question, student_answer: str) -> Dict:
        """Evaluate single correct MCQ"""
        correct_answer = question.correct_answer.strip().lower()
        student_answer = student_answer.strip().lower()
        
        is_correct = correct_answer == student_answer
        marks_obtained = float(question.marks) if is_correct else 0
        
        return {
            'is_correct': is_correct,
            'marks_obtained': marks_obtained,
            'feedback': 'Correct!' if is_correct else f'Incorrect. Correct answer: {question.correct_answer}'
        }
    
    def _evaluate_multiple_mcq(self, question: Question, student_answer: str) -> Dict:
        """Evaluate multiple correct MCQ"""
        try:
            # Handle pipe-separated format: "option1|option2|option3"
            if isinstance(student_answer, str) and '|' in student_answer:
                student_answers = [ans.strip() for ans in student_answer.split('|') if ans.strip()]
            elif isinstance(student_answer, str):
                try:
                    # Try JSON format as fallback
                    student_answers = json.loads(student_answer)
                except:
                    student_answers = [student_answer]
            else:
                student_answers = [student_answer]
            
            # Handle correct answer format
            if isinstance(question.correct_answer, str) and '|' in question.correct_answer:
                correct_answers = [ans.strip() for ans in question.correct_answer.split('|') if ans.strip()]
            elif isinstance(question.correct_answer, str):
                try:
                    correct_answers = json.loads(question.correct_answer)
                except:
                    correct_answers = [question.correct_answer]
            else:
                correct_answers = question.correct_answer
            
            # Convert to sets for comparison (case-insensitive)
            correct_set = set(str(ans).strip().lower() for ans in correct_answers)
            student_set = set(str(ans).strip().lower() for ans in student_answers)
            
            is_correct = correct_set == student_set
            marks_obtained = float(question.marks) if is_correct else 0
            
            return {
                'is_correct': is_correct,
                'marks_obtained': marks_obtained,
                'feedback': 'Correct!' if is_correct else f'Incorrect. Correct answers: {", ".join(correct_answers)}'
            }
        except Exception as e:
            return {
                'is_correct': False,
                'marks_obtained': 0,
                'feedback': f'Error parsing answers: {str(e)}'
            }
    
    def _evaluate_true_false(self, question: Question, student_answer: str) -> Dict:
        """Evaluate True/False questions"""
        correct_answer = question.correct_answer.strip().lower()
        student_answer = student_answer.strip().lower()
        
        # Normalize answers
        correct_bool = correct_answer in ['true', 't', 'yes', 'y', '1']
        student_bool = student_answer in ['true', 't', 'yes', 'y', '1']
        
        is_correct = correct_bool == student_bool
        marks_obtained = float(question.marks) if is_correct else 0
        
        return {
            'is_correct': is_correct,
            'marks_obtained': marks_obtained,
            'feedback': 'Correct!' if is_correct else f'Incorrect. Correct answer: {question.correct_answer}'
        }
    
    def _evaluate_numerical(self, question: Question, student_answer: str) -> Dict:
        """Evaluate numerical questions with tolerance"""
        try:
            correct_value = float(question.correct_answer)
            student_value = float(student_answer)
            
            # Default tolerance of 1% or 0.01, whichever is larger
            tolerance = max(abs(correct_value) * 0.01, 0.01)
            
            is_correct = abs(correct_value - student_value) <= tolerance
            marks_obtained = float(question.marks) if is_correct else 0
            
            return {
                'is_correct': is_correct,
                'marks_obtained': marks_obtained,
                'feedback': 'Correct!' if is_correct else f'Incorrect. Correct answer: {correct_value} (±{tolerance})'
            }
        except (ValueError, TypeError):
            return {
                'is_correct': False,
                'marks_obtained': 0,
                'feedback': 'Invalid numerical answer'
            }
    
    def _evaluate_fill_blank(self, question: Question, student_answer: str) -> Dict:
        """Evaluate fill-in-the-blank questions"""
        correct_answer = question.correct_answer.strip().lower()
        student_answer = student_answer.strip().lower()
        
        # Simple string matching (can be enhanced with fuzzy matching)
        is_correct = correct_answer == student_answer
        marks_obtained = float(question.marks) if is_correct else 0
        
        return {
            'is_correct': is_correct,
            'marks_obtained': marks_obtained,
            'feedback': 'Correct!' if is_correct else f'Incorrect. Correct answer: {question.correct_answer}'
        }
    
    def _create_evaluation_batch(self, batch_type: str, question_evaluations: List[QuestionEvaluation]) -> EvaluationBatch:
        """Create an evaluation batch for manual or AI evaluation"""
        batch = EvaluationBatch.objects.create(
            exam=self.exam,
            batch_type=batch_type,
            questions_count=len(question_evaluations),
            status='pending'
        )
        return batch
    
    def _calculate_final_score(self) -> float:
        """Calculate final score for the attempt"""
        total_marks = 0
        obtained_marks = 0
        
        for q_eval in QuestionEvaluation.objects.filter(attempt=self.attempt):
            total_marks += float(q_eval.max_marks)
            obtained_marks += float(q_eval.marks_obtained)
        
        return obtained_marks if total_marks > 0 else 0
    
    def evaluate_with_ai(self, question_evaluation: QuestionEvaluation) -> Dict:
        """Evaluate subjective questions using AI"""
        # This is a placeholder for AI evaluation
        # In a real implementation, you would integrate with OpenAI, Claude, or other AI services
        
        try:
            # Placeholder AI evaluation logic
            # In practice, you would send the question and student answer to an AI service
            
            # For now, return a mock evaluation
            ai_confidence = 0.85  # Mock confidence score
            ai_feedback = "AI evaluation completed. Please review for accuracy."
            
            # Simple scoring based on answer length and keywords (placeholder logic)
            answer_length = len(question_evaluation.student_answer)
            max_marks = float(question_evaluation.max_marks)
            
            # Basic scoring logic (replace with actual AI evaluation)
            if answer_length > 50:
                marks_obtained = max_marks * 0.8
            elif answer_length > 20:
                marks_obtained = max_marks * 0.6
            else:
                marks_obtained = max_marks * 0.3
            
            # Update question evaluation
            question_evaluation.marks_obtained = Decimal(str(marks_obtained))
            question_evaluation.is_correct = marks_obtained > (max_marks * 0.5)
            question_evaluation.evaluation_status = 'ai_evaluated'
            question_evaluation.evaluated_at = timezone.now()
            question_evaluation.ai_confidence_score = Decimal(str(ai_confidence))
            question_evaluation.ai_feedback = ai_feedback
            question_evaluation.save()
            
            return {
                'success': True,
                'marks_obtained': marks_obtained,
                'confidence': ai_confidence,
                'feedback': ai_feedback
            }
            
        except Exception as e:
            # Fallback to manual evaluation if AI fails
            question_evaluation.evaluation_status = 'pending'
            question_evaluation.evaluation_notes = f"AI evaluation failed: {str(e)}"
            question_evaluation.save()
            
            return {
                'success': False,
                'error': str(e),
                'fallback_to_manual': True
            }
    
    def get_evaluation_summary(self) -> Dict:
        """Get summary of evaluation progress"""
        progress = EvaluationProgress.objects.get(exam=self.exam)
        question_evaluations = QuestionEvaluation.objects.filter(attempt=self.attempt)
        
        return {
            'total_questions': progress.total_questions,
            'auto_evaluated': progress.auto_evaluated,
            'manually_evaluated': progress.manually_evaluated,
            'ai_evaluated': progress.ai_evaluated,
            'pending_evaluation': progress.pending_evaluation,
            'completion_percentage': progress.completion_percentage,
            'is_fully_evaluated': progress.is_fully_evaluated,
            'question_details': [
                {
                    'question_number': qe.question_number,
                    'question_type': qe.question.question_type,
                    'evaluation_status': qe.evaluation_status,
                    'marks_obtained': float(qe.marks_obtained),
                    'max_marks': float(qe.max_marks),
                    'is_correct': qe.is_correct
                }
                for qe in question_evaluations
            ]
        }
