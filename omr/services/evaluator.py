"""
OMR Evaluation Service
Django-friendly wrapper for the OMR sheet evaluator
"""
import os
import json
import tempfile
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from django.core.files.base import ContentFile
from django.utils import timezone

from .evaluator_core import (
    evaluate_omr_sheet as evaluate_omr_core,
    extract_responses_with_details,
    extract_candidate_info,
    evaluate_responses,
)


class OMREvaluatorService:
    """
    Service class for evaluating scanned OMR sheets.
    Wraps the core evaluator functionality for Django integration.
    """
    
    def __init__(self, omr_submission):
        """
        Initialize OMR evaluator for a submission.
        
        Args:
            omr_submission: OMRSubmission model instance
        """
        self.submission = omr_submission
        self.omr_sheet = omr_submission.omr_sheet
        self.exam = self.omr_sheet.exam
    
    def _get_answer_key(self) -> Dict:
        """
        Get answer key for the exam.
        First tries to get from AnswerKey model, then builds from questions.
        """
        from ..models import AnswerKey
        
        try:
            answer_key_model = AnswerKey.objects.get(exam=self.exam)
            return answer_key_model.answers
        except AnswerKey.DoesNotExist:
            # Build answer key from exam questions
            return self._build_answer_key_from_questions()
    
    def _build_answer_key_from_questions(self) -> Dict:
        """
        Build answer key from exam question mappings.
        """
        from questions.models import ExamQuestion
        mappings = ExamQuestion.objects.filter(
            exam=self.exam
        ).select_related('question').order_by('question_number')
        
        for i, mapping in enumerate(mappings, start=1):
            q = mapping.question
            q_field = f"Q{i}"
            
            # Get correct answer based on question type
            if q.question_type in ['single', 'multiple']:
                # MCQ - correct options are stored as list
                if q.correct_answer:
                    if isinstance(q.correct_answer, list):
                        correct = q.correct_answer
                    else:
                        correct = [q.correct_answer]
                else:
                    correct = []
            elif q.question_type in ['numerical', 'integer']:
                # Numerical - correct answer is a number
                if q.correct_answer is not None:
                    correct = [str(q.correct_answer)]
                else:
                    correct = []
            else:
                correct = []
            
            answer_key[q_field] = {
                'correct': correct,
                'marks': float(mapping.marks),
                'negative': float(mapping.negative_marks),
            }
        
        return answer_key
    
    def _save_file_to_media(self, file_path: str, prefix: str) -> str:
        """
        Save a file to Django media storage and return the path.
        """
        from django.core.files.storage import default_storage
        
        filename = os.path.basename(file_path)
        media_path = f"omr_results/{prefix}_{filename}"
        
        with open(file_path, 'rb') as f:
            saved_path = default_storage.save(media_path, ContentFile(f.read()))
        
        return saved_path
    
    def evaluate(self) -> Tuple[Dict, str, str]:
        """
        Evaluate the submitted OMR sheet.
        
        Returns:
            Tuple of (evaluation_results, results_path, annotated_path)
        """
        from django.core.files.storage import default_storage
        
        # Get metadata from OMR sheet
        metadata = self.omr_sheet.metadata
        if not metadata:
            raise ValueError("OMR sheet has no metadata for evaluation")
        
        # Get answer key
        answer_key = self._get_answer_key()
        if not answer_key:
            raise ValueError("No answer key found for exam")
        
        # Get scanned files
        scanned_files = self.submission.scanned_files
        if not scanned_files:
            raise ValueError("No scanned files found in submission")
        
        # Create temp directory for processing
        output_dir = tempfile.mkdtemp(prefix='omr_eval_')
        
        # Download files from storage to temp directory for processing
        local_files = []
        for file_path in scanned_files:
            # Check if it's a local path or cloud storage path
            if os.path.exists(file_path):
                # Local path - use directly
                local_files.append(file_path)
            else:
                # Cloud storage path - download to temp file
                try:
                    file_ext = os.path.splitext(file_path)[1]
                    temp_file = tempfile.NamedTemporaryFile(suffix=file_ext, delete=False, dir=output_dir)
                    with default_storage.open(file_path, 'rb') as f:
                        temp_file.write(f.read())
                    temp_file.close()
                    local_files.append(temp_file.name)
                except Exception as e:
                    # If download fails, log and continue
                    print(f"[EVALUATOR] Failed to download {file_path}: {e}")
                    continue
        
        if not local_files:
            raise ValueError("Could not access any scanned files for evaluation")
        
        # Save metadata to temp file
        metadata_path = os.path.join(output_dir, 'metadata.json')
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f)
        
        # Output paths
        results_path = os.path.join(output_dir, 'results.json')
        annotated_path = os.path.join(output_dir, 'annotated.pdf')
        
        # Run evaluation
        results = evaluate_omr_core(
            scanned_images=local_files,
            metadata_file=metadata_path,
            answer_key=answer_key,
            output_results=results_path,
            create_annotated=True,
            annotated_pdf=annotated_path
        )
        
        # Cleanup temp metadata file
        # Cleanup temp metadata file
        # try:
        #     os.remove(metadata_path)
        # except:
        #     pass
        print(f"DEBUG: Metadata file preserved at: {metadata_path}")
        
        return results, results_path, annotated_path
    
    def evaluate_and_save(self) -> None:
        """
        Evaluate the submission and save results to the model.
        """
        try:
            self.submission.status = 'processing'
            self.submission.save(update_fields=['status'])
            
            # Run evaluation
            results, results_path, annotated_path = self.evaluate()
            
            # Save results to model
            self.submission.extracted_responses = results.get('raw_responses', {})
            self.submission.candidate_info = results.get('candidate', {})
            self.submission.evaluation_results = results.get('evaluation', {})
            
            # Save score summary
            evaluation = results.get('evaluation', {})
            self.submission.score = Decimal(str(evaluation.get('score', 0)))
            self.submission.max_score = Decimal(str(evaluation.get('max_score', 0)))
            self.submission.percentage = Decimal(str(evaluation.get('percentage', 0)))
            
            # Save annotated PDF
            if os.path.exists(annotated_path):
                with open(annotated_path, 'rb') as f:
                    filename = f"annotated_{self.exam.id}_{self.submission.id}.pdf"
                    self.submission.annotated_pdf.save(filename, ContentFile(f.read()))
                try:
                    # os.remove(annotated_path)
                    pass
                except:
                    pass
            
            # Save results JSON
            if os.path.exists(results_path):
                with open(results_path, 'rb') as f:
                    filename = f"results_{self.exam.id}_{self.submission.id}.json"
                    self.submission.results_json.save(filename, ContentFile(f.read()))
                try:
                    # 
                    pass
                except:
                    pass
            
            self.submission.status = 'evaluated'
            self.submission.evaluation_error = None
            self.submission.evaluated_at = timezone.now()
            self.submission.save()
            
            # Update exam attempt if linked
            if self.submission.attempt:
                self._update_exam_attempt()
                
        except Exception as e:
            self.submission.status = 'failed'
            self.submission.evaluation_error = str(e)
            self.submission.save(update_fields=['status', 'evaluation_error'])
            raise
    
    def _update_exam_attempt(self):
        """
        Update the linked ExamAttempt with OMR evaluation results.
        """
        attempt = self.submission.attempt
        if not attempt:
            return
        
        # Update attempt score
        attempt.score = self.submission.score
        attempt.percentage = self.submission.percentage
        
        # Store evaluation results in answers field as backup
        if not attempt.answers:
            attempt.answers = {}
        attempt.answers['omr_evaluation'] = self.submission.evaluation_results
        
        attempt.save(update_fields=['score', 'percentage', 'answers'])
        
        # Create QuestionEvaluation records if model exists
        try:
            from exams.models import QuestionEvaluation
            from questions.models import ExamQuestion
            
            details = self.submission.evaluation_results.get('details', [])
            mappings = {
                f"Q{i}": m for i, m in enumerate(
                    ExamQuestion.objects.filter(exam=self.exam).order_by('question_number'),
                    start=1
                )
            }
            
            for detail in details:
                q_field = detail.get('question')
                mapping = mappings.get(q_field)
                if not mapping:
                    continue
                
                QuestionEvaluation.objects.update_or_create(
                    attempt=attempt,
                    question=mapping.question,
                    defaults={
                        'evaluation_type': 'auto',
                        'marks_obtained': Decimal(str(detail.get('marks_awarded', 0))),
                        'is_correct': detail.get('verdict') == 'CORRECT',
                        'auto_evaluation_result': {
                            'verdict': detail.get('verdict'),
                            'student_answer': detail.get('student_answer'),
                            'correct_answer': detail.get('correct_answer'),
                            'bubble_remark': detail.get('bubble_filled_remark'),
                        },
                        'status': 'auto_evaluated',
                    }
                )
        except ImportError:
            # QuestionEvaluation model doesn't exist
            pass
