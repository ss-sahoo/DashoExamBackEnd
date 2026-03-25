"""
Question Validation Service for validating extracted questions
"""
import logging
from typing import Tuple, List, Optional
from django.db.models import Q
from patterns.models import PatternSection
from questions.models import Question

logger = logging.getLogger('extraction')


class ValidationError(Exception):
    """Raised when validation fails"""
    pass


class QuestionValidationService:
    """Validate extracted questions against pattern requirements"""
    
    def validate_question(
        self, 
        question_data: dict, 
        pattern_section: Optional[PatternSection] = None,
        exam_id: Optional[int] = None
    ) -> Tuple[bool, List[str]]:
        """
        Validate question against pattern section requirements
        
        Args:
            question_data: Extracted question data
            pattern_section: Target pattern section (optional)
            exam_id: Exam ID for duplicate checking (optional)
            
        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        
        # Validate required fields
        field_errors = self._validate_required_fields(question_data)
        errors.extend(field_errors)
        
        # Validate question type
        type_errors = self._validate_question_type(question_data)
        errors.extend(type_errors)
        
        # Validate based on question type
        if question_data.get('question_type') in ['single_mcq', 'multiple_mcq']:
            mcq_errors = self.validate_mcq_options(question_data)
            errors.extend(mcq_errors)
        
        elif question_data.get('question_type') == 'numerical':
            numerical_errors = self._validate_numerical(question_data)
            errors.extend(numerical_errors)
        
        # Validate against pattern section if provided
        if pattern_section:
            section_errors = self.check_question_type_match(
                question_data.get('question_type', ''),
                pattern_section.question_type
            )
            if section_errors:
                errors.append(section_errors)
        
        # Check for duplicates if exam_id provided
        if exam_id:
            is_duplicate = self.check_duplicate(
                question_data.get('question_text', ''),
                exam_id
            )
            if is_duplicate:
                errors.append("Question already exists in this exam (duplicate detected)")
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    def _validate_required_fields(self, question_data: dict) -> List[str]:
        """Validate that required fields are present and non-empty"""
        errors = []
        
        # Check question text
        question_text = question_data.get('question_text', '').strip()
        if not question_text:
            errors.append("Question text is required and cannot be empty")
        elif len(question_text) < 10:
            errors.append("Question text is too short (minimum 10 characters)")
        
        # Check correct answer
        correct_answer = question_data.get('correct_answer')
        if not correct_answer or (isinstance(correct_answer, str) and not correct_answer.strip()):
            errors.append("Correct answer is required and cannot be empty")
        
        # Check question type
        if not question_data.get('question_type'):
            errors.append("Question type is required")
        
        return errors
    
    def _validate_question_type(self, question_data: dict) -> List[str]:
        """Validate that question type is valid"""
        errors = []
        
        valid_types = [
            'single_mcq',
            'multiple_mcq',
            'numerical',
            'subjective',
            'true_false',
            'fill_blank'
        ]
        
        question_type = question_data.get('question_type', '')
        if question_type not in valid_types:
            errors.append(
                f"Invalid question type '{question_type}'. "
                f"Must be one of: {', '.join(valid_types)}"
            )
        
        return errors
    
    def validate_mcq_options(self, question_data: dict) -> List[str]:
        """
        Validate MCQ options and correct answer
        
        Args:
            question_data: Question data with options
            
        Returns:
            List of error messages
        """
        errors = []
        
        options = question_data.get('options', [])
        correct_answer = question_data.get('correct_answer', '')
        question_type = question_data.get('question_type', '')
        
        # Check that options exist
        if not options or not isinstance(options, list):
            errors.append("MCQ questions must have options")
            return errors
        
        # Check minimum number of options
        if len(options) < 2:
            errors.append("MCQ questions must have at least 2 options")
        
        # Check that options are non-empty
        empty_options = [i for i, opt in enumerate(options) if not str(opt).strip()]
        if empty_options:
            errors.append(f"Options at positions {empty_options} are empty")
        
        # Check for duplicate options
        option_texts = [str(opt).strip().lower() for opt in options]
        if len(option_texts) != len(set(option_texts)):
            errors.append("Duplicate options found")
        
        # Validate correct answer
        if question_type == 'single_mcq':
            # Single correct answer must be in options
            if correct_answer not in options:
                # Try case-insensitive match
                correct_lower = str(correct_answer).strip().lower()
                options_lower = [str(opt).strip().lower() for opt in options]
                if correct_lower not in options_lower:
                    errors.append(
                        f"Correct answer '{correct_answer}' is not one of the options"
                    )
        
        elif question_type == 'multiple_mcq':
            # Multiple correct answers
            if isinstance(correct_answer, list):
                for ans in correct_answer:
                    if ans not in options:
                        errors.append(
                            f"Correct answer '{ans}' is not one of the options"
                        )
            else:
                # Single answer provided for multiple MCQ - should be a list
                if correct_answer not in options:
                    errors.append(
                        f"Correct answer '{correct_answer}' is not one of the options"
                    )
        
        return errors
    
    def _validate_numerical(self, question_data: dict) -> List[str]:
        """Validate numerical question answer"""
        errors = []
        
        correct_answer = question_data.get('correct_answer', '')
        
        # Try to parse as number
        try:
            float(str(correct_answer))
        except (ValueError, TypeError):
            errors.append(
                f"Numerical questions must have a numeric answer. "
                f"Got: '{correct_answer}'"
            )
        
        # Validate tolerance if provided
        tolerance = question_data.get('tolerance_range')
        if tolerance is not None:
            try:
                tolerance_val = float(tolerance)
                if tolerance_val < 0:
                    errors.append("Tolerance range cannot be negative")
            except (ValueError, TypeError):
                errors.append(f"Invalid tolerance range: '{tolerance}'")
        
        return errors
    
    def check_question_type_match(
        self, 
        question_type: str, 
        section_type: str
    ) -> Optional[str]:
        """
        Verify question type matches section requirements
        
        Args:
            question_type: Type of the question
            section_type: Required type from pattern section
            
        Returns:
            Error message if mismatch, None if valid
        """
        if question_type != section_type:
            return (
                f"Question type mismatch: question is '{question_type}' "
                f"but section requires '{section_type}'"
            )
        return None
    
    def validate_correct_answer(
        self, 
        correct_answer: str, 
        options: List[str]
    ) -> bool:
        """
        Verify correct answer is valid for the given options
        
        Args:
            correct_answer: The correct answer
            options: List of available options
            
        Returns:
            True if valid, False otherwise
        """
        if not options:
            return True  # No options to validate against
        
        # Check exact match
        if correct_answer in options:
            return True
        
        # Check case-insensitive match
        correct_lower = str(correct_answer).strip().lower()
        options_lower = [str(opt).strip().lower() for opt in options]
        
        return correct_lower in options_lower
    
    def check_duplicate(
        self, 
        question_text: str, 
        exam_id: int
    ) -> bool:
        """
        Check if question already exists in exam
        
        Args:
            question_text: Text of the question
            exam_id: ID of the exam
            
        Returns:
            True if duplicate found, False otherwise
        """
        if not question_text or not exam_id:
            return False
        
        # Normalize text for comparison
        normalized_text = question_text.strip().lower()
        
        # Remove extra whitespace
        normalized_text = ' '.join(normalized_text.split())
        
        # Check for existing questions with similar text
        existing_questions = Question.objects.filter(
            exam_id=exam_id,
            is_active=True
        )
        
        for question in existing_questions:
            existing_text = question.question_text.strip().lower()
            existing_text = ' '.join(existing_text.split())
            
            # Check for exact match
            if normalized_text == existing_text:
                return True
            
            # Check for very similar text (>90% similarity)
            similarity = self._calculate_similarity(normalized_text, existing_text)
            if similarity > 0.9:
                logger.warning(
                    f"Found similar question (similarity: {similarity:.2f}): "
                    f"{question_text[:50]}..."
                )
                return True
        
        return False
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity between two texts using simple ratio
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score (0.0 to 1.0)
        """
        # Simple character-based similarity
        if not text1 or not text2:
            return 0.0
        
        # Use set intersection for word-based similarity
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0
    
    def validate_batch(
        self, 
        questions: List[dict],
        pattern_section: Optional[PatternSection] = None,
        exam_id: Optional[int] = None
    ) -> Tuple[List[dict], List[dict]]:
        """
        Validate a batch of questions
        
        Args:
            questions: List of question data dictionaries
            pattern_section: Target pattern section
            exam_id: Exam ID for duplicate checking
            
        Returns:
            Tuple of (valid_questions, invalid_questions_with_errors)
        """
        valid_questions = []
        invalid_questions = []
        
        for i, question_data in enumerate(questions):
            is_valid, errors = self.validate_question(
                question_data,
                pattern_section,
                exam_id
            )
            
            if is_valid:
                valid_questions.append(question_data)
            else:
                invalid_questions.append({
                    'index': i,
                    'question_data': question_data,
                    'errors': errors
                })
        
        logger.info(
            f"Batch validation: {len(valid_questions)} valid, "
            f"{len(invalid_questions)} invalid"
        )
        
        return valid_questions, invalid_questions
    
    def get_section_by_question_type(
        self,
        pattern_id: int,
        question_type: str,
        subject: Optional[str] = None
    ) -> Optional[PatternSection]:
        """
        Find appropriate section for a question type
        
        Args:
            pattern_id: Pattern ID
            question_type: Type of question
            subject: Optional subject filter
            
        Returns:
            PatternSection if found, None otherwise
        """
        try:
            query = Q(pattern_id=pattern_id, question_type=question_type)
            
            if subject:
                query &= Q(subject=subject)
            
            section = PatternSection.objects.filter(query).first()
            return section
            
        except Exception as e:
            logger.error(f"Error finding section: {e}")
            return None
