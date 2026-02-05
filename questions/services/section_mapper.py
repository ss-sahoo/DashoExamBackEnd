"""
Section Mapper Service
Maps extracted questions to pattern sections based on question type and subject.
Provides import preview with remaining counts and confirmation flow.
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from django.db.models import Count

from patterns.models import ExamPattern, PatternSection
from questions.models import Question

logger = logging.getLogger('extraction')


@dataclass
class SectionMapping:
    """Mapping of extracted questions to a pattern section"""
    pattern_section_id: int
    pattern_section_name: str
    subject: str
    question_type: str
    required_count: int
    current_count: int  # Already in exam
    remaining_capacity: int
    extracted_count: int
    will_import_count: int
    overflow_count: int
    questions_to_import: List[Dict]
    questions_overflow: List[Dict]
    status: str  # 'ready', 'overflow', 'shortage', 'complete'
    
    def to_dict(self):
        return asdict(self)


@dataclass
class ImportPreview:
    """Preview of what will be imported"""
    exam_id: int
    pattern_id: int
    subject: str
    total_extracted: int
    total_will_import: int
    total_overflow: int
    total_remaining_after_import: int
    section_mappings: List[SectionMapping]
    warnings: List[str]
    recommendations: List[str]
    can_proceed: bool
    requires_selection: bool  # True if user needs to select which questions to import
    
    def to_dict(self):
        result = asdict(self)
        result['section_mappings'] = [m.to_dict() for m in self.section_mappings]
        return result


class SectionMapper:
    """
    Maps extracted questions to pattern sections.
    Calculates remaining capacity and provides import preview.
    """
    
    def __init__(self):
        pass
    
    def map_questions_to_sections(
        self,
        exam_id: int,
        pattern_id: int,
        subject: str,
        extracted_sections: List[Dict],
        import_target: Optional[Dict] = None
    ) -> ImportPreview:
        """
        Map extracted questions to pattern sections.
        
        Args:
            exam_id: Target exam ID
            pattern_id: Pattern ID
            subject: Subject name
            extracted_sections: List of extracted section results
                [
                    {
                        'section_name': 'Section A',
                        'section_type': 'single_mcq',
                        'questions': [...],
                        'total_extracted': 20
                    }
                ]
            import_target: Optional import target selection
                {
                    'mode': 'auto' | 'subject' | 'section',
                    'target_subject': str,
                    'target_section_id': int
                }
        
        Returns:
            ImportPreview with mapping details
        """
        logger.info(f"Mapping questions for subject {subject} to pattern {pattern_id}")
        
        # Handle targeted section import
        if import_target and import_target.get('mode') == 'section':
            return self._map_to_specific_section(
                exam_id, pattern_id, subject, extracted_sections, import_target
            )
        
        # Get pattern sections for this subject
        pattern_sections = PatternSection.objects.filter(
            pattern_id=pattern_id,
            subject__iexact=subject
        ).order_by('order', 'id')
        
        if not pattern_sections.exists():
            logger.warning(f"No pattern sections found for subject {subject}")
            return self._create_empty_preview(exam_id, pattern_id, subject, extracted_sections)
        
        # Get current question counts per section
        current_counts = self._get_current_counts(exam_id, pattern_sections)
        
        # Map extracted questions to pattern sections
        section_mappings = []
        total_will_import = 0
        total_overflow = 0
        warnings = []
        recommendations = []
        
        # Group extracted questions by type
        extracted_by_type = self._group_by_type(extracted_sections)
        
        # Get all extracted questions (for fallback)
        all_extracted_questions = []
        for questions in extracted_by_type.values():
            all_extracted_questions.extend(questions)
        
        # FIXED: Calculate total_extracted ONCE from unique questions only
        # This prevents double-counting when questions are assigned to multiple sections
        total_extracted = len(all_extracted_questions)
        
        logger.info(f"Extracted types: {list(extracted_by_type.keys())}")
        logger.info(f"Total extracted (unique): {total_extracted}")
        
        # Track which questions have been assigned
        assigned_question_ids = set()
        
        for pattern_section in pattern_sections:
            section_type = pattern_section.question_type
            required = pattern_section.total_questions
            current = current_counts.get(pattern_section.id, 0)
            remaining_capacity = max(0, required - current)
            
            # Get compatible types for this section
            compatible_types = self._get_compatible_types(section_type)
            
            # Get extracted questions for these types
            extracted_questions = []
            for t in compatible_types:
                extracted_questions.extend(extracted_by_type.get(t, []))
            
            # Filter out already assigned questions
            extracted_questions = [q for q in extracted_questions if id(q) not in assigned_question_ids]
                
            # Track if we're using fallback (for correct counting)
            using_fallback = False
            
            # If no questions of this type, try to use unassigned questions
            if not extracted_questions and remaining_capacity > 0:
                logger.warning(f"No questions of type '{section_type}' found, using available questions")
                using_fallback = True
                # Get unassigned questions
                extracted_questions = [
                    q for q in all_extracted_questions 
                    if id(q) not in assigned_question_ids
                ][:remaining_capacity]
            extracted_count = len(extracted_questions)
            
            # Determine how many to import
            will_import = min(extracted_count, remaining_capacity)
            overflow = max(0, extracted_count - remaining_capacity)
            
            total_will_import += will_import
            total_overflow += overflow
            
            # Split questions
            questions_to_import = extracted_questions[:will_import]
            questions_overflow = extracted_questions[will_import:]
            
            # Mark questions as assigned
            for q in questions_to_import:
                assigned_question_ids.add(id(q))
            
            # Determine status
            if current >= required:
                status = 'complete'
            elif will_import == 0 and extracted_count == 0:
                status = 'shortage'
            elif overflow > 0:
                status = 'overflow'
            elif will_import < remaining_capacity:
                status = 'shortage'
            else:
                status = 'ready'
            
            mapping = SectionMapping(
                pattern_section_id=pattern_section.id,
                pattern_section_name=pattern_section.name,
                subject=subject,
                question_type=section_type,
                required_count=required,
                current_count=current,
                remaining_capacity=remaining_capacity,
                extracted_count=extracted_count,
                will_import_count=will_import,
                overflow_count=overflow,
                questions_to_import=questions_to_import,
                questions_overflow=questions_overflow,
                status=status
            )
            section_mappings.append(mapping)
            
            # Generate warnings
            if status == 'overflow':
                warnings.append(
                    f"{pattern_section.name}: {overflow} extra questions won't be imported "
                    f"(capacity: {remaining_capacity}, extracted: {extracted_count})"
                )
            elif status == 'shortage':
                shortage = remaining_capacity - will_import
                warnings.append(
                    f"{pattern_section.name}: {shortage} more questions needed "
                    f"(required: {required}, will have: {current + will_import})"
                )
        
        # Calculate total remaining after import
        total_required = sum(ps.total_questions for ps in pattern_sections)
        total_current = sum(current_counts.values())
        total_remaining_after = total_required - (total_current + total_will_import)
        
        # Generate recommendations
        if total_overflow > 0:
            recommendations.append(
                f"You have {total_overflow} extra questions. "
                "You can select which ones to import or skip them."
            )
        if total_remaining_after > 0:
            recommendations.append(
                f"After import, you'll still need {total_remaining_after} more questions."
            )
        if total_will_import == total_extracted and total_remaining_after == 0:
            recommendations.append("Perfect match! All questions will be imported.")
        
        # Determine if user needs to select questions
        requires_selection = total_overflow > 0
        can_proceed = total_will_import > 0
        
        return ImportPreview(
            exam_id=exam_id,
            pattern_id=pattern_id,
            subject=subject,
            total_extracted=total_extracted,
            total_will_import=total_will_import,
            total_overflow=total_overflow,
            total_remaining_after_import=total_remaining_after,
            section_mappings=section_mappings,
            warnings=warnings,
            recommendations=recommendations,
            can_proceed=can_proceed,
            requires_selection=requires_selection
        )
    
    def _get_current_counts(
        self,
        exam_id: int,
        pattern_sections
    ) -> Dict[int, int]:
        """Get current question counts per pattern section"""
        counts = {}
        
        for section in pattern_sections:
            count = Question.objects.filter(
                exam_id=exam_id,
                pattern_section_id=section.id,
                is_active=True
            ).count()
            counts[section.id] = count
        
        return counts
    
    def _group_by_type(self, extracted_sections: List[Dict]) -> Dict[str, List[Dict]]:
        """Group extracted questions by their individual question_type"""
        by_type = {}
        
        for section in extracted_sections:
            section_type = section.get('section_type', 'single_mcq')
            questions = section.get('questions', [])
            
            # Add section info to each question and group by individual question_type
            for q in questions:
                q['source_section'] = section.get('section_name', 'Unknown')
                
                # Use individual question's question_type, fallback to section_type
                q_type = q.get('question_type', section_type)
                
                if q_type not in by_type:
                    by_type[q_type] = []
                by_type[q_type].append(q)
        
        logger.info(f"Grouped questions by type: {{{', '.join(f'{k}: {len(v)}' for k, v in by_type.items())}}}")
        return by_type

    def _get_compatible_types(self, section_type: str) -> List[str]:
        """Get list of question types compatible with a section type"""
        # Mapping of section type to list of compatible question types
        compatibility = {
            'subjective': ['subjective', 'single_mcq', 'multipart', 'internal_choice', 'mixed', 'numerical'],
            'single_mcq': ['single_mcq', 'subjective'],
            'multiple_mcq': ['multiple_mcq', 'single_mcq'],
            'numerical': ['numerical', 'subjective'],
            'true_false': ['true_false'],
            'fill_blank': ['fill_blank'],
            'multipart': ['multipart', 'mixed', 'subjective', 'single_mcq'],
            'mixed': ['mixed', 'multipart', 'internal_choice', 'subjective', 'single_mcq'],
            'internal_choice': ['internal_choice', 'mixed', 'subjective', 'single_mcq'],
        }
        
        # Always include the type itself
        types = compatibility.get(section_type, [section_type])
        if section_type not in types:
            types.append(section_type)
        return types
    
    def _create_empty_preview(
        self,
        exam_id: int,
        pattern_id: int,
        subject: str,
        extracted_sections: List[Dict]
    ) -> ImportPreview:
        """Create empty preview when no pattern sections found"""
        total_extracted = sum(s.get('total_extracted', 0) for s in extracted_sections)
        
        return ImportPreview(
            exam_id=exam_id,
            pattern_id=pattern_id,
            subject=subject,
            total_extracted=total_extracted,
            total_will_import=0,
            total_overflow=total_extracted,
            total_remaining_after_import=0,
            section_mappings=[],
            warnings=[f"No pattern sections found for subject '{subject}'"],
            recommendations=["Please check the pattern configuration"],
            can_proceed=False,
            requires_selection=False
        )
    
    def _map_to_specific_section(
        self,
        exam_id: int,
        pattern_id: int,
        subject: str,
        extracted_sections: List[Dict],
        import_target: Dict
    ) -> ImportPreview:
        """
        Map all questions to a specific section (targeted import).
        Only imports questions matching the section's question_type.
        """
        target_section_id = import_target.get('target_section_id')
        
        if not target_section_id:
            return self._create_empty_preview(exam_id, pattern_id, subject, extracted_sections)
        
        try:
            pattern_section = PatternSection.objects.get(id=target_section_id)
        except PatternSection.DoesNotExist:
            return self._create_empty_preview(exam_id, pattern_id, subject, extracted_sections)
        
        # Get current count for this section
        current_count = Question.objects.filter(
            exam_id=exam_id,
            pattern_section_id=target_section_id,
            is_active=True
        ).count()
        
        required = pattern_section.total_questions
        remaining_capacity = max(0, required - current_count)
        target_type = pattern_section.question_type
        
        # Collect all questions and filter by matching type
        all_questions = []
        for section in extracted_sections:
            for q in section.get('questions', []):
                q['source_section'] = section.get('section_name', 'Unknown')
                all_questions.append(q)
        
        # Filter questions by matching question_type
        matching_questions = [
            q for q in all_questions
            if q.get('question_type', 'single_mcq') == target_type
        ]
        
        total_extracted = len(all_questions)
        matching_count = len(matching_questions)
        
        # Determine how many to import
        will_import = min(matching_count, remaining_capacity)
        overflow = max(0, matching_count - remaining_capacity)
        skipped_type_mismatch = total_extracted - matching_count
        
        questions_to_import = matching_questions[:will_import]
        questions_overflow = matching_questions[will_import:]
        
        # Determine status
        if current_count >= required:
            status = 'complete'
        elif will_import == 0 and matching_count == 0:
            status = 'shortage'
        elif overflow > 0:
            status = 'overflow'
        else:
            status = 'ready'
        
        mapping = SectionMapping(
            pattern_section_id=pattern_section.id,
            pattern_section_name=pattern_section.name,
            subject=subject,
            question_type=target_type,
            required_count=required,
            current_count=current_count,
            remaining_capacity=remaining_capacity,
            extracted_count=matching_count,
            will_import_count=will_import,
            overflow_count=overflow,
            questions_to_import=questions_to_import,
            questions_overflow=questions_overflow,
            status=status
        )
        
        # Build warnings
        warnings = []
        if skipped_type_mismatch > 0:
            warnings.append(
                f"{skipped_type_mismatch} questions skipped (type mismatch - section requires '{target_type}')"
            )
        if overflow > 0:
            warnings.append(
                f"{overflow} extra questions won't be imported (capacity: {remaining_capacity})"
            )
        if remaining_capacity == 0:
            warnings.append(f"Section is already full ({current_count}/{required} questions)")
        
        # Build recommendations
        recommendations = []
        if will_import > 0:
            recommendations.append(f"{will_import} questions will be imported to {pattern_section.name}")
        if skipped_type_mismatch > 0:
            recommendations.append(
                f"Only '{target_type}' questions are imported. Other types are skipped."
            )
        
        return ImportPreview(
            exam_id=exam_id,
            pattern_id=pattern_id,
            subject=subject,
            total_extracted=total_extracted,
            total_will_import=will_import,
            total_overflow=overflow + skipped_type_mismatch,
            total_remaining_after_import=max(0, required - current_count - will_import),
            section_mappings=[mapping],
            warnings=warnings,
            recommendations=recommendations,
            can_proceed=will_import > 0,
            requires_selection=overflow > 0
        )
    
    def get_full_import_preview(
        self,
        exam_id: int,
        pattern_id: int,
        all_subjects_data: Dict[str, List[Dict]]
    ) -> Dict:
        """
        Get full import preview for all subjects.
        
        Args:
            exam_id: Target exam ID
            pattern_id: Pattern ID
            all_subjects_data: Dict mapping subject to extracted sections
                {
                    'Physics': [section_results],
                    'Chemistry': [section_results],
                    ...
                }
        
        Returns:
            Full import preview with all subjects
        """
        previews = {}
        total_extracted = 0
        total_will_import = 0
        total_overflow = 0
        total_remaining = 0
        all_warnings = []
        all_recommendations = []
        
        for subject, sections in all_subjects_data.items():
            preview = self.map_questions_to_sections(
                exam_id, pattern_id, subject, sections
            )
            previews[subject] = preview.to_dict()
            
            total_extracted += preview.total_extracted
            total_will_import += preview.total_will_import
            total_overflow += preview.total_overflow
            total_remaining += preview.total_remaining_after_import
            all_warnings.extend(preview.warnings)
            all_recommendations.extend(preview.recommendations)
        
        return {
            'exam_id': exam_id,
            'pattern_id': pattern_id,
            'subjects': previews,
            'summary': {
                'total_extracted': total_extracted,
                'total_will_import': total_will_import,
                'total_overflow': total_overflow,
                'total_remaining_after_import': total_remaining,
                'subjects_count': len(previews)
            },
            'warnings': all_warnings,
            'recommendations': all_recommendations,
            'can_proceed': total_will_import > 0,
            'requires_selection': total_overflow > 0
        }
    
    def prepare_import_mappings(
        self,
        import_preview: ImportPreview,
        selected_question_ids: Optional[List[int]] = None,
        import_target: Optional[Dict] = None
    ) -> List[Dict]:
        """
        Prepare question mappings for bulk import.
        
        Args:
            import_preview: Import preview result
            selected_question_ids: Optional list of question IDs to import
                                   (for overflow selection)
            import_target: Optional import target selection
        
        Returns:
            List of mappings ready for BulkImportService
        """
        mappings = []
        
        for section_mapping in import_preview.section_mappings:
            questions = section_mapping.questions_to_import
            
            # If user selected specific questions, filter
            if selected_question_ids is not None:
                questions = [
                    q for q in questions
                    if q.get('id') in selected_question_ids or 
                       q.get('question_number') in selected_question_ids
                ]
            
            for q in questions:
                mappings.append({
                    'extracted_question_id': q.get('id'),
                    'question_data': q,
                    'subject': section_mapping.subject,
                    'section_id': section_mapping.pattern_section_id,
                    'section_name': section_mapping.pattern_section_name,
                    'question_type': section_mapping.question_type
                })
        
        return mappings


class ImportConfirmationFlow:
    """
    Manages the confirmation flow for importing questions.
    Shows remaining counts and allows user to confirm at each step.
    """
    
    def __init__(self):
        self.mapper = SectionMapper()
    
    def get_confirmation_data(
        self,
        exam_id: int,
        pattern_id: int,
        subject: str,
        extracted_sections: List[Dict],
        import_target: Optional[Dict] = None
    ) -> Dict:
        """
        Get data for confirmation dialog.
        
        Returns:
            {
                'preview': ImportPreview,
                'confirmation_message': str,
                'options': [
                    {'action': 'import_all', 'label': 'Import All (X questions)'},
                    {'action': 'select', 'label': 'Select Questions to Import'},
                    {'action': 'skip', 'label': 'Skip This Subject'}
                ]
            }
        """
        preview = self.mapper.map_questions_to_sections(
            exam_id, pattern_id, subject, extracted_sections, import_target
        )
        
        # Build confirmation message
        if preview.total_overflow > 0:
            message = (
                f"Found {preview.total_extracted} questions for {subject}. "
                f"Pattern can accept {preview.total_will_import} questions. "
                f"{preview.total_overflow} questions will be skipped unless you select them."
            )
        elif preview.total_remaining_after_import > 0:
            message = (
                f"Found {preview.total_extracted} questions for {subject}. "
                f"All will be imported. "
                f"You'll still need {preview.total_remaining_after_import} more questions."
            )
        else:
            message = (
                f"Found {preview.total_extracted} questions for {subject}. "
                f"All questions will be imported. Pattern will be complete!"
            )
        
        # Build options
        options = []
        
        if preview.can_proceed:
            options.append({
                'action': 'import_all',
                'label': f'Import All ({preview.total_will_import} questions)',
                'description': 'Import all questions that fit in the pattern'
            })
        
        if preview.requires_selection:
            options.append({
                'action': 'select',
                'label': 'Select Questions to Import',
                'description': 'Choose which questions to import from overflow'
            })
        
        options.append({
            'action': 'skip',
            'label': 'Skip This Subject',
            'description': 'Do not import any questions for this subject'
        })
        
        return {
            'preview': preview.to_dict(),
            'confirmation_message': message,
            'options': options,
            'subject': subject,
            'can_proceed': preview.can_proceed
        }
    
    def get_section_details(
        self,
        exam_id: int,
        pattern_id: int,
        subject: str
    ) -> Dict:
        """
        Get detailed section information for display.
        Shows current state, capacity, and what's needed.
        """
        pattern_sections = PatternSection.objects.filter(
            pattern_id=pattern_id,
            subject__iexact=subject
        ).order_by('order', 'id')
        
        sections = []
        total_required = 0
        total_filled = 0
        
        for section in pattern_sections:
            current = Question.objects.filter(
                exam_id=exam_id,
                pattern_section_id=section.id,
                is_active=True
            ).count()
            
            required = section.total_questions
            remaining = max(0, required - current)
            
            total_required += required
            total_filled += current
            
            sections.append({
                'section_id': section.id,
                'section_name': section.name,
                'question_type': section.question_type,
                'question_type_display': dict(Question.QUESTION_TYPE_CHOICES).get(
                    section.question_type, section.question_type
                ),
                'required': required,
                'current': current,
                'remaining': remaining,
                'status': 'complete' if current >= required else 'incomplete',
                'completion_percent': (current / required * 100) if required > 0 else 0
            })
        
        return {
            'subject': subject,
            'sections': sections,
            'summary': {
                'total_required': total_required,
                'total_filled': total_filled,
                'total_remaining': total_required - total_filled,
                'completion_percent': (total_filled / total_required * 100) if total_required > 0 else 0
            }
        }
