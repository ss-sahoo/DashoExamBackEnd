"""
ExamFlow Question Extraction Pipeline V3

A 6-stage extraction pipeline that replaces the monolithic extraction approach 
with specialized stages for reliable, high-quality question extraction.

Stages:
    1. DocumentProcessor: PDF/DOCX → Text + Images
    2. StructureAnalyzer: AI-powered document structure analysis
    3. DocumentSplitter: Split text by section boundaries
    4. QuestionExtractor: Per-chunk extraction with type-specific prompts
    5. Validator: Validation + retry loop for completeness
    6. PatternMapper: Map extracted questions to exam pattern sections

Usage:
    from questions.services.pipeline import ExtractionPipelineV3
    
    pipeline = ExtractionPipelineV3(job_id='...')
    result = pipeline.run()
"""

from .orchestrator import ExtractionPipelineV3

__all__ = ['ExtractionPipelineV3']
