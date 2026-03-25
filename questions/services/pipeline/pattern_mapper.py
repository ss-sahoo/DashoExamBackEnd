"""
Stage 6: Pattern Mapper
Maps extracted/validated questions to exam pattern sections.
Creates ExtractedQuestion model instances ready for user review/import.
"""
import re
import logging
from typing import Dict, List, Optional
from difflib import SequenceMatcher

logger = logging.getLogger('extraction')


class PatternMapperError(Exception):
    """Raised when pattern mapping fails"""
    pass


class PatternMapper:
    """
    Stage 6 of the extraction pipeline.
    
    Maps extracted questions to the exam pattern sections:
    - Matches subjects from extraction to pattern subjects
    - Assigns each question to the correct PatternSection
    - Creates ExtractedQuestion model instances in the database
    
    This is where extraction results become database records, 
    ready for user review and final import.
    """
    
    def map_to_pattern(
        self,
        questions: List[Dict],
        pattern,
        job,
    ) -> Dict:
        """
        Map extracted questions to pattern sections and save to DB.
        
        Args:
            questions: Validated questions from Stage 5
            pattern: ExamPattern model instance
            job: ExtractionJob model instance
            
        Returns:
            {
                'saved_count': int,
                'mapped_count': int,
                'unmapped_count': int,
                'per_section': {
                    section_id: {'mapped': int, 'expected': int},
                    ...
                },
                'mapping_issues': [str, ...],
            }
        """
        logger.info(
            f"[Stage 6] Mapping {len(questions)} questions to pattern "
            f"'{pattern.name}'..."
        )
        
        # Get pattern sections
        sections = list(pattern.sections.all().order_by('subject', 'order', 'start_question'))
        
        # Build subject mapping (fuzzy match source subjects → pattern subjects)
        subject_mapping = self._build_subject_mapping(questions, sections)
        
        # Map each question to its pattern section
        mapped_questions = []
        unmapped_questions = []
        mapping_issues = []
        
        per_section = {s.id: {'mapped': 0, 'expected': s.total_questions_in_section} for s in sections}
        
        for q in questions:
            source = q.get('_source', {})
            source_subject = source.get('subject', '')
            source_section = source.get('section_name', '')
            source_type = source.get('question_type', '')
            q_number = q.get('question_number', 0)
            
            # Find the best matching pattern section
            matched_section = self._find_matching_section(
                sections, source_subject, source_type, q_number,
                subject_mapping
            )
            
            if matched_section:
                mapped_questions.append({
                    'question_data': q,
                    'section': matched_section,
                })
                per_section[matched_section.id]['mapped'] += 1
            else:
                unmapped_questions.append(q)
                mapping_issues.append(
                    f"Q{q_number} ({source_subject}/{source_type}): "
                    f"No matching pattern section found"
                )
        
        # Save to database
        saved_count = self._save_to_database(mapped_questions, unmapped_questions, job)
        
        result = {
            'saved_count': saved_count,
            'mapped_count': len(mapped_questions),
            'unmapped_count': len(unmapped_questions),
            'per_section': per_section,
            'mapping_issues': mapping_issues,
        }
        
        logger.info(
            f"[Stage 6] Mapping complete: {len(mapped_questions)} mapped, "
            f"{len(unmapped_questions)} unmapped, {saved_count} saved to DB"
        )
        
        return result
    
    def _build_subject_mapping(
        self,
        questions: List[Dict],
        sections
    ) -> Dict[str, str]:
        """
        Build a mapping from source subjects to pattern subjects.
        Uses fuzzy matching to handle slight name differences.
        """
        # Get unique source subjects
        source_subjects = set()
        for q in questions:
            subj = q.get('_source', {}).get('subject', '')
            if subj:
                source_subjects.add(subj)
        
        # Get unique pattern subjects
        pattern_subjects = set(s.subject for s in sections)
        
        # Build mapping
        mapping = {}
        for src in source_subjects:
            best_match = None
            best_score = 0.0
            
            for pat in pattern_subjects:
                # Exact match
                if src.lower() == pat.lower():
                    best_match = pat
                    best_score = 1.0
                    break
                
                # Fuzzy match
                score = SequenceMatcher(None, src.lower(), pat.lower()).ratio()
                if score > best_score and score > 0.5:
                    best_match = pat
                    best_score = score
                
                # Substring match
                if src.lower() in pat.lower() or pat.lower() in src.lower():
                    best_match = pat
                    best_score = 0.9
            
            if best_match:
                mapping[src] = best_match
                logger.debug(f"Subject mapping: '{src}' → '{best_match}' (score={best_score:.2f})")
            else:
                mapping[src] = src
                logger.warning(f"No pattern match for subject: '{src}'")
        
        return mapping
    
    def _find_matching_section(
        self,
        sections,
        source_subject: str,
        source_type: str,
        question_number: int,
        subject_mapping: Dict[str, str]
    ):
        """Find the best matching PatternSection for a question"""
        
        # Map source subject to pattern subject
        pattern_subject = subject_mapping.get(source_subject, source_subject)
        
        # Filter sections by subject
        subject_sections = [
            s for s in sections
            if s.subject.lower() == pattern_subject.lower()
        ]
        
        if not subject_sections:
            # Try all sections if subject doesn't match
            subject_sections = list(sections)
        
        # Strategy 1: Match by question_number range AND type
        for s in subject_sections:
            if (s.start_question <= question_number <= s.end_question and
                    s.question_type == source_type):
                return s
        
        # Strategy 2: Match by question_number range only
        for s in subject_sections:
            if s.start_question <= question_number <= s.end_question:
                return s
        
        # Strategy 3: Match by type only (for the right subject)
        type_matches = [s for s in subject_sections if s.question_type == source_type]
        if type_matches:
            # Pick the section with most remaining capacity
            return type_matches[0]
        
        # Strategy 4: First section of the subject
        if subject_sections:
            return subject_sections[0]
        
        return None
    
    def _save_to_database(
        self,
        mapped_questions: List[Dict],
        unmapped_questions: List[Dict],
        job,
    ) -> int:
        """Save extracted questions to the database as ExtractedQuestion records"""
        from questions.models import ExtractedQuestion
        
        saved = 0
        
        # Save mapped questions
        for item in mapped_questions:
            q = item['question_data']
            section = item['section']
            
            try:
                eq = ExtractedQuestion(
                    job=job,
                    question_text=q.get('question_text', ''),
                    question_type=self._normalize_type(q.get('question_type', 'single_mcq')),
                    options=q.get('options', []),
                    correct_answer=str(q.get('correct_answer', '')),
                    solution=q.get('solution', ''),
                    explanation='',
                    difficulty=q.get('difficulty', 'medium'),
                    confidence_score=q.get('confidence_score', 0.7),
                    requires_review=q.get('requires_review', False),
                    suggested_subject=section.subject,
                    suggested_section_id=section.id,
                    assigned_subject=section.subject,
                    assigned_section_id=section.id,
                    detection_reasoning=f"Mapped Q{q.get('question_number', '?')} to {section.name} ({section.subject})",
                    is_validated=True,
                    structure=q.get('structure', {}),
                )
                eq.save()
                saved += 1
            except Exception as e:
                logger.error(
                    f"Failed to save Q{q.get('question_number', '?')}: {e}"
                )
        
        # Save unmapped questions (without section assignment)
        for q in unmapped_questions:
            try:
                source = q.get('_source', {})
                eq = ExtractedQuestion(
                    job=job,
                    question_text=q.get('question_text', ''),
                    question_type=self._normalize_type(q.get('question_type', 'single_mcq')),
                    options=q.get('options', []),
                    correct_answer=str(q.get('correct_answer', '')),
                    solution=q.get('solution', ''),
                    explanation='',
                    difficulty=q.get('difficulty', 'medium'),
                    confidence_score=max(0.3, q.get('confidence_score', 0.5) - 0.2),
                    requires_review=True,
                    suggested_subject=source.get('subject', ''),
                    detection_reasoning="No matching pattern section found — requires manual assignment",
                    is_validated=False,
                    structure=q.get('structure', {}),
                )
                eq.save()
                saved += 1
            except Exception as e:
                logger.error(
                    f"Failed to save unmapped Q{q.get('question_number', '?')}: {e}"
                )
        
        return saved
    
    def _normalize_type(self, q_type: str) -> str:
        """Normalize question type to valid model choices"""
        valid_types = {
            'single_mcq', 'multiple_mcq', 'numerical',
            'subjective', 'true_false', 'fill_blank',
        }
        if q_type in valid_types:
            return q_type
        
        # Map common alternatives
        type_map = {
            'mcq': 'single_mcq',
            'integer': 'numerical',
            'numeric': 'numerical',
            'essay': 'subjective',
            'descriptive': 'subjective',
            'boolean': 'true_false',
        }
        return type_map.get(q_type.lower(), 'single_mcq')
