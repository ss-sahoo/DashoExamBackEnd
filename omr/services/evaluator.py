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
    
    def __init__(self, omr_submission=None):
        """
        Initialize OMR evaluator for a submission.
        
        Args:
            omr_submission: OMRSubmission model instance (optional)
        """
        self.submission = omr_submission
        if omr_submission:
            self.omr_sheet = omr_submission.omr_sheet
            self.exam = self.omr_sheet.exam
        else:
            self.omr_sheet = None
            self.exam = None

    
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
        Build answer key from exam question mappings or pattern sections, 
        matching OMR sequential numbering.
        """
        from questions.models import ExamQuestion, Question
        from patterns.models import PatternSection
        
        answer_key = {}
        global_idx = 1
        
        mappings = ExamQuestion.objects.filter(
            exam=self.exam
        ).select_related('question').order_by('question_number')
        
        direct_questions = Question.objects.filter(exam=self.exam).order_by('question_number', 'id')
        
        if mappings.exists():
            # First, group by the determined section name (matching OMRGeneratorService logic)
            raw_questions = []
            for mapping in mappings:
                q = mapping.question
                subject_name = q.subject or 'General'
                section_name = mapping.section_name
                
                if section_name and section_name.lower() != subject_name.lower():
                    if len(section_name) <= 2:
                        display_name = f"{subject_name} - Section {section_name}"
                    else:
                        display_name = f"{subject_name} - {section_name}"
                else:
                    display_name = subject_name
                    
                raw_questions.append({
                    'mapping': mapping,
                    'question': q,
                    'section': display_name,
                    'original_number': mapping.question_number,
                    'marks': mapping.marks,
                    'negative': mapping.negative_marks,
                    'mapping_id': mapping.id
                })
                
            # Re-sort to match OMR generator's sequential flow (original number first)
            raw_questions.sort(key=lambda x: (x['original_number'], x['section']))
            
            for data in raw_questions:
                q = data['question']
                q_field = f"Q{global_idx}"
                
                if q.question_type in ['single_mcq', 'single', 'multiple_mcq', 'multiple', 'true_false']:
                    # Handle comma-separated letters if stored that way (e.g. "A,B")
                    if isinstance(q.correct_answer, str) and ',' in q.correct_answer and all(len(x.strip()) == 1 for x in q.correct_answer.split(',')):
                        correct = [x.strip().upper() for x in q.correct_answer.split(',')]
                    elif isinstance(q.correct_answer, str) and len(q.correct_answer.strip()) == 1 and q.correct_answer.strip().upper() in ['A', 'B', 'C', 'D']:
                        correct = [q.correct_answer.strip().upper()]
                    else:
                        # Otherwise, try to find the index of the answer text in options
                        correct = []
                        q_options = q.options if isinstance(q.options, list) else []
                        
                        # Match by value
                        ans_text = str(q.correct_answer).strip().lower()
                        for idx, opt in enumerate(q_options):
                            if str(opt).strip().lower() == ans_text and idx < 26:
                                correct.append(chr(65 + idx))
                                
                        # Fallback: if correct_answer IS an index (e.g. "0", "1")
                        if not correct and ans_text.isdigit():
                            idx = int(ans_text)
                            if 0 <= idx < len(q_options):
                                correct.append(chr(65 + idx))
                elif q.question_type in ['numerical', 'integer', 'fill_blank']:
                    correct = [str(q.correct_answer).strip()] if q.correct_answer is not None else []
                else:
                    correct = []
                
                answer_key[q_field] = {
                    'correct': correct,
                    'marks': float(data.get('marks', 1)),
                    'negative': float(data.get('negative', 0)),
                    'mapping_id': data.get('mapping_id'),
                    'question_id': q.id
                }
                global_idx += 1
                
        elif direct_questions.exists():
            # Check for direct Question linkage (fallback if ExamQuestion missing)
            raw_questions = []
            for q in direct_questions:
                subject_name = q.subject or 'General'
                section_name = q.pattern_section_name
                
                if section_name and section_name.lower() != subject_name.lower():
                    if len(section_name) <= 2:
                        display_name = f"{subject_name} - Section {section_name}"
                    else:
                        display_name = f"{subject_name} - {section_name}"
                else:
                    display_name = subject_name
                    
                raw_questions.append({
                    'question': q,
                    'section': display_name,
                    'original_number': q.question_number or 0,
                    'marks': q.marks,
                    'negative': q.negative_marks
                })
            
            # Re-sort to match OMR generator's sequential flow (original number first)
            raw_questions.sort(key=lambda x: (x['original_number'], x['section']))
            
            for data in raw_questions:
                q = data['question']
                q_field = f"Q{global_idx}"
                
                if q.question_type in ['single_mcq', 'single', 'multiple_mcq', 'multiple', 'true_false']:
                    # Use index-based mapping for MCQs
                    if isinstance(q.correct_answer, str) and ',' in q.correct_answer and all(len(x.strip()) == 1 for x in q.correct_answer.split(',')):
                        correct = [x.strip().upper() for x in q.correct_answer.split(',')]
                    elif isinstance(q.correct_answer, str) and len(q.correct_answer.strip()) == 1 and q.correct_answer.strip().upper() in ['A', 'B', 'C', 'D']:
                        correct = [q.correct_answer.strip().upper()]
                    else:
                        correct = []
                        q_options = q.options if isinstance(q.options, list) else []
                        ans_text = str(q.correct_answer).strip().lower()
                        for idx, opt in enumerate(q_options):
                            if str(opt).strip().lower() == ans_text and idx < 26:
                                correct.append(chr(65 + idx))
                        if not correct and ans_text.isdigit():
                            idx = int(ans_text)
                            if 0 <= idx < len(q_options):
                                correct.append(chr(65 + idx))
                elif q.question_type in ['numerical', 'integer', 'fill_blank']:
                    correct = [str(q.correct_answer).strip()] if q.correct_answer is not None else []
                else:
                    correct = []
                
                answer_key[q_field] = {
                    'correct': correct,
                    'marks': float(data.get('marks', 1)),
                    'negative': float(data.get('negative', 0)),
                    'mapping_id': None,
                    'question_id': q.id
                }
                global_idx += 1
                
        elif self.exam and self.exam.pattern:
            # Fallback to pattern sections
            sections = PatternSection.objects.filter(pattern=self.exam.pattern).order_by('start_question')
            for section in sections:
                # Combine subject and section name for display
                subject_name = section.subject or 'General'
                section_name = section.name
                if section_name and section_name.lower() != subject_name.lower():
                    display_name = f"{subject_name} - Section {section_name}" if len(section_name) <= 2 else f"{subject_name} - {section_name}"
                else:
                    display_name = subject_name

                for i in range(section.start_question, section.end_question + 1):
                    q_field = f"Q{global_idx}"
                    answer_key[q_field] = {
                        'correct': [], # Pattern mode defaults to empty correct answers unless mapped
                        'marks': float(section.marks_per_question),
                        'negative': float(section.negative_marking),
                        'section': display_name
                    }
                    global_idx += 1
        
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
            # Last resort: check if we can build it from questions or pattern
            answer_key = self._build_answer_key_from_questions()
            if answer_key:
                # Save it so it's permanent
                from ..models import AnswerKey
                AnswerKey.objects.update_or_create(
                    exam=self.exam,
                    defaults={'answers': answer_key}
                )
            else:
                raise ValueError(f"No answer key or questions found for exam {self.exam.id if self.exam else 'Unknown'}")

        
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
            # Match the same sequential logic as generator and answer key builder
            answer_key_data = self._build_answer_key_from_questions()
            
            details = self.submission.evaluation_results.get('details', [])
            for detail in details:
                q_field = detail.get('question')
                q_key_info = answer_key_data.get(q_field)
                if not q_key_info:
                    continue

                
                mapping_id = q_key_info.get('mapping_id')
                if not mapping_id:
                    continue
                    
                mapping = ExamQuestion.objects.get(id=mapping_id)

                
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
