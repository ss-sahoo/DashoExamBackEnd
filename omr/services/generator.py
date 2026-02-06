"""
OMR Generation Service
Django-friendly wrapper for the OMR sheet generator
"""
import os
import json
import tempfile
from typing import Dict, List, Optional, Tuple
from django.conf import settings
from django.core.files.base import ContentFile

from .generator_core import (
    generate_omr_sheet,
    generate_answer_key_sheet,
    BUBBLE_RADIUS,
    BUBBLE_VERTICAL_SPACING,
)


class OMRGeneratorService:
    """
    Service class for generating OMR sheets for exams.
    Wraps the core generator functionality for Django integration.
    """
    
    def __init__(self, exam):
        """
        Initialize OMR generator for an exam.
        
        Args:
            exam: Exam model instance
        """
        self.exam = exam
        self.questions = self._get_exam_questions()
    
    def _get_exam_questions(self) -> List[Dict]:
        """
        Extract question configuration from exam.
        Returns list of question configs for OMR generation.
        """
        questions = []
        
        # Get all question mappings for this exam
        from exams.models import ExamQuestionMapping
        mappings = ExamQuestionMapping.objects.filter(
            exam=self.exam
        ).select_related('question').order_by('order')
        
        for i, mapping in enumerate(mappings, start=1):
            q = mapping.question
            q_config = {
                'number': i,
                'type': self._map_question_type(q.question_type),
                'marks': float(mapping.marks),
                'negative_marks': float(mapping.negative_marks),
            }
            
            # For MCQ questions, determine number of options
            if q.question_type in ['single', 'multiple']:
                options_count = len(q.options) if q.options else 4
                q_config['options'] = [chr(65 + j) for j in range(options_count)]  # ['A', 'B', 'C', 'D']
            
            # For integer questions  
            if q.question_type in ['numerical', 'integer']:
                q_config['digits'] = 4  # Default 4 digit integer
            
            questions.append(q_config)
        
        return questions
    
    def _map_question_type(self, django_type: str) -> str:
        """Map Django question type to OMR generator type"""
        type_mapping = {
            'single': 'mcq',
            'multiple': 'mcq_multi',
            'numerical': 'integer',
            'integer': 'integer',
            'true_false': 'mcq',
            'fill_blank': 'integer',
        }
        return type_mapping.get(django_type, 'mcq')
    
    def _build_candidate_fields(self, custom_fields: Optional[List[Dict]] = None) -> List[Dict]:
        """
        Build candidate identification fields for OMR header.
        
        Default fields: Roll Number (10 digits), Set (A-D)
        """
        if custom_fields:
            return custom_fields
        
        return [
            {'name': 'Roll No', 'type': 'digits', 'digits': 10},
            {'name': 'Set', 'type': 'options-only', 'options': ['A', 'B', 'C', 'D']},
        ]
    
    def _build_exam_config(self, candidate_fields: Optional[List[Dict]] = None) -> Dict:
        """
        Build full exam configuration for the OMR generator.
        """
        fields = self._build_candidate_fields(candidate_fields)
        
        # Group questions by type
        mcq_questions = []
        integer_questions = []
        
        for q in self.questions:
            if q['type'] in ['mcq', 'mcq_multi']:
                mcq_questions.append({
                    'number': q['number'],
                    'options': q.get('options', ['A', 'B', 'C', 'D']),
                })
            else:
                integer_questions.append({
                    'number': q['number'],
                    'type': 'digits',
                    'digits': q.get('digits', 4),
                })
        
        # Build sections
        sections = []
        question_groups = []
        
        if mcq_questions:
            question_groups.append({
                'type': 'mcq',
                'questions': mcq_questions,
            })
        
        if integer_questions:
            question_groups.append({
                'type': 'integer',
                'questions': integer_questions,
            })
        
        if question_groups:
            sections.append({
                'name': self.exam.title,
                'question_groups': question_groups,
            })
        else:
            # Default section with 30 MCQ questions
            sections.append({
                'name': self.exam.title,
                'question_groups': [{
                    'type': 'mcq',
                    'questions': [
                        {'number': i, 'options': ['A', 'B', 'C', 'D']}
                        for i in range(1, 31)
                    ]
                }]
            })
        
        return {
            'candidate_fields': fields,
            'sections': sections,
        }
    
    def generate(
        self,
        candidate_fields: Optional[List[Dict]] = None,
        title: Optional[str] = None,
    ) -> Tuple[str, Dict]:
        """
        Generate OMR sheet for the exam.
        
        Args:
            candidate_fields: Custom candidate identification fields
            title: Custom title for the OMR sheet
        
        Returns:
            Tuple of (pdf_path, metadata_dict)
        """
        # Build configuration
        exam_config = self._build_exam_config(candidate_fields)
        
        # Create temporary directory for output
        output_dir = tempfile.mkdtemp(prefix='omr_')
        pdf_path = os.path.join(output_dir, 'omr_sheet.pdf')
        metadata_path = os.path.join(output_dir, 'omr_layout.json')
        
        # Generate OMR sheet
        generate_omr_sheet(
            exam_config=exam_config,
            output_pdf=pdf_path,
            output_metadata=metadata_path,
            sheet_id=str(self.exam.id),
        )
        
        # Load metadata
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        
        return pdf_path, metadata
    
    def generate_and_save(
        self,
        omr_sheet_model,
        candidate_fields: Optional[List[Dict]] = None,
        title: Optional[str] = None,
    ) -> None:
        """
        Generate OMR sheet and save to OMRSheet model instance.
        
        Args:
            omr_sheet_model: OMRSheet model instance to save to
            candidate_fields: Custom candidate identification fields
            title: Custom title for the OMR sheet
        """
        try:
            omr_sheet_model.status = 'generating'
            omr_sheet_model.save(update_fields=['status'])
            
            # Generate the OMR sheet
            pdf_path, metadata = self.generate(candidate_fields, title)
            metadata_path = pdf_path.replace('omr_sheet.pdf', 'omr_layout.json')
            
            # Save PDF to model
            with open(pdf_path, 'rb') as f:
                pdf_content = f.read()
            
            filename = f"omr_{self.exam.id}_{omr_sheet_model.sheet_id}.pdf"
            omr_sheet_model.pdf_file.save(filename, ContentFile(pdf_content))
            
            # Save metadata
            omr_sheet_model.metadata = metadata
            omr_sheet_model.candidate_fields = candidate_fields or self._build_candidate_fields()
            omr_sheet_model.question_config = self._build_exam_config(candidate_fields)
            omr_sheet_model.status = 'generated'
            omr_sheet_model.generation_error = None
            omr_sheet_model.save()
            
            # Cleanup temp files
            try:
                os.remove(pdf_path)
                os.remove(metadata_path)
            except:
                pass
            
        except Exception as e:
            omr_sheet_model.status = 'failed'
            omr_sheet_model.generation_error = str(e)
            omr_sheet_model.save(update_fields=['status', 'generation_error'])
            raise
