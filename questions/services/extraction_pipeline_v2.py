"""
Extraction Pipeline V2 - Enhanced orchestration with complete extraction
"""
import logging
import re
import time
from uuid import UUID
from typing import Optional, Tuple, List, Dict
from django.utils import timezone
from django.db import transaction

from questions.models import ExtractionJob, ExtractedQuestion
from questions.services.file_parser import FileParserService, FileParsingError
from questions.services.gemini_extraction_v2 import GeminiExtractionServiceV2, GeminiExtractionError
from questions.services.question_validation import QuestionValidationService
from questions.services.pre_analyzer import PreAnalyzer
from questions.services.question_type_classifier import QuestionTypeClassifier
from questions.services.subject_categorizer import SubjectCategorizer, SubjectCategorizationError

logger = logging.getLogger('extraction')


class ExtractionPipelineV2:
    """
    Enhanced extraction pipeline with:
    - Pre-analysis for question counting
    - Complete extraction validation
    - Accurate type classification
    - LaTeX preservation
    - Progress tracking
    """
    
    def __init__(self):
        """Initialize pipeline with all required services"""
        self.file_parser = FileParserService()
        self.ai_extractor = None  # Lazy initialization
        self.subject_categorizer = None  # Lazy initialization
        self.validator = QuestionValidationService()
        self.pre_analyzer = PreAnalyzer()
        self.type_classifier = QuestionTypeClassifier()
    
    def process_file(
        self, 
        job_id: UUID,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        Process extraction job with complete extraction guarantee.
        
        ENHANCED: Now checks for pre-analysis job and uses subject-separated
        content for more accurate extraction with 100% correct subject assignment.
        
        Args:
            job_id: UUID of the extraction job
            progress_callback: Optional callback for progress updates
            
        Returns:
            Extraction result summary
        """
        start_time = time.time()
        
        try:
            # Get extraction job
            job = ExtractionJob.objects.get(id=job_id)
            
            logger.info(f"Starting extraction job {job_id} for file: {job.file_name}")
            
            # Update status
            job.status = 'processing'
            job.progress_percent = 5
            job.save()
            
            self._update_progress(job, 5, "Starting extraction...", progress_callback)
            
            # NEW: Check for pre-analysis job with subject-separated content
            pre_analysis = self._get_pre_analysis(job)
            
            if pre_analysis and pre_analysis.subject_separated_content:
                logger.info(
                    f"Using pre-analysis with {len(pre_analysis.subject_separated_content)} subjects: "
                    f"{list(pre_analysis.subject_separated_content.keys())}"
                )
                return self._process_with_pre_analysis(
                    job, pre_analysis, start_time, progress_callback
                )
            else:
                logger.info("No pre-analysis available, using standard extraction flow")
                return self._process_without_pre_analysis(
                    job, start_time, progress_callback
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
    
    def _get_pre_analysis(self, job: ExtractionJob):
        """Get linked pre-analysis job if available"""
        # Check direct link first (new field)
        if job.pre_analysis_job:
            return job.pre_analysis_job
        
        # Check reverse relationship (old behavior)
        pre_analysis = job.pre_analysis.first()
        if pre_analysis:
            return pre_analysis
        
        return None
    
    def _process_with_pre_analysis(
        self,
        job: ExtractionJob,
        pre_analysis,
        start_time: float,
        progress_callback: Optional[callable]
    ) -> Dict:
        """
        Process extraction using pre-analyzed subject-separated content.
        
        This is the PREFERRED path - questions are extracted from each subject's
        content separately, ensuring 100% accurate subject assignment.
        
        ENHANCED: Now uses document_structure (sections, instructions, marking scheme)
        to guide extraction and tag questions with their detected section type.
        
        Args:
            job: Extraction job
            pre_analysis: PreAnalysisJob with subject_separated_content
            start_time: Start time for processing duration calculation
            progress_callback: Progress callback
            
        Returns:
            Extraction result summary
        """
        logger.info("="*60)
        logger.info("USING PRE-ANALYSIS SUBJECT-SEPARATED CONTENT")
        logger.info("="*60)
        
        # Get subject-separated content (now includes instructions per subject)
        subject_content_dict = pre_analysis.subject_separated_content
        subjects = list(subject_content_dict.keys())
        total_subjects = len(subjects)
        
        # Get document structure if available (sections, instructions, marking scheme)
        document_structure = pre_analysis.document_structure or {}
        if document_structure:
            logger.info(f"Using document structure: {len(document_structure.get('sections', []))} sections detected")
            logger.info(f"  Instructions: {document_structure.get('has_instructions', False)}")
            logger.info(f"  Marking scheme: {document_structure.get('marking_scheme', {})}")
            for section in document_structure.get('sections', []):
                logger.info(f"  Section: {section.get('name')} - {section.get('type_hint')} ({section.get('question_range')})")
        
        # Use pre-analysis question estimates
        expected_count = pre_analysis.total_estimated_questions
        job.total_questions_found = expected_count
        job.save(update_fields=['total_questions_found'])
        
        self._update_progress(
            job, 10, 
            f"Processing {total_subjects} subjects with ~{expected_count} questions", 
            progress_callback
        )
        
        # Build context - ENHANCED: include document structure
        context = self._build_context(job)
        context['document_structure'] = document_structure  # Add structure to context
        # Default instructions from document structure (will be overridden per subject)
        context['instructions'] = document_structure.get('instructions_text', '')
        context['marking_scheme'] = document_structure.get('marking_scheme', {})
        context['detected_sections'] = document_structure.get('sections', [])
        self._update_progress(job, 15, "Context built with document structure", progress_callback)
        
        # Extract questions from each subject separately
        all_questions = []
        subject_counts = {}
        
        # Get question counts per subject from pre-analysis
        subject_question_counts = pre_analysis.subject_question_counts or {}
        
        for i, subject in enumerate(subjects):
            # Get subject data (handle both new format with instructions and old format)
            subject_data = subject_content_dict.get(subject, {})
            if isinstance(subject_data, dict):
                content = subject_data.get('content', '')
                subject_instructions = subject_data.get('instructions', '')
            else:
                # Backward compatibility: old format (just string)
                content = str(subject_data) if subject_data else ''
                subject_instructions = ''
            
            if not content or not content.strip():
                logger.warning(f"Empty content for subject: {subject}")
                continue
            
            # Calculate progress for this subject (15-80% range divided among subjects)
            progress_start = 15 + int((i / total_subjects) * 65)
            progress_end = 15 + int(((i + 1) / total_subjects) * 65)
            
            self._update_progress(
                job, progress_start, 
                f"Extracting {subject} ({i+1}/{total_subjects})...", 
                progress_callback
            )
            
            # Get expected question count for this subject from pre-analysis
            expected_for_subject = subject_question_counts.get(subject, 0)
            logger.info(f"Extracting subject {i+1}/{total_subjects}: {subject} ({len(content)} chars, ~{expected_for_subject} questions expected)")
            if subject_instructions:
                logger.info(f"  Using subject-specific instructions ({len(subject_instructions)} chars)")
            
            # Create subject-specific context with expected count and subject-specific instructions
            subject_context = context.copy()
            subject_context['subject'] = subject
            subject_context['current_subject'] = subject
            subject_context['expected_question_count'] = expected_for_subject  # CRITICAL: Pass expected count
            # Use subject-specific instructions if available, otherwise fall back to document-level
            subject_context['instructions'] = subject_instructions if subject_instructions else context.get('instructions', '')
            
            try:
                # Extract questions from this subject's content ONLY
                extraction_result = self._extract_questions_v2(
                    job,
                    content,
                    subject_context,
                    is_image=False,
                    progress_callback=None  # Don't flood with sub-progress
                )
                
                questions = extraction_result.get('questions', [])
                
                # CRITICAL: Assign subject to ALL extracted questions (100% accurate)
                for q in questions:
                    q['subject'] = subject
                    q['suggested_subject'] = subject
                    q['subject_source'] = 'pre_analysis'  # Mark source for debugging
                
                all_questions.extend(questions)
                subject_counts[subject] = len(questions)
                
                logger.info(f"  -> Extracted {len(questions)} questions from {subject}")
                
            except Exception as e:
                logger.error(f"Failed to extract questions from {subject}: {e}")
                subject_counts[subject] = 0
        
        self._update_progress(job, 80, "All subjects processed", progress_callback)
        
        # Log summary
        total_extracted = len(all_questions)
        logger.info(f"Total extracted from all subjects: {total_extracted}")
        logger.info(f"Subject distribution: {subject_counts}")
        
        # Skip AI categorization - subjects are already assigned!
        logger.info("Skipping AI categorization (subjects already assigned from pre-analysis)")
        self._update_progress(job, 85, "Subjects already assigned", progress_callback)
        
        # Save extracted questions
        logger.info(f"Saving {total_extracted} questions")
        saved_count = self._save_extracted_questions(job, all_questions, context)
        self._update_progress(job, 95, f"Saved {saved_count} questions", progress_callback)
        
        # Finalize
        processing_time = time.time() - start_time
        job.processing_time_seconds = processing_time
        job.questions_extracted = saved_count
        
        # Determine completeness
        completeness = (saved_count / expected_count * 100) if expected_count > 0 else 100
        
        if completeness >= 90:
            job.mark_completed()
        elif completeness >= 50:
            job.mark_partial()
        else:
            job.mark_failed(
                f"Low extraction completeness: {completeness:.1f}% "
                f"({saved_count}/{expected_count} questions)"
            )
        
        self._update_progress(job, 100, "Extraction complete", progress_callback)
        
        # Get type distribution from saved questions
        type_distribution = {}
        for q in all_questions:
            qtype = q.get('question_type', 'unknown')
            type_distribution[qtype] = type_distribution.get(qtype, 0) + 1
        
        result = {
            'job_id': str(job.id),
            'status': job.status,
            'expected_count': expected_count,
            'extracted_count': saved_count,
            'completeness': completeness,
            'processing_time': processing_time,
            'type_distribution': type_distribution,
            'has_latex': any('$' in q.get('question_text', '') for q in all_questions),
            'detected_subjects': subjects,
            'subject_counts': subject_counts,
            'extraction_method': 'pre_analysis_subject_separated',  # Mark method used
        }
        
        logger.info(
            f"Extraction job {job.id} completed (with pre-analysis): "
            f"{saved_count}/{expected_count} questions ({completeness:.1f}%) "
            f"in {processing_time:.2f}s"
        )
        
        return result
    
    def _process_without_pre_analysis(
        self,
        job: ExtractionJob,
        start_time: float,
        progress_callback: Optional[callable]
    ) -> Dict:
        """
        Process extraction without pre-analysis (legacy flow).
        
        This is the FALLBACK path - used when no pre-analysis is available.
        Subjects are guessed after extraction using AI categorization.
        
        Args:
            job: Extraction job
            start_time: Start time for processing duration calculation
            progress_callback: Progress callback
            
        Returns:
            Extraction result summary
        """
        logger.info("Using standard extraction flow (no pre-analysis)")
        
        # Step 1: Parse file (5-15%)
        logger.info("Step 1: Parsing file")
        text_content, is_image = self._parse_file(job)
        self._update_progress(job, 15, "File parsed", progress_callback)
        
        # Step 2: Pre-analyze content (15-25%)
        logger.info("Step 2: Pre-analyzing content")
        analysis = self.pre_analyzer.analyze_file(text_content)
        expected_count = analysis['estimated_question_count']
        
        # Store pre-analysis results
        job.total_questions_found = expected_count
        job.save(update_fields=['total_questions_found'])
        
        self._update_progress(
            job, 25, 
            f"Found ~{expected_count} questions", 
            progress_callback
        )
        
        logger.info(f"Pre-analysis: {expected_count} questions expected")
        
        # Step 3: Build context (25-30%)
        logger.info("Step 3: Building extraction context")
        context = self._build_context(job)
        self._update_progress(job, 30, "Context built", progress_callback)
        
        # Step 4: Extract questions with V2 service (30-80%)
        logger.info("Step 4: Extracting questions with enhanced AI")
        
        def extraction_progress(percent, message):
            # Map 0-100 to 30-80
            mapped_percent = 30 + int(percent * 0.5)
            self._update_progress(job, mapped_percent, message, progress_callback)
        
        extraction_result = self._extract_questions_v2(
            job,
            text_content,
            context,
            is_image,
            extraction_progress
        )
        
        self._update_progress(job, 75, "Questions extracted", progress_callback)
        
        # Log extraction result details
        questions_list = extraction_result.get('questions', [])
        logger.info(f"Extraction result: {len(questions_list)} questions in result")
        if questions_list:
            sample = questions_list[0]
            logger.info(f"Sample question keys: {sample.keys() if isinstance(sample, dict) else 'not a dict'}")
            logger.info(f"Sample question_text: {sample.get('question_text', 'MISSING')[:100] if isinstance(sample, dict) else 'N/A'}")
        
        # Step 5: Categorize questions by subject (75-85%)
        logger.info(f"Step 5: Categorizing {len(questions_list)} questions by subject")
        self._update_progress(job, 78, "Categorizing by subject...", progress_callback)
        
        available_subjects = context.get('subjects', [])
        if available_subjects and len(questions_list) > 0:
            try:
                categorization_result = self._categorize_questions(
                    questions_list,
                    available_subjects
                )
                questions_list = categorization_result['questions']
                logger.info(f"Subject distribution: {categorization_result['subject_counts']}")
            except Exception as e:
                logger.warning(f"Subject categorization failed, continuing without: {e}")
        
        self._update_progress(job, 85, "Questions categorized", progress_callback)
        
        # Step 6: Save extracted questions (85-95%)
        logger.info(f"Step 6: Saving {len(questions_list)} questions")
        saved_count = self._save_extracted_questions(
            job, 
            questions_list,
            context
        )
        self._update_progress(job, 95, f"Saved {saved_count} questions", progress_callback)
        
        # Step 7: Finalize (95-100%)
        logger.info("Step 7: Finalizing extraction")
        processing_time = time.time() - start_time
        
        # Update job with results
        job.processing_time_seconds = processing_time
        job.questions_extracted = saved_count
        
        # Determine final status
        metadata = extraction_result['metadata']
        completeness = metadata['completeness']
        
        # Status thresholds:
        # - 90%+ = completed (excellent extraction)
        # - 50%+ = partial (acceptable, user can review)
        # - <50% = failed (too many missing questions)
        if completeness >= 90:
            job.mark_completed()
        elif completeness >= 50:
            job.mark_partial()
        else:
            job.mark_failed(
                f"Low extraction completeness: {completeness:.1f}% "
                f"({saved_count}/{expected_count} questions)"
            )
        
        self._update_progress(job, 100, "Extraction complete", progress_callback)
        
        result = {
            'job_id': str(job.id),
            'status': job.status,
            'expected_count': expected_count,
            'extracted_count': saved_count,
            'completeness': completeness,
            'processing_time': processing_time,
            'type_distribution': metadata['type_distribution'],
            'has_latex': metadata['has_latex'],
            'detected_subjects': metadata.get('detected_subjects', []),
            'extraction_method': 'standard',  # Mark method used
        }
        
        logger.info(
            f"Extraction job {job.id} completed: "
            f"{saved_count}/{expected_count} questions ({completeness:.1f}%) "
            f"in {processing_time:.2f}s"
        )
        
        return result
    
    def _update_progress(
        self,
        job: ExtractionJob,
        percent: int,
        message: str,
        callback: Optional[callable]
    ):
        """Update job progress and call callback if provided"""
        job.progress_percent = percent
        job.save(update_fields=['progress_percent'])
        
        if callback:
            callback(percent, message)
        
        logger.debug(f"Progress: {percent}% - {message}")
    
    def _parse_file(self, job: ExtractionJob) -> Tuple[str, bool]:
        """Parse file to extract text content"""
        try:
            self.file_parser.validate_file_size(job.file_path, max_size_mb=10)
            text_content = self.file_parser.parse_file(job.file_path, job.file_type)
            
            is_image = text_content.startswith('[IMAGE_FILE:')
            
            if is_image:
                logger.info(f"Detected image file: {job.file_name}")
            else:
                logger.info(f"Extracted {len(text_content)} characters from {job.file_name}")
            
            return text_content, is_image
            
        except FileParsingError as e:
            logger.error(f"File parsing failed: {e}")
            raise
    
    def _build_context(self, job: ExtractionJob) -> dict:
        """Build context for AI extraction"""
        pattern = job.pattern
        sections = pattern.sections.all()
        
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
        
        if len(subjects) == 1:
            context['subject'] = subjects[0]
        
        return context
    
    def _extract_questions_v2(
        self,
        job: ExtractionJob,
        text_content: str,
        context: dict,
        is_image: bool,
        progress_callback: Optional[callable]
    ) -> Dict:
        """Extract questions using V2 service"""
        try:
            # Initialize V2 extractor
            if not self.ai_extractor:
                self.ai_extractor = GeminiExtractionServiceV2()
            
            # Determine image path if needed
            image_path = None
            if is_image:
                import re
                match = re.search(r'\[IMAGE_FILE:(.*?)\]', text_content)
                if match:
                    image_path = match.group(1)
            
            # Extract with V2 service
            result = self.ai_extractor.extract_questions(
                text_content,
                context,
                is_image=is_image,
                image_path=image_path,
                progress_callback=progress_callback
            )
            
            # Update job metadata
            job.ai_model_used = self.ai_extractor.model
            job.save(update_fields=['ai_model_used'])
            
            return result
            
        except GeminiExtractionError as e:
            logger.error(f"V2 extraction failed: {e}")
            raise
    
    def _save_extracted_questions(
        self,
        job: ExtractionJob,
        questions: List[Dict],
        context: dict
    ) -> int:
        """
        Save extracted questions to database.
        ENHANCED: Now stores detected section information from AI analysis.
        """
        saved_count = 0
        
        # Get marking scheme from context if available
        marking_scheme = context.get('marking_scheme', {})
        detected_sections = context.get('detected_sections', [])
        
        with transaction.atomic():
            for question_data in questions:
                try:
                    # Get subject from extracted data or suggest one
                    extracted_subject = question_data.get('subject', '')
                    suggested_subject, suggested_section_id = self._suggest_mapping(
                        question_data,
                        context
                    )
                    
                    # Use extracted subject if valid, otherwise use suggested
                    final_subject = extracted_subject if extracted_subject else suggested_subject
                    
                    # Get question type (default to single_mcq if not provided)
                    question_type = question_data.get('question_type', 'single_mcq')
                    if not question_type or question_type == 'unknown':
                        # Detect type based on options
                        options = question_data.get('options', [])
                        if options and len(options) >= 2:
                            question_type = 'single_mcq'
                        else:
                            question_type = 'subjective'
                    
                    # Get question text
                    q_text = question_data.get('question_text', '')
                    if not q_text:
                        logger.warning(f"Skipping question with empty text: {question_data}")
                        continue
                    
                    logger.debug(f"Saving question: {q_text[:50]}... subject={final_subject}")
                    
                    # Get options and correct answer
                    options = question_data.get('options', []) or []
                    correct_answer = str(question_data.get('correct_answer', ''))
                    
                    # Normalize correct_answer - convert letter (A, B, C, D) to actual option text
                    correct_answer = self._normalize_correct_answer(correct_answer, options)
                    
                    # Build detection reasoning with section info
                    detected_section = question_data.get('detected_section', '')
                    type_reasoning = question_data.get('type_reasoning', '')
                    
                    # Build comprehensive reasoning including section and marking scheme
                    detection_parts = []
                    if detected_section:
                        detection_parts.append(f"Section: {detected_section}")
                    if type_reasoning:
                        detection_parts.append(f"Reasoning: {type_reasoning}")
                    if marking_scheme:
                        correct_marks = marking_scheme.get('correct_marks')
                        negative_marks = marking_scheme.get('negative_marks')
                        if correct_marks or negative_marks:
                            marks_info = []
                            if correct_marks:
                                marks_info.append(f"+{correct_marks}")
                            if negative_marks:
                                marks_info.append(f"{negative_marks}")
                            detection_parts.append(f"Marks: {'/'.join(marks_info)}")
                    
                    detection_reasoning = ' | '.join(detection_parts) if detection_parts else ''
                    
                    # Create ExtractedQuestion
                    extracted_q = ExtractedQuestion.objects.create(
                        job=job,
                        question_text=q_text,
                        question_type=question_type,
                        options=options,
                        correct_answer=correct_answer,
                        solution=str(question_data.get('solution', '')),
                        explanation=str(question_data.get('explanation', '')),
                        difficulty=question_data.get('difficulty', 'medium') or 'medium',
                        confidence_score=float(question_data.get('confidence_score', 0.8) or 0.8),
                        requires_review=question_data.get('confidence_score', 0.8) < 0.7,
                        suggested_subject=final_subject,
                        suggested_section_id=suggested_section_id,
                        detection_reasoning=detection_reasoning,
                    )
                    
                    # Validate
                    is_valid, errors = extracted_q.validate()
                    
                    if not is_valid:
                        logger.warning(f"Question validation issues: {'; '.join(errors)}")
                    
                    saved_count += 1
                    
                except Exception as e:
                    logger.error(f"Failed to save question: {e}")
                    continue
        
        logger.info(f"Saved {saved_count}/{len(questions)} questions")
        return saved_count
    
    def _normalize_correct_answer(
        self,
        answer: str,
        options: List[str]
    ) -> str:
        """
        Normalize correct answer - convert letter (A, B, C, D) to actual option text
        
        Args:
            answer: The answer string (could be "A", "B", "Option A text", etc.)
            options: List of option texts
            
        Returns:
            The actual option text if answer is a letter, otherwise the original answer
        """
        if not answer or not options:
            return answer
        
        answer = answer.strip()
        
        # If answer is already one of the options, return as-is
        if answer in options:
            return answer
        
        # Check if answer is a letter (A, B, C, D, E) or letter with parentheses/period
        letter_match = None
        clean_answer = answer.upper().strip()
        
        # Handle formats: "A", "(A)", "A)", "A.", "Option A", etc.
        letter_pattern = re.match(r'^[\(\[]?([A-Ea-e])[\)\]\.]?$', clean_answer)
        if letter_pattern:
            letter_match = letter_pattern.group(1).upper()
        elif clean_answer in ['A', 'B', 'C', 'D', 'E']:
            letter_match = clean_answer
        
        if letter_match:
            # Convert letter to index (A=0, B=1, C=2, D=3, E=4)
            index = ord(letter_match) - ord('A')
            if 0 <= index < len(options):
                return options[index]
        
        # Handle multiple answers like "A, C" or "A and B" or "A,B,C"
        # Only match standalone letters (not part of words like "and")
        multi_pattern = re.findall(r'\b([A-Ea-e])\b', clean_answer)
        if len(multi_pattern) > 1:
            # Multiple correct answers - return comma-separated option texts
            selected_options = []
            seen = set()
            for letter in multi_pattern:
                letter_upper = letter.upper()
                if letter_upper not in seen:
                    seen.add(letter_upper)
                    index = ord(letter_upper) - ord('A')
                    if 0 <= index < len(options):
                        selected_options.append(options[index])
            if selected_options:
                return ', '.join(selected_options)
        
        # If we couldn't normalize, return original
        return answer
    
    def _suggest_mapping(
        self, 
        question_data: dict, 
        context: dict
    ) -> Tuple[str, Optional[int]]:
        """Suggest subject and section for a question"""
        question_type = question_data.get('question_type')
        ai_suggested_subject = question_data.get('suggested_subject', '').strip()
        
        subjects = context.get('subjects', [])
        
        # Use AI-suggested subject if valid
        suggested_subject = None
        if ai_suggested_subject:
            for subj in subjects:
                if subj.lower() == ai_suggested_subject.lower():
                    suggested_subject = subj
                    break
        
        # Fallback
        if not suggested_subject:
            suggested_subject = subjects[0] if subjects else ''
        
        # Find matching section
        suggested_section_id = None
        fallback_section_id = None
        
        for section in context.get('sections', []):
            if section['question_type'] == question_type:
                if section['subject'] == suggested_subject:
                    suggested_section_id = section['id']
                    break
                elif not fallback_section_id:
                    fallback_section_id = section['id']
        
        if not suggested_section_id and fallback_section_id:
            suggested_section_id = fallback_section_id
            for section in context.get('sections', []):
                if section['id'] == fallback_section_id:
                    suggested_subject = section['subject']
                    break
        
        return suggested_subject, suggested_section_id
    
    def _categorize_questions(
        self,
        questions: List[Dict],
        available_subjects: List[str]
    ) -> Dict:
        """
        Categorize extracted questions by subject using AI
        
        This is a SEPARATE step from extraction - questions are first extracted
        without subjects, then categorized into the pattern's available subjects.
        
        Args:
            questions: List of extracted questions (without subjects)
            available_subjects: List of subjects from the exam pattern
            
        Returns:
            {
                'questions': List of questions with subject assignments,
                'subject_counts': Dict mapping subject to question count,
                'uncategorized_count': Number of questions that couldn't be categorized
            }
        """
        try:
            # Initialize categorizer lazily
            if not self.subject_categorizer:
                self.subject_categorizer = SubjectCategorizer()
            
            # Categorize questions
            result = self.subject_categorizer.categorize_questions(
                questions,
                available_subjects,
                batch_size=20
            )
            
            logger.info(
                f"Subject categorization complete: {result['subject_counts']}, "
                f"uncategorized: {result['uncategorized_count']}"
            )
            
            return result
            
        except SubjectCategorizationError as e:
            logger.error(f"Subject categorization failed: {e}")
            # Return questions without categorization
            for q in questions:
                q['suggested_subject'] = available_subjects[0] if available_subjects else 'Uncategorized'
            return {
                'questions': questions,
                'subject_counts': {available_subjects[0] if available_subjects else 'Uncategorized': len(questions)},
                'uncategorized_count': 0
            }
    
    def get_extraction_status(self, job_id: UUID) -> Dict:
        """Get detailed extraction status"""
        try:
            job = ExtractionJob.objects.get(id=job_id)
            
            # Get question stats
            questions = job.extracted_questions.all()
            
            type_distribution = {}
            low_confidence_count = 0
            needs_review_count = 0
            
            for q in questions:
                type_distribution[q.question_type] = type_distribution.get(q.question_type, 0) + 1
                if q.confidence_score < 0.7:
                    low_confidence_count += 1
                if q.requires_review:
                    needs_review_count += 1
            
            return {
                'job_id': str(job_id),
                'status': job.status,
                'progress': job.progress_percent,
                'expected_count': job.total_questions_found,
                'extracted_count': job.questions_extracted,
                'imported_count': job.questions_imported,
                'failed_count': job.questions_failed,
                'type_distribution': type_distribution,
                'low_confidence_count': low_confidence_count,
                'needs_review_count': needs_review_count,
                'processing_time': job.processing_time_seconds,
                'error_message': job.error_message,
                'created_at': job.created_at.isoformat(),
                'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            }
            
        except ExtractionJob.DoesNotExist:
            return {'error': f'Job {job_id} not found'}
    
    def retry_failed_job(self, job_id: UUID) -> Dict:
        """Retry a failed extraction job"""
        try:
            job = ExtractionJob.objects.get(id=job_id)
            
            if job.status not in ['failed', 'partial']:
                return {'error': 'Job is not in failed/partial state'}
            
            # Clear previous extracted questions
            job.extracted_questions.all().delete()
            
            # Reset job
            job.retry_count += 1
            job.status = 'pending'
            job.error_message = ''
            job.progress_percent = 0
            job.questions_extracted = 0
            job.questions_imported = 0
            job.questions_failed = 0
            job.save()
            
            logger.info(f"Retrying extraction job {job_id} (attempt {job.retry_count})")
            
            # Process again
            return self.process_file(job_id)
            
        except ExtractionJob.DoesNotExist:
            return {'error': f'Job {job_id} not found'}


# Convenience function for Celery tasks
def process_extraction_job(job_id: str) -> Dict:
    """Process extraction job (for Celery task)"""
    pipeline = ExtractionPipelineV2()
    return pipeline.process_file(UUID(job_id))
