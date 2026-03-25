"""
Enhanced Question Type Classifier
Accurately classifies questions into 6 types with confidence scoring
"""
import re
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger('extraction')


@dataclass
class ClassificationResult:
    """Result of question type classification"""
    question_type: str
    confidence: float
    reasoning: str
    indicators_found: List[str]


class QuestionTypeClassifier:
    """
    Classify questions into 6 types with high accuracy:
    - single_mcq: Single correct MCQ
    - multiple_mcq: Multiple correct MCQ
    - numerical: Numerical answer
    - subjective: Long-form text answer
    - true_false: True/False questions
    - fill_blank: Fill in the blanks
    """
    
    # Keywords and patterns for each question type
    MULTIPLE_MCQ_INDICATORS = [
        # Explicit instructions
        (r'select\s+all\s+(?:that\s+apply|correct)', 0.95, 'explicit_select_all'),
        (r'choose\s+all\s+(?:that\s+apply|correct)', 0.95, 'explicit_choose_all'),
        (r'more\s+than\s+one\s+(?:correct|answer|option)', 0.90, 'more_than_one'),
        (r'multiple\s+(?:correct|answers?)', 0.90, 'multiple_correct'),
        (r'one\s+or\s+more\s+(?:correct|answers?)', 0.85, 'one_or_more'),
        (r'which\s+(?:of\s+the\s+following\s+)?are\s+(?:correct|true)', 0.85, 'which_are'),
        (r'mark\s+all\s+(?:correct|that\s+apply)', 0.90, 'mark_all'),
        # Answer format indicators
        (r'(?:correct\s+)?answers?\s*[:=]\s*[A-D]\s*,\s*[A-D]', 0.95, 'multiple_answer_format'),
        (r'(?:correct\s+)?answers?\s*[:=]\s*\([A-D],\s*[A-D]', 0.95, 'multiple_answer_parens'),
    ]
    
    TRUE_FALSE_INDICATORS = [
        # Explicit T/F format
        (r'\btrue\s+or\s+false\b', 0.95, 'true_or_false'),
        (r'\bT\s*/\s*F\b', 0.95, 't_slash_f'),
        (r'\(T/F\)', 0.95, 't_f_parens'),
        (r'\[True/False\]', 0.95, 'true_false_brackets'),
        # Statement verification
        (r'state\s+(?:whether|if)\s+.*(?:true|false)', 0.85, 'state_whether'),
        (r'is\s+(?:this|the\s+(?:statement|following))\s+(?:true|false)', 0.85, 'is_true_false'),
        (r'correct\s+or\s+incorrect', 0.80, 'correct_incorrect'),
        (r'right\s+or\s+wrong', 0.75, 'right_wrong'),
        # Option patterns (exactly 2 options: True/False)
        (r'^\s*\(?[Aa]\)?\s*True\s*$.*^\s*\(?[Bb]\)?\s*False\s*$', 0.90, 'tf_options'),
    ]
    
    FILL_BLANK_INDICATORS = [
        # Blank patterns
        (r'_{3,}', 0.95, 'underscores'),
        (r'_+\s*_+', 0.90, 'multiple_underscores'),
        (r'\[blank\]', 0.95, 'blank_bracket'),
        (r'\[___+\]', 0.95, 'underscore_bracket'),
        (r'\(\s*\)', 0.80, 'empty_parens'),
        (r'\.{3,}', 0.70, 'dots'),
        # Instruction patterns
        (r'fill\s+in\s+the\s+blank', 0.95, 'fill_instruction'),
        (r'complete\s+the\s+(?:sentence|statement|blank)', 0.90, 'complete_instruction'),
        (r'supply\s+the\s+(?:missing|correct)\s+(?:word|term)', 0.85, 'supply_instruction'),
    ]
    
    NUMERICAL_INDICATORS = [
        # Calculation instructions
        (r'calculate\s+(?:the\s+)?(?:value|area|volume|distance|speed|time)', 0.90, 'calculate'),
        (r'find\s+(?:the\s+)?(?:value|area|volume|distance|speed|time|result)', 0.85, 'find_value'),
        (r'compute\s+(?:the\s+)?', 0.85, 'compute'),
        (r'evaluate\s+(?:the\s+)?', 0.80, 'evaluate'),
        (r'determine\s+(?:the\s+)?(?:value|magnitude)', 0.80, 'determine'),
        (r'what\s+is\s+the\s+(?:value|result|answer)', 0.75, 'what_is_value'),
        # Answer format
        (r'(?:answer|ans|result)\s*[:=]\s*[\d\.\-\+]+', 0.90, 'numeric_answer'),
        (r'(?:answer|ans)\s*[:=]\s*[\d\.\-\+]+\s*(?:cm|m|kg|s|N|J|W)', 0.95, 'numeric_with_unit'),
        # Tolerance indicators
        (r'(?:tolerance|error|range)\s*[:=]?\s*[±\+\-]?\s*[\d\.]+', 0.85, 'tolerance'),
        (r'correct\s+(?:to|up\s+to)\s+\d+\s+decimal', 0.80, 'decimal_precision'),
    ]
    
    SUBJECTIVE_INDICATORS = [
        # Explanation requests
        (r'explain\s+(?:why|how|the|in\s+detail)', 0.90, 'explain'),
        (r'describe\s+(?:the|in\s+detail|briefly)', 0.90, 'describe'),
        (r'discuss\s+(?:the|in\s+detail|briefly)', 0.90, 'discuss'),
        (r'elaborate\s+(?:on|the)', 0.85, 'elaborate'),
        (r'justify\s+(?:your|the)', 0.85, 'justify'),
        (r'analyze\s+(?:the|and)', 0.80, 'analyze'),
        (r'compare\s+and\s+contrast', 0.85, 'compare_contrast'),
        # Writing instructions
        (r'write\s+(?:a\s+)?(?:short\s+)?(?:note|essay|paragraph|answer)', 0.90, 'write'),
        (r'give\s+(?:a\s+)?(?:detailed|brief)\s+(?:account|explanation)', 0.85, 'give_account'),
        # Word/mark limits
        (r'\(\s*\d+\s*(?:words?|marks?)\s*\)', 0.80, 'word_limit'),
        (r'(?:in\s+)?(?:about\s+)?\d+[-–]\d+\s*words?', 0.80, 'word_range'),
        (r'(?:not\s+)?(?:more|less)\s+than\s+\d+\s*words?', 0.80, 'word_constraint'),
    ]
    
    SINGLE_MCQ_INDICATORS = [
        # Explicit single answer
        (r'choose\s+(?:the\s+)?(?:correct|best|right)\s+(?:answer|option)', 0.80, 'choose_correct'),
        (r'select\s+(?:the\s+)?(?:correct|best|right)\s+(?:answer|option)', 0.80, 'select_correct'),
        (r'which\s+(?:one\s+)?(?:of\s+the\s+following)\s+is\s+(?:correct|true)', 0.85, 'which_one'),
        (r'the\s+(?:correct|right)\s+(?:answer|option)\s+is', 0.80, 'correct_answer_is'),
        # Single answer format
        (r'(?:correct\s+)?answer\s*[:=]\s*\(?[A-Da-d]\)?(?:\s|$|\.)', 0.85, 'single_answer_format'),
    ]
    
    def classify(
        self, 
        question_text: str, 
        options: List[str] = None, 
        correct_answer: str = None,
        ai_suggested_type: str = None
    ) -> ClassificationResult:
        """
        Classify question type with confidence score
        
        Args:
            question_text: The question text
            options: List of answer options (for MCQ)
            correct_answer: The correct answer
            ai_suggested_type: Type suggested by AI (if any)
            
        Returns:
            ClassificationResult with type, confidence, and reasoning
        """
        options = options or []
        correct_answer = correct_answer or ''
        
        # Calculate scores for each type
        scores = {
            'single_mcq': self._score_single_mcq(question_text, options, correct_answer),
            'multiple_mcq': self._score_multiple_mcq(question_text, options, correct_answer),
            'true_false': self._score_true_false(question_text, options, correct_answer),
            'fill_blank': self._score_fill_blank(question_text, options, correct_answer),
            'numerical': self._score_numerical(question_text, options, correct_answer),
            'subjective': self._score_subjective(question_text, options, correct_answer),
        }
        
        # Get best match
        best_type = max(scores, key=lambda k: scores[k][0])
        best_score, indicators = scores[best_type]
        
        # If AI suggested a type and our confidence is low, consider it
        if ai_suggested_type and best_score < 0.6:
            ai_score = scores.get(ai_suggested_type, (0, []))[0]
            if ai_score > 0.3:  # AI suggestion has some support
                best_type = ai_suggested_type
                best_score = max(ai_score, 0.5)  # Boost confidence slightly
                indicators = scores[ai_suggested_type][1]
        
        # Build reasoning
        reasoning = self._build_reasoning(best_type, indicators, scores)
        
        return ClassificationResult(
            question_type=best_type,
            confidence=best_score,
            reasoning=reasoning,
            indicators_found=indicators
        )
    
    def _score_multiple_mcq(
        self, 
        text: str, 
        options: List[str], 
        answer: str
    ) -> Tuple[float, List[str]]:
        """Score likelihood of being multiple correct MCQ"""
        score = 0.0
        indicators = []
        
        # Check text patterns
        for pattern, weight, indicator in self.MULTIPLE_MCQ_INDICATORS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                score = max(score, weight)
                indicators.append(indicator)
        
        # Check if answer contains multiple options
        if answer:
            # Multiple letters in answer
            answer_letters = re.findall(r'[A-Da-d]', answer)
            if len(answer_letters) > 1:
                score = max(score, 0.90)
                indicators.append('multiple_letters_in_answer')
            
            # Comma-separated answers
            if ',' in answer and re.search(r'[A-Da-d]\s*,\s*[A-Da-d]', answer):
                score = max(score, 0.95)
                indicators.append('comma_separated_answers')
            
            # "and" between options
            if re.search(r'[A-Da-d]\s+and\s+[A-Da-d]', answer, re.IGNORECASE):
                score = max(score, 0.90)
                indicators.append('and_between_answers')
        
        # Must have options to be MCQ
        if not options or len(options) < 2:
            score *= 0.3
        
        return score, indicators
    
    def _score_true_false(
        self, 
        text: str, 
        options: List[str], 
        answer: str
    ) -> Tuple[float, List[str]]:
        """Score likelihood of being true/false question"""
        score = 0.0
        indicators = []
        
        # Check text patterns
        for pattern, weight, indicator in self.TRUE_FALSE_INDICATORS:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                score = max(score, weight)
                indicators.append(indicator)
        
        # Check options
        if options:
            options_lower = [o.lower().strip() for o in options]
            
            # Exactly 2 options
            if len(options) == 2:
                # Check if options are True/False variants
                tf_variants = [
                    ('true', 'false'),
                    ('t', 'f'),
                    ('yes', 'no'),
                    ('correct', 'incorrect'),
                    ('right', 'wrong'),
                ]
                
                for true_var, false_var in tf_variants:
                    if (true_var in options_lower[0] and false_var in options_lower[1]) or \
                       (false_var in options_lower[0] and true_var in options_lower[1]):
                        score = max(score, 0.95)
                        indicators.append(f'options_are_{true_var}_{false_var}')
                        break
        
        # Check answer
        if answer:
            answer_lower = answer.lower().strip()
            if answer_lower in ['true', 'false', 't', 'f', 'yes', 'no']:
                score = max(score, 0.85)
                indicators.append('answer_is_boolean')
        
        return score, indicators
    
    def _score_fill_blank(
        self, 
        text: str, 
        options: List[str], 
        answer: str
    ) -> Tuple[float, List[str]]:
        """Score likelihood of being fill in the blank"""
        score = 0.0
        indicators = []
        
        # Check text patterns
        for pattern, weight, indicator in self.FILL_BLANK_INDICATORS:
            if re.search(pattern, text, re.IGNORECASE):
                score = max(score, weight)
                indicators.append(indicator)
        
        # Count blanks
        blank_count = len(re.findall(r'_{3,}|\[blank\]|\[___+\]', text, re.IGNORECASE))
        if blank_count > 0:
            score = max(score, 0.90)
            indicators.append(f'{blank_count}_blanks_found')
        
        # Fill in blank usually doesn't have MCQ options
        if options and len(options) >= 4:
            score *= 0.5  # Reduce score if has many options
        
        return score, indicators
    
    def _score_numerical(
        self, 
        text: str, 
        options: List[str], 
        answer: str
    ) -> Tuple[float, List[str]]:
        """Score likelihood of being numerical question"""
        score = 0.0
        indicators = []
        
        # Check text patterns
        for pattern, weight, indicator in self.NUMERICAL_INDICATORS:
            if re.search(pattern, text, re.IGNORECASE):
                score = max(score, weight)
                indicators.append(indicator)
        
        # Check if answer is numeric
        if answer:
            # Remove units and whitespace
            clean_answer = re.sub(r'[a-zA-Z\s]+$', '', answer.strip())
            try:
                float(clean_answer.replace(',', ''))
                score = max(score, 0.85)
                indicators.append('numeric_answer')
            except ValueError:
                pass
            
            # Check for scientific notation
            if re.match(r'^[\d\.\-\+]+\s*[×x]\s*10\^?[\d\-\+]+', answer):
                score = max(score, 0.90)
                indicators.append('scientific_notation')
            
            # Check for units
            if re.search(r'\d+\s*(?:cm|m|km|kg|g|s|min|hr|N|J|W|V|A|Ω|Hz|Pa|mol|L|mL)', answer):
                score = max(score, 0.85)
                indicators.append('has_units')
        
        # Numerical questions typically don't have MCQ options
        if options and len(options) >= 3:
            score *= 0.4
        
        return score, indicators
    
    def _score_subjective(
        self, 
        text: str, 
        options: List[str], 
        answer: str
    ) -> Tuple[float, List[str]]:
        """Score likelihood of being subjective question"""
        score = 0.0
        indicators = []
        
        # Check text patterns
        for pattern, weight, indicator in self.SUBJECTIVE_INDICATORS:
            if re.search(pattern, text, re.IGNORECASE):
                score = max(score, weight)
                indicators.append(indicator)
        
        # Check answer length (subjective answers are usually longer)
        if answer and len(answer) > 100:
            score = max(score, 0.70)
            indicators.append('long_answer')
        
        # Subjective questions typically don't have MCQ options
        if not options or len(options) == 0:
            score = max(score, 0.50)
            indicators.append('no_options')
        elif len(options) >= 3:
            score *= 0.3  # Reduce if has MCQ options
        
        return score, indicators
    
    def _score_single_mcq(
        self, 
        text: str, 
        options: List[str], 
        answer: str
    ) -> Tuple[float, List[str]]:
        """Score likelihood of being single correct MCQ"""
        score = 0.0
        indicators = []
        
        # Check text patterns
        for pattern, weight, indicator in self.SINGLE_MCQ_INDICATORS:
            if re.search(pattern, text, re.IGNORECASE):
                score = max(score, weight)
                indicators.append(indicator)
        
        # Must have options
        if options and len(options) >= 2:
            score = max(score, 0.60)
            indicators.append(f'{len(options)}_options')
            
            # Typical MCQ has 4 options
            if len(options) == 4:
                score = max(score, 0.70)
                indicators.append('standard_4_options')
        else:
            score *= 0.2  # Very unlikely without options
        
        # Check answer format
        if answer:
            # Single letter answer
            if re.match(r'^[A-Da-d]$', answer.strip()):
                score = max(score, 0.85)
                indicators.append('single_letter_answer')
            
            # Answer matches one option
            if options and answer.strip() in options:
                score = max(score, 0.80)
                indicators.append('answer_in_options')
        
        # Reduce score if multiple_mcq indicators are strong
        # (This is handled by comparing scores later)
        
        return score, indicators
    
    def _build_reasoning(
        self, 
        best_type: str, 
        indicators: List[str], 
        all_scores: Dict
    ) -> str:
        """Build human-readable reasoning for classification"""
        type_names = {
            'single_mcq': 'Single Correct MCQ',
            'multiple_mcq': 'Multiple Correct MCQ',
            'true_false': 'True/False',
            'fill_blank': 'Fill in the Blank',
            'numerical': 'Numerical',
            'subjective': 'Subjective',
        }
        
        reasoning_parts = [f"Classified as {type_names.get(best_type, best_type)}"]
        
        if indicators:
            reasoning_parts.append(f"Indicators: {', '.join(indicators[:3])}")
        
        # Show competing types if close
        sorted_scores = sorted(all_scores.items(), key=lambda x: x[1][0], reverse=True)
        if len(sorted_scores) > 1:
            second_type, (second_score, _) = sorted_scores[1]
            best_score = all_scores[best_type][0]
            if second_score > 0.5 and (best_score - second_score) < 0.2:
                reasoning_parts.append(
                    f"Also considered: {type_names.get(second_type, second_type)} "
                    f"({second_score:.0%})"
                )
        
        return ". ".join(reasoning_parts)
    
    def classify_batch(
        self, 
        questions: List[Dict]
    ) -> List[ClassificationResult]:
        """
        Classify multiple questions
        
        Args:
            questions: List of question dicts with 'question_text', 'options', 'correct_answer'
            
        Returns:
            List of ClassificationResult
        """
        results = []
        for q in questions:
            result = self.classify(
                question_text=q.get('question_text', ''),
                options=q.get('options', []),
                correct_answer=q.get('correct_answer', ''),
                ai_suggested_type=q.get('question_type')
            )
            results.append(result)
        return results
