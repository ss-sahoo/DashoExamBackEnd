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
        
        # Get all questions assigned to this exam
        from questions.models import ExamQuestion
        mappings = ExamQuestion.objects.filter(
            exam=self.exam
        ).select_related('question').order_by('question_number')
        
        if mappings.exists():
            # First, group by the determined section name
            raw_questions = []
            for mapping in mappings:
                q = mapping.question
                
                # Combine subject and section name for display
                subject_name = q.subject or 'General'
                section_name = mapping.section_name
                
                if section_name and section_name.lower() != subject_name.lower():
                    if len(section_name) <= 2:
                        display_name = f"{subject_name} - Section {section_name}"
                    else:
                        display_name = f"{subject_name} - {section_name}"
                else:
                    display_name = subject_name

                q_data = {
                    'original_number': mapping.question_number,
                    'type': self._map_question_type(q.question_type),
                    'marks': float(mapping.marks),
                    'negative_marks': float(mapping.negative_marks),
                    'section': display_name,
                    'question_obj': q
                }
                
                if q.question_type in ['single', 'multiple', 'single_mcq', 'multiple_mcq', 'true_false']:
                    options_count = len(q.options) if hasattr(q, 'options') and q.options else 4
                    q_data['options'] = [chr(65 + j) for j in range(options_count)]
                
                if q.question_type in ['numerical', 'integer', 'fill_blank']:
                    q_data['digits'] = 4
                
                raw_questions.append(q_data)

            # Sort by original number first to maintain absolute exam sequence across subjects
            # This ensures Physics (1-20) always comes before Chemistry (21-40) regardless of section name
            raw_questions.sort(key=lambda x: (x['original_number'], x['section']))
            
            # Assign NEW sequential numbers for OMR
            for i, q_data in enumerate(raw_questions, start=1):
                q_config = {
                    'number': i, # Sequential number for OMR 1, 2, 3...
                    'original_db_number': q_data['original_number'],
                    'type': q_data['type'],
                    'marks': q_data['marks'],
                    'negative_marks': q_data['negative_marks'],
                    'section': q_data['section'],
                }
                if 'options' in q_data:
                    q_config['options'] = q_data['options']
                if 'digits' in q_data:
                    q_config['digits'] = q_data['digits']
                
                questions.append(q_config)


        elif self.exam.pattern:
            # Fallback to pattern sections to determine question counts and types
            from patterns.models import PatternSection
            sections = PatternSection.objects.filter(pattern=self.exam.pattern).order_by('start_question')
            global_idx = 1
            for section in sections:
                q_type = self._map_question_type(section.question_type)
                # Combine subject and section name for display
                subject_name = section.subject or 'General'
                section_name = section.name
                
                if section_name and section_name.lower() != subject_name.lower():
                    if len(section_name) <= 2:
                        display_name = f"{subject_name} - Section {section_name}"
                    else:
                        display_name = f"{subject_name} - {section_name}"
                else:
                    display_name = subject_name

                for i in range(section.start_question, section.end_question + 1):
                    q_config = {
                        'number': global_idx,
                        'pattern_original_number': i,
                        'type': q_type,
                        'marks': float(section.marks_per_question),
                        'negative_marks': float(section.negative_marking),
                        'section': display_name,
                    }

                    if 'mcq' in q_type:
                        q_config['options'] = ['A', 'B', 'C', 'D']
                    elif q_type == 'integer':
                        q_config['digits'] = 4
                        
                    questions.append(q_config)
                    global_idx += 1

        
        return questions
    
    def _map_question_type(self, django_type: str) -> str:
        """Map Django question type to OMR generator type"""
        type_mapping = {
            'single': 'mcq',
            'single_mcq': 'mcq',
            'multiple': 'mcq_multi',
            'multiple_mcq': 'mcq_multi',
            'numerical': 'integer',
            'integer': 'integer',
            'true_false': 'mcq',
            'fill_blank': 'integer',
            'subjective': 'subjective',
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
        
        # Group questions by section
        section_groups = {}
        for q in self.questions:
            s_name = q.get('section', 'General')
            if s_name not in section_groups:
                section_groups[s_name] = []
            section_groups[s_name].append(q)
            
        # Build sections list
        sections = []
        for s_name, s_questions in section_groups.items():
            mcq_group = []
            integer_group = []
            
            for q in s_questions:
                if q['type'] in ['mcq', 'mcq_multi']:
                    mcq_group.append({
                        'number': q['number'],
                        'options': q.get('options', ['A', 'B', 'C', 'D']),
                    })
                else:
                    integer_group.append({
                        'number': q['number'],
                        'type': 'digits',
                        'digits': q.get('digits', 4),
                    })
            
            groups = []
            if mcq_group:
                groups.append({'type': 'mcq', 'questions': mcq_group})
            if integer_group:
                groups.append({'type': 'integer', 'questions': integer_group})
                
            if groups:
                sections.append({
                    'name': s_name,
                    'question_groups': groups
                })
        
        # Sort sections by their first question number
        sections.sort(key=lambda s: min(q['number'] for g in s['question_groups'] for q in g['questions']))

        if not sections:
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
