"""
Extraction Pipeline - Orchestrates the complete extraction process
"""
import logging
import time
from uuid import UUID
from typing import Optional
from django.utils import timezone

from questions.models import ExtractionJob, ExtractedQuestion
from questions.services.file_parser import FileParserService, FileParsingError
from questions.services.gemini_extraction import GeminiExtractionService, GeminiExtractionError
from questions.services.question_validation import QuestionValidationService

logger = logging.getLogger('extraction')


class ExtractionPipeline:
    """Orchestrate the extraction process from file to extracted questions"""
    
    def __init__(self):
        """Initialize pipeline with all required services"""
        self.file_parser = FileParserService()
        self.ai_extractor = None  # Initialized when needed
        self.validator = QuestionValidationService()
    
    def process_file(self, job_id: UUID) -> None:
        """
        Process extraction job asynchronously
        
        Args:
            job_id: UUID of the extraction job
            
        Raises:
            Exception: If processing fails
        """
        start_time = time.time()
        
        try:
            # Get extraction job
            job = ExtractionJob.objects.get(id=job_id)
            
            logger.info(f"Starting extraction job {job_id} for file: {job.file_name}")
            
            # Update status to processing
            job.status = 'processing'
            job.progress_percent = 5
            job.save()
            
            # Step 1: Parse file to extract text (10-30%)
            logger.info(f"Step 1: Parsing file {job.file_name}")
            text_content, is_image = self._parse_file(job)
            job.update_progress(30)
            
            # Step 2: Build context for AI (30-40%)
            logger.info("Step 2: Building extraction context")
            context = self._build_context(job)
            job.update_progress(40)
            
            # Step 3: Extract questions using AI (40-70%)
            logger.info("Step 3: Extracting questions with Gemini AI")
            extracted_questions = self._extract_questions(
                job, 
                text_content, 
                context,
                is_image
            )
            job.update_progress(70)
            
            # Step 4: Validate and save extracted questions (70-90%)
            logger.info(f"Step 4: Validating and saving {len(extracted_questions)} questions")
            saved_count = self._save_extracted_questions(job, extracted_questions, context)
            job.update_progress(90)
            
            # Step 5: Finalize job (90-100%)
            logger.info("Step 5: Finalizing extraction job")
            processing_time = time.time() - start_time
            job.processing_time_seconds = processing_time
            job.total_questions_found = len(extracted_questions)
            job.questions_extracted = saved_count
            job.mark_completed()
            
            logger.info(
                f"Extraction job {job_id} completed successfully. "
                f"Extracted {saved_count}/{len(extracted_questions)} questions "
                f"in {processing_time:.2f} seconds"
            )
            
        except ExtractionJob.DoesNotExist:
            logger.error(f"Extraction job {job_id} not found")
            raise
        
        except Exception as e:
            logger.error(f"Extraction job {job_id} failed: {str(e)}", exc_info=True)
            
            try:
                job = ExtractionJob.objects.get(id=job_id)
                job.mark_failed(str(e))
            except:
                pass
            
            raise
    
    def _parse_file(self, job: ExtractionJob) -> tuple[str, bool]:
        """
        Parse file to extract text content
        
        Args:
            job: ExtractionJob instance
            
        Returns:
            Tuple of (text_content, is_image)
            
        Raises:
            FileParsingError: If parsing fails
        """
        try:
            # Validate file size
            self.file_parser.validate_file_size(job.file_path, max_size_mb=10)
            
            # Parse file
            text_content = self.file_parser.parse_file(job.file_path, job.file_type)
            
            # Check if it's an image file
            is_image = text_content.startswith('[IMAGE_FILE:')
            
            if is_image:
                logger.info(f"Detected image file: {job.file_name}")
            else:
                logger.info(f"Extracted {len(text_content)} characters from {job.file_name}")
            
            return text_content, is_image
            
        except FileParsingError as e:
            logger.error(f"File parsing failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during file parsing: {e}")
            raise FileParsingError(f"Failed to parse file: {str(e)}")
    
    def _build_context(self, job: ExtractionJob) -> dict:
        """
        Build context for AI extraction
        
        Args:
            job: ExtractionJob instance
            
        Returns:
            Context dictionary
        """
        pattern = job.pattern
        sections = pattern.sections.all()
        
        # Get unique subjects and question types
        subjects = list(set(s.subject for s in sections))
        question_types = list(set(s.question_type for s in sections))
        
        context = {
            'pattern_name': pattern.name,
            'pattern_id': pattern.id,
            'exam_id': job.exam.id,
            'subjects': subjects,
            'allowed_question_types': question_types,
            'total_questions_needed': pattern.total_questions,
            'sections': [
                {
                    'id': s.id,
                    'name': s.name,
                    'subject': s.subject,
                    'question_type': s.question_type,
                    'start': s.start_question,
                    'end': s.end_question,
                    'marks': s.marks_per_question,
                }
                for s in sections
            ]
        }
        
        # If only one subject, use it as default
        if len(subjects) == 1:
            context['subject'] = subjects[0]
        
        return context
    
    def _extract_questions(
        self,
        job: ExtractionJob,
        text_content: str,
        context: dict,
        is_image: bool
    ) -> list:
        """
        Extract questions using Gemini AI
        
        Args:
            job: ExtractionJob instance
            text_content: Parsed text or image marker
            context: Extraction context
            is_image: Whether content is from image
            
        Returns:
            List of extracted questions
            
        Raises:
            GeminiExtractionError: If extraction fails
        """
        try:
            # Initialize AI extractor if not already done
            if not self.ai_extractor:
                self.ai_extractor = GeminiExtractionService()
            
            # Determine image path if needed
            image_path = None
            if is_image:
                # Extract path from marker
                import re
                match = re.search(r'\[IMAGE_FILE:(.*?)\]', text_content)
                if match:
                    image_path = match.group(1)
            
            # Extract questions
            questions = self.ai_extractor.extract_questions(
                text_content,
                context,
                is_image=is_image,
                image_path=image_path
            )
            
            # Update job with AI metadata
            job.ai_model_used = self.ai_extractor.model
            # Note: tokens_used would need to be extracted from API response
            # For now, we'll estimate based on content length
            job.tokens_used = len(text_content) // 4  # Rough estimate
            job.save(update_fields=['ai_model_used', 'tokens_used'])
            
            return questions
            
        except GeminiExtractionError as e:
            logger.error(f"Gemini extraction failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during extraction: {e}")
            raise GeminiExtractionError(f"Failed to extract questions: {str(e)}")
    
    def _save_extracted_questions(
        self,
        job: ExtractionJob,
        questions: list,
        context: dict
    ) -> int:
        """
        Validate and save extracted questions
        
        Args:
            job: ExtractionJob instance
            questions: List of extracted questions
            context: Extraction context
            
        Returns:
            Number of questions saved
        """
        saved_count = 0
        
        for question_data in questions:
            try:
                # Suggest subject and section
                suggested_subject, suggested_section_id = self._suggest_mapping(
                    question_data,
                    context
                )
                
                # Create ExtractedQuestion
                extracted_q = ExtractedQuestion.objects.create(
                    job=job,
                    question_text=question_data['question_text'],
                    question_type=question_data['question_type'],
                    options=question_data.get('options', []),
                    correct_answer=question_data['correct_answer'],
                    solution=question_data.get('solution', ''),
                    explanation=question_data.get('explanation', ''),
                    difficulty=question_data.get('difficulty', 'medium'),
                    confidence_score=question_data['confidence_score'],
                    requires_review=question_data['confidence_score'] < 0.7,
                    suggested_subject=suggested_subject,
                    suggested_section_id=suggested_section_id,
                )
                
                # Validate the question
                is_valid, errors = extracted_q.validate()
                
                if not is_valid:
                    logger.warning(
                        f"Question validation failed: {'; '.join(errors)}"
                    )
                
                saved_count += 1
                
            except Exception as e:
                logger.error(f"Failed to save extracted question: {e}")
                continue
        
        logger.info(f"Saved {saved_count}/{len(questions)} extracted questions")
        return saved_count
    
    def _suggest_mapping(self, question_data: dict, context: dict) -> tuple:
        """
        Suggest subject and section for a question
        
        Args:
            question_data: Extracted question data
            context: Extraction context
            
        Returns:
            Tuple of (suggested_subject, suggested_section_id)
        """
        question_type = question_data.get('question_type')
        ai_suggested_subject = question_data.get('subject', '').strip()
        
        # Get available subjects
        subjects = context.get('subjects', [])
        
        # Use AI-suggested subject if it matches available subjects
        suggested_subject = None
        if ai_suggested_subject:
            # Case-insensitive match
            for subj in subjects:
                if subj.lower() == ai_suggested_subject.lower():
                    suggested_subject = subj
                    break
        
        # Fallback to single subject or first subject
        if not suggested_subject:
            if len(subjects) == 1:
                suggested_subject = subjects[0]
            elif subjects:
                suggested_subject = subjects[0]
            else:
                suggested_subject = ''
        
        # Find matching section (prefer subject + type match)
        suggested_section_id = None
        fallback_section_id = None
        
        for section in context.get('sections', []):
            if section['question_type'] == question_type:
                if section['subject'] == suggested_subject:
                    # Perfect match: subject + type
                    suggested_section_id = section['id']
                    break
                elif not fallback_section_id:
                    # Fallback: just type match
                    fallback_section_id = section['id']
        
        # Use fallback if no perfect match
        if not suggested_section_id and fallback_section_id:
            suggested_section_id = fallback_section_id
            # Update subject to match the fallback section
            for section in context.get('sections', []):
                if section['id'] == fallback_section_id:
                    suggested_subject = section['subject']
                    break
        
        return suggested_subject, suggested_section_id
    
    def retry_failed_job(self, job_id: UUID) -> None:
        """
        Retry a failed extraction job
        
        Args:
            job_id: UUID of the failed job
        """
        try:
            job = ExtractionJob.objects.get(id=job_id)
            
            if job.status not in ['failed', 'partial']:
                logger.warning(f"Job {job_id} is not in failed/partial state")
                return
            
            # Increment retry count
            job.retry_count += 1
            job.status = 'pending'
            job.error_message = ''
            job.save()
            
            logger.info(f"Retrying extraction job {job_id} (attempt {job.retry_count})")
            
            # Process the job
            self.process_file(job_id)
            
        except ExtractionJob.DoesNotExist:
            logger.error(f"Extraction job {job_id} not found")
            raise
