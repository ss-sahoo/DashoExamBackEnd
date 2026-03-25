"""
Capacity Calculator Service for Pattern Section Management
"""
import logging
from typing import Dict, List
from django.db.models import Count, Q
from patterns.models import ExamPattern, PatternSection
from questions.models import Question

logger = logging.getLogger('extraction')


class CapacityCalculator:
    """
    Calculate and track question capacity for exam pattern sections
    """
    
    def calculate_pattern_capacity(self, exam_id: int, pattern_id: int) -> Dict:
        """
        Calculate capacity for entire pattern
        
        Returns:
            {
                'pattern_id': 31,
                'pattern_name': 'JEE Main 2024',
                'total_required': 90,
                'total_filled': 65,
                'total_remaining': 25,
                'subjects': {...}
            }
        """
        try:
            pattern = ExamPattern.objects.get(id=pattern_id)
            
            # Get all unique subjects from pattern sections
            subjects_data = {}
            total_required = 0
            total_filled = 0
            
            # Get unique subjects from pattern sections
            unique_subjects = PatternSection.objects.filter(
                pattern=pattern
            ).values_list('subject', flat=True).distinct()
            
            for subject_name in unique_subjects:
                subject_capacity = self.calculate_subject_capacity(
                    exam_id, 
                    pattern_id, 
                    subject_name
                )
                subjects_data[subject_name] = subject_capacity
                total_required += subject_capacity['total_required']
                total_filled += subject_capacity['total_filled']
            
            return {
                'pattern_id': pattern_id,
                'pattern_name': pattern.name,
                'total_required': total_required,
                'total_filled': total_filled,
                'total_remaining': total_required - total_filled,
                'completion_percentage': (total_filled / total_required * 100) if total_required > 0 else 0,
                'subjects': subjects_data
            }
            
        except ExamPattern.DoesNotExist:
            logger.error(f"Pattern {pattern_id} not found")
            raise Exception(f"Pattern {pattern_id} not found")
        except Exception as e:
            logger.error(f"Error calculating pattern capacity: {e}", exc_info=True)
            raise
    
    def calculate_subject_capacity(
        self, 
        exam_id: int, 
        pattern_id: int, 
        subject: str
    ) -> Dict:
        """
        Calculate capacity for a specific subject
        
        Returns:
            {
                'subject': 'physics',
                'total_required': 30,
                'total_filled': 20,
                'total_remaining': 10,
                'sections': [...]
            }
        """
        try:
            # Get all sections for this subject
            sections = PatternSection.objects.filter(
                pattern_id=pattern_id,
                subject=subject
            )
            
            sections_data = []
            total_required = 0
            total_filled = 0
            
            for section in sections:
                section_capacity = self.calculate_section_capacity(exam_id, section)
                sections_data.append(section_capacity)
                total_required += section_capacity['required']
                total_filled += section_capacity['current']
            
            return {
                'subject': subject,
                'total_required': total_required,
                'total_filled': total_filled,
                'total_remaining': total_required - total_filled,
                'completion_percentage': (total_filled / total_required * 100) if total_required > 0 else 0,
                'sections': sections_data
            }
            
        except Exception as e:
            logger.error(f"Error calculating subject capacity: {e}", exc_info=True)
            return {
                'subject': subject,
                'total_required': 0,
                'total_filled': 0,
                'total_remaining': 0,
                'completion_percentage': 0,
                'sections': []
            }
    
    def calculate_section_capacity(self, exam_id: int, section: PatternSection) -> Dict:
        """
        Calculate capacity for a specific section
        
        Returns:
            {
                'section_id': 5,
                'section_name': 'Section A',
                'subject': 'physics',
                'question_type': 'single_mcq',
                'required': 20,
                'current': 15,
                'remaining': 5,
                'overflow': 0,
                'status': 'incomplete'  # 'incomplete', 'complete', 'overflow'
            }
        """
        try:
            required = section.total_questions
            
            # Count current questions in this section
            # Use pattern_section_id instead of pattern_section
            current = Question.objects.filter(
                exam_id=exam_id,
                pattern_section_id=section.id
            ).count()
            
            remaining = max(0, required - current)
            overflow = max(0, current - required)
            
            # Determine status
            if current < required:
                status = 'incomplete'
            elif current == required:
                status = 'complete'
            else:
                status = 'overflow'
            
            return {
                'section_id': section.id,
                'section_name': section.name,
                'subject': section.subject,
                'question_type': section.question_type,
                'required': required,
                'current': current,
                'remaining': remaining,
                'overflow': overflow,
                'status': status,
                'completion_percentage': (current / required * 100) if required > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error calculating section capacity: {e}", exc_info=True)
            # Return a valid structure even on error
            return {
                'section_id': section.id,
                'section_name': section.name,
                'subject': section.subject,
                'question_type': section.question_type,
                'required': 0,
                'current': 0,
                'remaining': 0,
                'overflow': 0,
                'status': 'error',
                'completion_percentage': 0
            }
    
    def analyze_extraction_mismatches(
        self, 
        exam_id: int, 
        pattern_id: int,
        extracted_questions: Dict
    ) -> Dict:
        """
        Analyze mismatches between extracted questions and pattern requirements
        
        Args:
            exam_id: Exam ID
            pattern_id: Pattern ID
            extracted_questions: Dict with subject-grouped questions
                {
                    'subjects': {
                        'physics': [questions],
                        'mathematics': [questions]
                    }
                }
        
        Returns:
            {
                'mismatches': [
                    {
                        'subject': 'physics',
                        'section_id': 5,
                        'section_name': 'Section A',
                        'question_type': 'single_mcq',
                        'required': 20,
                        'extracted': 25,
                        'status': 'overflow',
                        'excess': 5
                    }
                ],
                'summary': {
                    'total_overflow': 10,
                    'total_shortage': 5,
                    'sections_with_overflow': 2,
                    'sections_with_shortage': 1
                }
            }
        """
        try:
            mismatches = []
            total_overflow = 0
            total_shortage = 0
            sections_with_overflow = 0
            sections_with_shortage = 0
            
            # Get pattern capacity
            capacity = self.calculate_pattern_capacity(exam_id, pattern_id)
            
            # Group extracted questions by subject and type
            extracted_by_subject_type = {}
            for subject, questions in extracted_questions.get('subjects', {}).items():
                if subject not in extracted_by_subject_type:
                    extracted_by_subject_type[subject] = {}
                
                for q in questions:
                    q_type = q.get('question_type', 'single_mcq')
                    if q_type not in extracted_by_subject_type[subject]:
                        extracted_by_subject_type[subject][q_type] = []
                    extracted_by_subject_type[subject][q_type].append(q)
            
            # Compare with pattern requirements
            for subject, subject_data in capacity.get('subjects', {}).items():
                for section in subject_data.get('sections', []):
                    section_type = section['question_type']
                    required = section['required']
                    current = section['current']
                    
                    # Get extracted count for this subject/type
                    extracted_count = len(
                        extracted_by_subject_type.get(subject, {}).get(section_type, [])
                    )
                    
                    # Calculate what would be the total after import
                    total_after_import = current + extracted_count
                    
                    if total_after_import > required:
                        # Overflow situation
                        excess = total_after_import - required
                        mismatches.append({
                            'subject': subject,
                            'section_id': section['section_id'],
                            'section_name': section['section_name'],
                            'question_type': section_type,
                            'required': required,
                            'current': current,
                            'extracted': extracted_count,
                            'total_after_import': total_after_import,
                            'status': 'overflow',
                            'excess': excess,
                            'message': f"Found {extracted_count} questions, but only {required - current} more needed"
                        })
                        total_overflow += excess
                        sections_with_overflow += 1
                    
                    elif total_after_import < required:
                        # Shortage situation
                        shortage = required - total_after_import
                        mismatches.append({
                            'subject': subject,
                            'section_id': section['section_id'],
                            'section_name': section['section_name'],
                            'question_type': section_type,
                            'required': required,
                            'current': current,
                            'extracted': extracted_count,
                            'total_after_import': total_after_import,
                            'status': 'shortage',
                            'shortage': shortage,
                            'message': f"Found {extracted_count} questions, but {shortage} more needed"
                        })
                        total_shortage += shortage
                        sections_with_shortage += 1
            
            return {
                'mismatches': mismatches,
                'summary': {
                    'total_overflow': total_overflow,
                    'total_shortage': total_shortage,
                    'sections_with_overflow': sections_with_overflow,
                    'sections_with_shortage': sections_with_shortage,
                    'has_mismatches': len(mismatches) > 0
                }
            }
            
        except Exception as e:
            logger.error(f"Error analyzing mismatches: {e}")
            return {'mismatches': [], 'summary': {}}
    
    def get_available_sections_for_question(
        self, 
        pattern_id: int, 
        question_type: str, 
        subject: str
    ) -> List[Dict]:
        """
        Get available sections that can accept a question of given type and subject
        
        Returns:
            [
                {
                    'section_id': 5,
                    'section_name': 'Section A',
                    'subject': 'physics',
                    'question_type': 'single_mcq',
                    'can_accept': True,
                    'reason': 'Has space for 5 more questions'
                }
            ]
        """
        try:
            sections = PatternSection.objects.filter(
                pattern_id=pattern_id,
                subject=subject,
                question_type=question_type
            )
            
            available_sections = []
            for section in sections:
                # This would need exam_id to calculate current capacity
                # For now, just return section info
                available_sections.append({
                    'section_id': section.id,
                    'section_name': section.name,
                    'subject': section.subject,
                    'question_type': section.question_type,
                    'total_questions': section.total_questions,
                    'can_accept': True  # Would need to check current count
                })
            
            return available_sections
            
        except Exception as e:
            logger.error(f"Error getting available sections: {e}")
            return []
