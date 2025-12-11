"""
Pre-Analysis Service for Question Files
Analyzes files before extraction to estimate question count and structure
"""
import re
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger('extraction')


@dataclass
class QuestionPattern:
    """Represents a detected question pattern"""
    pattern_type: str  # 'numbered', 'lettered', 'q_prefix', 'question_word'
    regex: str
    count: int
    examples: List[str]


class PreAnalyzer:
    """
    Analyze uploaded files before extraction to:
    - Estimate total question count
    - Detect question patterns and structure
    - Identify LaTeX content
    - Detect subjects from headings
    """
    
    # Question number patterns (ordered by specificity)
    QUESTION_PATTERNS = [
        # Q1. or Q.1 or Q 1 patterns
        (r'(?:^|\n)\s*Q\.?\s*(\d+)[\.\)\:]?\s', 'q_prefix'),
        # Question 1: or Question 1. patterns
        (r'(?:^|\n)\s*Question\s+(\d+)[\.\)\:]?\s', 'question_word'),
        # Markdown heading style: ### 1. or ## 1. or # 1.
        (r'(?:^|\n)\s*#{1,4}\s*(\d+)[\.\)]\s', 'markdown_heading'),
        # 1. or 1) at start of line (most common)
        (r'(?:^|\n)\s*(\d+)[\.\)]\s+[A-Z]', 'numbered'),
        # (1) pattern
        (r'(?:^|\n)\s*\((\d+)\)\s+[A-Z]', 'parenthesis'),
        # **1. or **1) bold numbered pattern
        (r'(?:^|\n)\s*\*\*(\d+)[\.\)]\s', 'bold_numbered'),
    ]
    
    # MCQ option patterns
    OPTION_PATTERNS = [
        r'(?:^|\n)\s*\(?[A-Da-d]\)?[\.\)]\s',  # A) or (A) or A.
        r'(?:^|\n)\s*\(?[1-4]\)?[\.\)]\s',      # 1) or (1) or 1.
        r'(?:^|\n)\s*\(?[i-iv]\)?[\.\)]\s',     # i) or (i) or i.
    ]
    
    # LaTeX patterns
    LATEX_PATTERNS = [
        r'\$[^\$]+\$',           # Inline math $...$
        r'\$\$[^\$]+\$\$',       # Display math $$...$$
        r'\\frac\{[^}]+\}\{[^}]+\}',  # Fractions
        r'\\sqrt(?:\[[^\]]+\])?\{[^}]+\}',  # Square roots
        r'\\int(?:_[^}]+)?(?:\^[^}]+)?',    # Integrals
        r'\\sum(?:_[^}]+)?(?:\^[^}]+)?',    # Summations
        r'\\[a-zA-Z]+\{',        # Any LaTeX command with braces
        r'\\begin\{[^}]+\}',     # Environment starts
    ]
    
    # Generic subject heading patterns - captures ANY subject name
    # These patterns are designed to detect subject headers dynamically
    SUBJECT_PATTERNS = [
        # Pattern 1: "Section: Subject Name" or "Part - Subject Name"
        r'(?:^|\n)\s*(?:Section|Part|Chapter|Subject)\s*[-:\s]+([A-Za-z][A-Za-z\s]{2,30}?)\s*(?:Section|Questions|Part|$|\n)',
        # Pattern 2: "SUBJECT NAME" in all caps on its own line
        r'(?:^|\n)\s*([A-Z][A-Z\s]{3,30}?)\s*(?:\n|:)',
        # Pattern 3: Subject name followed by colon
        r'(?:^|\n)\s*([A-Za-z][A-Za-z\s]{2,25}):\s*(?:\n|$)',
    ]
    
    # Question type indicators
    TYPE_INDICATORS = {
        'multiple_mcq': [
            r'select\s+all',
            r'choose\s+all',
            r'more\s+than\s+one',
            r'multiple\s+correct',
            r'one\s+or\s+more',
            r'which\s+(?:of\s+the\s+following\s+)?are\s+(?:correct|true)',
        ],
        'true_false': [
            r'true\s+or\s+false',
            r'\btrue/false\b',
            r'\bT/F\b',
            r'state\s+(?:whether|if).*(?:true|false)',
            r'correct\s+or\s+incorrect',
        ],
        'fill_blank': [
            r'_{3,}',           # Three or more underscores
            r'\[blank\]',
            r'\[___+\]',
            r'fill\s+in\s+the\s+blank',
            r'complete\s+the\s+(?:sentence|statement)',
        ],
        'numerical': [
            r'calculate\s+the',
            r'find\s+the\s+(?:value|area|volume|distance)',
            r'what\s+is\s+the\s+(?:value|result)',
            r'compute\s+the',
            r'evaluate\s+the',
            r'(?:answer|ans)[\s:]+[\d\.\-]+',
        ],
        'subjective': [
            r'explain\s+(?:why|how|the)',
            r'describe\s+the',
            r'discuss\s+the',
            r'elaborate\s+on',
            r'justify\s+your',
            r'write\s+(?:a\s+)?(?:short\s+)?(?:note|essay|paragraph)',
            r'\(\s*\d+\s*(?:words?|marks?)\s*\)',
        ],
    }
    
    def analyze_file(self, text_content: str) -> Dict:
        """
        Comprehensive file analysis before extraction
        
        Args:
            text_content: Raw text from file
            
        Returns:
            Analysis results including estimated question count, patterns, etc.
        """
        logger.info("Starting pre-analysis of file content")
        
        # Estimate question count
        question_count, question_patterns = self._count_questions(text_content)
        
        # Detect LaTeX content
        has_latex, latex_count, latex_samples = self._detect_latex(text_content)
        
        # Detect subjects from headings
        detected_subjects = self._detect_subjects(text_content)
        
        # Detect question type distribution
        type_distribution = self._estimate_type_distribution(text_content)
        
        # Detect file structure
        structure = self._analyze_structure(text_content, question_patterns)
        
        # Calculate confidence in estimates
        confidence = self._calculate_confidence(
            question_count, 
            question_patterns, 
            len(text_content)
        )
        
        result = {
            'estimated_question_count': question_count,
            'confidence': confidence,
            'detected_patterns': [p.pattern_type for p in question_patterns],
            'pattern_details': [
                {
                    'type': p.pattern_type,
                    'count': p.count,
                    'examples': p.examples[:3]
                }
                for p in question_patterns
            ],
            'has_latex': has_latex,
            'latex_count': latex_count,
            'latex_samples': latex_samples[:5],
            'detected_subjects': detected_subjects,
            'type_distribution': type_distribution,
            'file_structure': structure,
            'total_characters': len(text_content),
            'total_lines': text_content.count('\n') + 1,
            'recommended_chunk_size': self._recommend_chunk_size(question_count),
        }
        
        logger.info(
            f"Pre-analysis complete: ~{question_count} questions, "
            f"LaTeX: {has_latex}, Subjects: {detected_subjects}"
        )
        
        return result
    
    def _count_questions(self, text: str) -> Tuple[int, List[QuestionPattern]]:
        """
        Count questions using multiple pattern detection strategies
        
        Returns:
            Tuple of (estimated_count, list of detected patterns)
        """
        detected_patterns = []
        all_question_numbers = set()
        
        for pattern_regex, pattern_type in self.QUESTION_PATTERNS:
            matches = list(re.finditer(pattern_regex, text, re.IGNORECASE | re.MULTILINE))
            
            if matches:
                # Extract question numbers to verify sequence
                numbers = []
                examples = []
                for m in matches:
                    try:
                        num = int(m.group(1))
                        numbers.append(num)
                        all_question_numbers.add(num)
                        # Get context around match (only for first 10)
                        if len(examples) < 10:
                            start = max(0, m.start() - 10)
                            end = min(len(text), m.end() + 50)
                            examples.append(text[start:end].strip()[:80])
                    except (ValueError, IndexError):
                        continue
                
                if numbers:
                    detected_patterns.append(QuestionPattern(
                        pattern_type=pattern_type,
                        regex=pattern_regex,
                        count=len(matches),
                        examples=examples
                    ))
        
        # Determine best estimate
        if not detected_patterns:
            # Fallback: count by option patterns (MCQ detection)
            option_count = self._count_option_groups(text)
            return option_count, []
        
        # Use multiple strategies to get the best count
        estimates = []
        
        # Strategy 1: Use the pattern with highest count
        best_pattern = max(detected_patterns, key=lambda p: p.count)
        estimates.append(best_pattern.count)
        
        # Strategy 2: Use the highest question number found
        if all_question_numbers:
            max_q_num = max(all_question_numbers)
            estimates.append(max_q_num)
        
        # Strategy 3: Count unique question numbers across all patterns
        estimates.append(len(all_question_numbers))
        
        # Strategy 4: Check for sequential numbering gaps
        if all_question_numbers:
            sorted_nums = sorted(all_question_numbers)
            # If numbers are mostly sequential, use max
            if sorted_nums[-1] - sorted_nums[0] + 1 <= len(sorted_nums) * 1.5:
                estimates.append(sorted_nums[-1])
        
        # Use the maximum estimate (to avoid under-counting)
        estimated_count = max(estimates)
        
        logger.info(
            f"Question count estimates: pattern={best_pattern.count}, "
            f"max_num={max(all_question_numbers) if all_question_numbers else 0}, "
            f"unique={len(all_question_numbers)}, final={estimated_count}"
        )
        
        return estimated_count, detected_patterns
    
    def _count_option_groups(self, text: str) -> int:
        """Count MCQ questions by detecting option groups (A, B, C, D)"""
        # Look for groups of 4 consecutive options
        option_groups = re.findall(
            r'(?:^|\n)\s*\(?A\)?[\.\)][^\n]+\n\s*\(?B\)?[\.\)][^\n]+\n\s*\(?C\)?[\.\)][^\n]+\n\s*\(?D\)?[\.\)]',
            text,
            re.IGNORECASE | re.MULTILINE
        )
        return len(option_groups)
    
    def _detect_latex(self, text: str) -> Tuple[bool, int, List[str]]:
        """
        Detect LaTeX content in text
        
        Returns:
            Tuple of (has_latex, count, sample_expressions)
        """
        latex_expressions = []
        
        for pattern in self.LATEX_PATTERNS:
            matches = re.findall(pattern, text)
            latex_expressions.extend(matches)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_latex = []
        for expr in latex_expressions:
            if expr not in seen:
                seen.add(expr)
                unique_latex.append(expr)
        
        return len(unique_latex) > 0, len(unique_latex), unique_latex[:10]
    
    def _detect_subjects(self, text: str) -> List[str]:
        """
        Detect subjects from section headings.
        DYNAMIC: Works with ANY subject - not limited to predefined list.
        """
        subjects = []
        
        # Words that are commonly found in headers but are NOT subjects
        non_subject_words = {
            'section', 'part', 'chapter', 'question', 'questions', 'answer', 'answers',
            'instructions', 'instruction', 'general', 'note', 'notes', 'marks', 'mark',
            'time', 'duration', 'total', 'marks', 'attempt', 'all', 'any', 'the',
            'compulsory', 'optional', 'paper', 'examination', 'exam', 'test', 'quiz',
            'directions', 'read', 'carefully', 'following', 'given', 'below', 'above',
            'choose', 'correct', 'option', 'multiple', 'choice', 'fill', 'blank',
            'true', 'false', 'match', 'following', 'column', 'row', 'table',
        }
        
        for pattern in self.SUBJECT_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                subject = match.strip().title()
                subject_lower = subject.lower()
                
                # Filter out non-subjects
                if (subject and 
                    subject not in subjects and 
                    len(subject) > 2 and  # Must be more than 2 characters
                    subject_lower not in non_subject_words and
                    not all(word in non_subject_words for word in subject_lower.split())):
                    subjects.append(subject)
        
        return subjects
    
    def _estimate_type_distribution(self, text: str) -> Dict[str, int]:
        """Estimate distribution of question types"""
        distribution = {
            'single_mcq': 0,
            'multiple_mcq': 0,
            'true_false': 0,
            'fill_blank': 0,
            'numerical': 0,
            'subjective': 0,
        }
        
        # Count indicators for each type
        for q_type, patterns in self.TYPE_INDICATORS.items():
            count = 0
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                count += len(matches)
            distribution[q_type] = count
        
        # Count MCQ by option patterns (default to single_mcq)
        mcq_count = self._count_option_groups(text)
        
        # Subtract multiple_mcq from total MCQ to get single_mcq
        distribution['single_mcq'] = max(0, mcq_count - distribution['multiple_mcq'])
        
        return distribution
    
    def _analyze_structure(self, text: str, patterns: List[QuestionPattern]) -> str:
        """Analyze the overall structure of the file"""
        # Check for section headers
        has_sections = bool(re.search(
            r'(?:Section|Part|Chapter)\s*[A-Z0-9]',
            text,
            re.IGNORECASE
        ))
        
        # Check for subject headers
        has_subject_headers = bool(re.search(
            r'(?:Physics|Chemistry|Mathematics|Biology)\s*(?:Section|Questions)?',
            text,
            re.IGNORECASE
        ))
        
        # Determine structure type
        if has_subject_headers:
            return 'multi_subject_sections'
        elif has_sections:
            return 'sectioned'
        elif patterns:
            return 'sequential_numbered'
        else:
            return 'unstructured'
    
    def _calculate_confidence(
        self, 
        question_count: int, 
        patterns: List[QuestionPattern],
        text_length: int
    ) -> float:
        """Calculate confidence in the question count estimate"""
        if question_count == 0:
            return 0.0
        
        confidence = 0.5  # Base confidence
        
        # Boost for detected patterns
        if patterns:
            confidence += 0.2
            
            # Higher confidence if multiple patterns agree
            if len(patterns) > 1:
                counts = [p.count for p in patterns]
                if max(counts) - min(counts) < 5:  # Patterns agree
                    confidence += 0.1
        
        # Boost for reasonable question density
        chars_per_question = text_length / question_count if question_count > 0 else 0
        if 200 < chars_per_question < 2000:  # Reasonable range
            confidence += 0.1
        
        # Cap at 0.95
        return min(0.95, confidence)
    
    def _recommend_chunk_size(self, question_count: int) -> int:
        """Recommend optimal chunk size based on question count"""
        if question_count <= 30:
            return question_count  # Process all at once
        elif question_count <= 100:
            return 30  # ~3-4 chunks
        elif question_count <= 300:
            return 40  # ~8-10 chunks
        else:
            return 50  # For very large files
    
    def count_questions_simple(self, text: str) -> int:
        """
        Simple question counter for quick estimates
        
        Args:
            text: Raw text content
            
        Returns:
            Estimated question count
        """
        count, _ = self._count_questions(text)
        return count
    
    def validate_extraction_completeness(
        self, 
        expected_count: int, 
        extracted_count: int,
        tolerance: float = 0.05
    ) -> Dict:
        """
        Validate if extraction was complete
        
        Args:
            expected_count: Pre-analysis estimated count
            extracted_count: Actual extracted count
            tolerance: Acceptable variance (default 5%)
            
        Returns:
            Validation result with completeness metrics
        """
        if expected_count == 0:
            return {
                'is_complete': extracted_count > 0,
                'completeness_percentage': 100.0 if extracted_count > 0 else 0.0,
                'expected': expected_count,
                'extracted': extracted_count,
                'difference': extracted_count,
                'status': 'unknown_expected'
            }
        
        completeness = (extracted_count / expected_count) * 100
        difference = extracted_count - expected_count
        
        # Allow some tolerance
        min_acceptable = expected_count * (1 - tolerance)
        max_acceptable = expected_count * (1 + tolerance)
        
        is_complete = min_acceptable <= extracted_count <= max_acceptable
        
        if extracted_count < min_acceptable:
            status = 'incomplete'
        elif extracted_count > max_acceptable:
            status = 'over_extracted'  # Might have duplicates
        else:
            status = 'complete'
        
        return {
            'is_complete': is_complete,
            'completeness_percentage': min(100.0, completeness),
            'expected': expected_count,
            'extracted': extracted_count,
            'difference': difference,
            'status': status
        }
