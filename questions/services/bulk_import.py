"""
Bulk Import Service for importing validated questions into database
"""
import logging
from typing import List, Dict, Optional
from uuid import UUID
from django.db import transaction
from django.utils import timezone

from questions.models import Question, ExtractedQuestion, ExtractionJob
from exams.models import Exam
from patterns.models import PatternSection

logger = logging.getLogger('extraction')


class BulkImportError(Exception):
    """Raised when bulk import fails"""
    pass


class BulkImportService:
    """Import validated questions into database"""
    
    def import_questions(
        self, 
        extraction_job_id: UUID, 
        question_mappings: List[Dict]
    ) -> Dict:
        """
        Import extracted questions into exam
        
        Args:
            extraction_job_id: ID of extraction job
            question_mappings: List of questions with section assignments
                Format: [
                    {
                        'extracted_question_id': 1,
                        'subject': 'physics',
                        'section_id': 5,
                        'question_number': 1
                    },
                    ...
                ]
            
        Returns:
            Import summary with success/failure counts
            
        Raises:
            BulkImportError: If import fails
        """
        try:
            # Get extraction job
            job = ExtractionJob.objects.get(id=extraction_job_id)
            
            # Get extracted questions
            extracted_question_ids = [m['extracted_question_id'] for m in question_mappings]
            extracted_questions = ExtractedQuestion.objects.filter(
                id__in=extracted_question_ids,
                job=job
            )
            
            if not extracted_questions.exists():
                raise BulkImportError("No extracted questions found for import")
            
            # Create mapping dictionary for quick lookup
            mapping_dict = {m['extracted_question_id']: m for m in question_mappings}
            
            # Track next question number per section
            section_next_numbers = {}
            
            def get_next_question_number_for_section(section_id):
                """Get the next available question number for a section"""
                if section_id not in section_next_numbers:
                    # Get the section to know its range
                    try:
                        section = PatternSection.objects.get(id=section_id)
                        # Find the last question in this section for this exam
                        last_in_section = Question.objects.filter(
                            exam=job.exam,
                            pattern_section_id=section_id,
                            is_active=True
                        ).order_by('-question_number').first()
                        
                        if last_in_section:
                            section_next_numbers[section_id] = last_in_section.question_number + 1
                        else:
                            # Start from section's start_question
                            section_next_numbers[section_id] = section.start_question
                    except PatternSection.DoesNotExist:
                        # Fallback to sequential numbering
                        last_question = Question.objects.filter(
                            exam=job.exam,
                            is_active=True
                        ).order_by('-question_number').first()
                        section_next_numbers[section_id] = (last_question.question_number + 1) if last_question else 1
                
                current = section_next_numbers[section_id]
                section_next_numbers[section_id] += 1
                return current
            
            # Import questions - each in its own transaction
            imported_count = 0
            failed_count = 0
            failed_questions = []
            
            for extracted_q in extracted_questions:
                mapping = mapping_dict.get(extracted_q.id)
                if not mapping:
                    continue
                
                try:
                    with transaction.atomic():
                        # Get question number based on section
                        section_id = mapping.get('section_id')
                        question_number = get_next_question_number_for_section(section_id)
                        mapping['question_number'] = question_number
                        
                        # Create Question record
                        question = self._create_question(
                            extracted_q,
                            job.exam,
                            mapping
                        )
                        
                        # Mark as imported
                        extracted_q.mark_imported(question)
                        imported_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to import question {extracted_q.id}: {e}")
                    # Mark failed outside transaction
                    try:
                        extracted_q.mark_failed(str(e))
                    except Exception as mark_error:
                        logger.error(f"Failed to mark question as failed: {mark_error}")
                    
                    failed_count += 1
                    failed_questions.append({
                        'id': extracted_q.id,
                        'question_text': extracted_q.question_text[:100],
                        'error': str(e)
                    })
            
            # Update job metrics in separate transaction
            with transaction.atomic():
                job.questions_imported = imported_count
                job.questions_failed = failed_count
                
                if failed_count == 0:
                    job.mark_completed()
                elif imported_count > 0:
                    job.mark_partial()
                else:
                    job.mark_failed("All questions failed to import")
                
                # Update exam metrics
                self.update_exam_metrics(job.exam)
            
            return {
                'success': True,
                'imported_count': imported_count,
                'failed_count': failed_count,
                'failed_questions': failed_questions,
                'exam_id': job.exam.id,
            }
            
        except ExtractionJob.DoesNotExist:
            raise BulkImportError(f"Extraction job {extraction_job_id} not found")
        except Exception as e:
            logger.error(f"Bulk import failed: {e}")
            raise BulkImportError(f"Failed to import questions: {str(e)}")
    
    def _create_question(
        self,
        extracted_q: ExtractedQuestion,
        exam: Exam,
        mapping: Dict
    ) -> Question:
        """
        Create Question record from ExtractedQuestion
        
        Args:
            extracted_q: ExtractedQuestion instance
            exam: Exam to import into
            mapping: Mapping with section and number info
            
        Returns:
            Created Question instance
        """
        # Get section if section_id provided
        section = None
        if mapping.get('section_id'):
            try:
                section = PatternSection.objects.get(id=mapping['section_id'])
            except PatternSection.DoesNotExist:
                logger.warning(f"Section {mapping['section_id']} not found")
        
        # Determine marks and negative marks from section or defaults
        marks = section.marks_per_question if section else 1
        negative_marks = float(section.negative_marking) if section else 0.25
        
        # Create Question
        question = Question.objects.create(
            exam=exam,
            question_text=extracted_q.question_text,
            question_type=extracted_q.question_type,
            difficulty=extracted_q.difficulty,
            options=extracted_q.options,
            correct_answer=extracted_q.correct_answer,
            solution=extracted_q.solution,
            explanation=extracted_q.explanation,
            marks=marks,
            negative_marks=negative_marks,
            subject=mapping.get('subject', extracted_q.assigned_subject or ''),
            question_number=mapping.get('question_number'),
            question_number_in_pattern=mapping.get('question_number_in_pattern'),
            pattern_section_id=mapping.get('section_id'),
            pattern_section_name=section.name if section else '',
            institute=exam.institute,
            created_by=exam.created_by,
            is_active=True,
        )
        
        return question
    
    def assign_question_numbers(
        self, 
        questions: List[Dict], 
        pattern_section: PatternSection
    ) -> List[Dict]:
        """
        Assign sequential question numbers based on section
        
        Args:
            questions: List of question data
            pattern_section: Target pattern section
            
        Returns:
            Questions with assigned numbers
        """
        # Get existing questions in this section
        existing_questions = Question.objects.filter(
            exam__pattern=pattern_section.pattern,
            pattern_section_id=pattern_section.id,
            is_active=True
        ).order_by('-question_number')
        
        # Get next available number
        if existing_questions.exists():
            next_number = existing_questions.first().question_number + 1
        else:
            next_number = pattern_section.start_question
        
        # Assign numbers sequentially
        for i, question in enumerate(questions):
            question['question_number'] = next_number + i
            question['section_id'] = pattern_section.id
        
        return questions
    
    def create_question_batch(
        self, 
        questions: List[Dict],
        exam: Exam
    ) -> List[Question]:
        """
        Bulk create Question instances
        
        Args:
            questions: List of question data dictionaries
            exam: Exam to create questions for
            
        Returns:
            List of created Question instances
        """
        question_objects = []
        
        for q_data in questions:
            question = Question(
                exam=exam,
                question_text=q_data['question_text'],
                question_type=q_data['question_type'],
                difficulty=q_data.get('difficulty', 'medium'),
                options=q_data.get('options', []),
                correct_answer=q_data['correct_answer'],
                solution=q_data.get('solution', ''),
                explanation=q_data.get('explanation', ''),
                marks=q_data.get('marks', 1),
                negative_marks=q_data.get('negative_marks', 0.25),
                subject=q_data.get('subject', ''),
                question_number=q_data.get('question_number'),
                pattern_section_id=q_data.get('section_id'),
                pattern_section_name=q_data.get('section_name', ''),
                institute=exam.institute,
                created_by=exam.created_by,
                is_active=True,
            )
            question_objects.append(question)
        
        # Bulk create
        created_questions = Question.objects.bulk_create(question_objects)
        
        logger.info(f"Bulk created {len(created_questions)} questions")
        return created_questions
    
    def update_exam_metrics(self, exam: Exam) -> None:
        """
        Update exam question completion metrics
        
        Args:
            exam: Exam to update
        """
        try:
            # The exam model has properties that calculate these automatically
            # Just trigger a save to ensure any cached values are updated
            exam.save(update_fields=['updated_at'])
            
            logger.info(
                f"Updated exam {exam.id} metrics: "
                f"{exam.questions_added}/{exam.questions_required} questions "
                f"({exam.question_completion_percent}% complete)"
            )
            
        except Exception as e:
            logger.error(f"Failed to update exam metrics: {e}")
    
    def import_from_extracted_questions(
        self,
        extracted_question_ids: List[int],
        exam_id: int,
        default_subject: Optional[str] = None
    ) -> Dict:
        """
        Import questions directly from ExtractedQuestion IDs
        
        Args:
            extracted_question_ids: List of ExtractedQuestion IDs
            exam_id: Target exam ID
            default_subject: Default subject if not assigned
            
        Returns:
            Import summary
        """
        try:
            exam = Exam.objects.get(id=exam_id)
            extracted_questions = ExtractedQuestion.objects.filter(
                id__in=extracted_question_ids
            )
            
            if not extracted_questions.exists():
                raise BulkImportError("No extracted questions found")
            
            imported_count = 0
            failed_count = 0
            failed_questions = []
            
            for extracted_q in extracted_questions:
                try:
                    with transaction.atomic():
                        # Determine subject
                        subject = (
                            extracted_q.assigned_subject or 
                            extracted_q.suggested_subject or 
                            default_subject or 
                            ''
                        )
                        
                        # Get next question number
                        last_question = Question.objects.filter(
                            exam=exam,
                            subject=subject,
                            is_active=True
                        ).order_by('-question_number').first()
                        
                        next_number = (last_question.question_number + 1) if last_question else 1
                        
                        # Create mapping
                        mapping = {
                            'subject': subject,
                            'section_id': extracted_q.assigned_section_id,
                            'question_number': next_number
                        }
                        
                        # Create question
                        question = self._create_question(extracted_q, exam, mapping)
                        extracted_q.mark_imported(question)
                        imported_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to import question {extracted_q.id}: {e}")
                    # Mark failed outside transaction
                    try:
                        extracted_q.mark_failed(str(e))
                    except Exception as mark_error:
                        logger.error(f"Failed to mark question as failed: {mark_error}")
                    
                    failed_count += 1
                    failed_questions.append({
                        'id': extracted_q.id,
                        'question_text': extracted_q.question_text[:100],
                        'error': str(e)
                    })
            
            # Update exam metrics in separate transaction
            with transaction.atomic():
                self.update_exam_metrics(exam)
            
            return {
                'success': True,
                'imported_count': imported_count,
                'failed_count': failed_count,
                'failed_questions': failed_questions,
                'exam_id': exam.id,
            }
            
        except Exam.DoesNotExist:
            raise BulkImportError(f"Exam {exam_id} not found")
        except Exception as e:
            logger.error(f"Import failed: {e}")
            raise BulkImportError(f"Failed to import questions: {str(e)}")
