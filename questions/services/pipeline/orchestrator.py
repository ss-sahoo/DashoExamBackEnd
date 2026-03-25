"""
Pipeline Orchestrator: Ties all 6 stages together.

ExtractionPipelineV3 runs the complete flow:
  Stage 1: DocumentProcessor  → file → text + metadata
  Stage 2: StructureAnalyzer  → text → blueprint
  Stage 3: DocumentSplitter   → text + blueprint → tagged chunks
  Stage 4: QuestionExtractor  → chunks → raw questions
  Stage 5: QuestionValidator   → raw → validated + gap-filled questions
  Stage 6: PatternMapper      → validated → DB records (ExtractedQuestion)
"""
import logging
import time
from typing import Dict, Optional, Callable
from django.utils import timezone

logger = logging.getLogger('extraction')


class PipelineError(Exception):
    """Raised when the pipeline encounters a fatal error"""
    pass


class ExtractionPipelineV3:
    """
    The V3 Extraction Pipeline orchestrator.
    
    Coordinates the 6 stages and handles:
    - Progress reporting back to ExtractionJob
    - Error handling and partial completion
    - Timing and telemetry
    
    Usage:
        pipeline = ExtractionPipelineV3(job_id='...')
        result = pipeline.run()
    """
    
    def __init__(self, job_id: str):
        self.job_id = job_id
        self._job = None
        self._pattern = None
        
        # Lazy-loaded stage instances
        self._document_processor = None
        self._structure_analyzer = None
        self._document_splitter = None
        self._question_extractor = None
        self._validator = None
        self._pattern_mapper = None
    
    @property
    def job(self):
        """Lazy-load ExtractionJob from DB"""
        if self._job is None:
            from questions.models import ExtractionJob
            try:
                self._job = ExtractionJob.objects.get(id=self.job_id)
            except ExtractionJob.DoesNotExist:
                raise PipelineError(f"ExtractionJob {self.job_id} not found")
        return self._job
    
    @property
    def pattern(self):
        """Get pattern from job"""
        if self._pattern is None:
            self._pattern = self.job.pattern
        return self._pattern
    
    # Stage lazy loaders
    @property
    def document_processor(self):
        if self._document_processor is None:
            from .document_processor import DocumentProcessor
            self._document_processor = DocumentProcessor()
        return self._document_processor
    
    @property
    def structure_analyzer(self):
        if self._structure_analyzer is None:
            from .structure_analyzer import StructureAnalyzer
            self._structure_analyzer = StructureAnalyzer()
        return self._structure_analyzer
    
    @property
    def document_splitter(self):
        if self._document_splitter is None:
            from .document_splitter import DocumentSplitter
            self._document_splitter = DocumentSplitter()
        return self._document_splitter
    
    @property
    def question_extractor(self):
        if self._question_extractor is None:
            from .question_extractor import QuestionExtractor
            self._question_extractor = QuestionExtractor()
        return self._question_extractor
    
    @property
    def validator(self):
        if self._validator is None:
            from .validator import QuestionValidator
            self._validator = QuestionValidator()
        return self._validator
    
    @property
    def pattern_mapper(self):
        if self._pattern_mapper is None:
            from .pattern_mapper import PatternMapper
            self._pattern_mapper = PatternMapper()
        return self._pattern_mapper
    
    def _update_progress(self, percent: int, message: str = ''):
        """Update job progress in the database"""
        try:
            self.job.progress_percent = min(100, max(0, percent))
            self.job.save(update_fields=['progress_percent'])
            if message:
                logger.info(f"[Pipeline] {percent}% — {message}")
        except Exception:
            pass
    
    def run(
        self,
        progress_callback: Optional[Callable] = None,
        image_path: Optional[str] = None,
    ) -> Dict:
        """
        Run the complete 6-stage extraction pipeline.
        
        Args:
            progress_callback: Optional fn(percent, message) 
            image_path: Optional image for Vision API
            
        Returns:
            {
                'success': bool,
                'status': 'completed' | 'partial' | 'failed',
                'questions_extracted': int,
                'questions_saved': int,
                'validation_report': {...},
                'timing': {
                    'total': float,
                    'stage_1': float,
                    ...
                },
                'error': str | None,
            }
        """
        pipeline_start = time.time()
        timings = {}
        
        # Mark job as processing
        self.job.status = 'processing'
        self.job.save(update_fields=['status'])
        
        def update(pct, msg=''):
            self._update_progress(pct, msg)
            if progress_callback:
                progress_callback(pct, msg)
        
        try:
            # ─── STAGE 1: Document Processing ───
            update(5, "Processing document...")
            stage_start = time.time()
            
            doc_result = self.document_processor.process(
                file_path=self.job.file_path,
                file_type=self.job.file_type,
            )
            
            timings['stage_1_document_processing'] = time.time() - stage_start
            full_text = doc_result['full_text']
            
            update(10, f"Document processed: {doc_result['metadata']['text_length']} chars")
            
            # ─── STAGE 2: Structure Analysis ───
            update(12, "Analyzing document structure...")
            stage_start = time.time()
            
            structure_result = self.structure_analyzer.analyze(
                full_text=full_text,
                pattern=self.pattern,
                document_metadata=doc_result['metadata'],
            )
            
            timings['stage_2_structure_analysis'] = time.time() - stage_start
            blueprint = structure_result['blueprint']
            
            if not structure_result['can_proceed']:
                logger.warning(
                    "[Pipeline] Structure doesn't match pattern well, "
                    "proceeding anyway with available data."
                )
            
            update(
                20,
                f"Structure analyzed: {blueprint.total_questions} questions "
                f"across {len(blueprint.subjects)} subjects. "
                f"Match score: {structure_result['validation'].get('subject_match_score', 0):.0%}"
            )
            
            # ─── STAGE 3: Document Splitting ───
            update(22, "Splitting document into sections...")
            stage_start = time.time()
            
            chunks = self.document_splitter.split(full_text, blueprint)
            
            timings['stage_3_document_splitting'] = time.time() - stage_start
            
            update(25, f"Document split into {len(chunks)} extraction chunks")
            
            # ─── STAGE 4: Question Extraction ───
            update(28, "Extracting questions...")
            stage_start = time.time()
            
            raw_questions = self.question_extractor.extract_all(
                chunks=chunks,
                image_path=image_path,
                progress_callback=update,
            )
            
            timings['stage_4_question_extraction'] = time.time() - stage_start
            
            update(80, f"Extracted {len(raw_questions)} raw questions")
            
            # ─── STAGE 5: Validation ───
            update(82, "Validating and filling gaps...")
            stage_start = time.time()
            
            validation_result = self.validator.validate_and_fix(
                questions=raw_questions,
                chunks=chunks,
                blueprint=blueprint,
            )
            
            timings['stage_5_validation'] = time.time() - stage_start
            validated_questions = validation_result['questions']
            validation_report = validation_result['validation_report']
            
            update(
                90,
                f"Validation complete: {len(validated_questions)} questions "
                f"({validation_report['completeness_score']:.0%} coverage)"
            )
            
            # ─── STAGE 6: Pattern Mapping ───
            update(92, "Mapping to exam pattern...")
            stage_start = time.time()
            
            mapping_result = self.pattern_mapper.map_to_pattern(
                questions=validated_questions,
                pattern=self.pattern,
                job=self.job,
            )
            
            timings['stage_6_pattern_mapping'] = time.time() - stage_start
            
            update(
                95,
                f"Mapped {mapping_result['mapped_count']} questions to pattern, "
                f"{mapping_result['unmapped_count']} unmapped"
            )
            
            # ─── Finalize ───
            total_time = time.time() - pipeline_start
            timings['total'] = total_time
            
            # Update job with final results
            saved = mapping_result['saved_count']
            self.job.questions_extracted = saved
            self.job.total_questions_found = len(validated_questions)
            self.job.questions_imported = 0  # Not yet imported, just extracted
            self.job.processing_time_seconds = total_time
            
            if saved > 0:
                if validation_report['completeness_score'] >= 0.9:
                    self.job.mark_completed()
                    status = 'completed'
                else:
                    self.job.mark_partial()
                    status = 'partial'
            else:
                self.job.mark_failed("No questions could be extracted")
                status = 'failed'
            
            update(100, f"Pipeline complete: {saved} questions extracted in {total_time:.1f}s")
            
            return {
                'success': status != 'failed',
                'status': status,
                'questions_extracted': saved,
                'questions_saved': saved,
                'validation_report': validation_report,
                'per_subject': validation_result.get('per_subject', {}),
                'mapping_result': {
                    'mapped': mapping_result['mapped_count'],
                    'unmapped': mapping_result['unmapped_count'],
                    'issues': mapping_result['mapping_issues'],
                },
                'timing': timings,
                'error': None,
            }
            
        except Exception as e:
            total_time = time.time() - pipeline_start
            error_msg = str(e)
            
            logger.error(f"[Pipeline] Fatal error after {total_time:.1f}s: {error_msg}")
            
            self.job.processing_time_seconds = total_time
            self.job.mark_failed(error_msg)
            
            return {
                'success': False,
                'status': 'failed',
                'questions_extracted': 0,
                'questions_saved': 0,
                'validation_report': {},
                'timing': {**timings, 'total': total_time},
                'error': error_msg,
            }
