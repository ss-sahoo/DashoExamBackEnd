"""
Document Pre-Analysis Service
AI-powered document analysis to determine document type, detect subjects,
and separate questions by subject before extraction.
"""
import json
import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from django.conf import settings

logger = logging.getLogger('extraction')


class DocumentPreAnalysisError(Exception):
    """Raised when document pre-analysis fails"""
    pass


@dataclass
class DocumentSection:
    """Represents a detected section in the document"""
    name: str  # Section name as it appears in the document
    type_hint: str  # Detected type (single_mcq, multiple_mcq, numerical, etc.)
    question_range: str  # e.g., "1-20" or "Q1-Q20"
    format_description: str  # How questions are formatted in this section
    start_marker: str  # Text that marks the start of this section
    

@dataclass
class DocumentStructure:
    """Detected structure of the document"""
    has_instructions: bool
    instructions_text: str  # Header/rules text at the top
    sections: List[Dict]  # List of detected sections
    question_numbering_format: str  # e.g., "Q1.", "1.", "(1)", etc.
    answer_format: str  # How answers are marked
    total_sections: int


@dataclass
class PreAnalysisResult:
    """Result of document pre-analysis"""
    is_valid: bool
    document_type: str  # 'questions_with_answers', 'questions_only', 'other'
    document_type_display: str
    confidence: float
    detected_subjects: List[str]
    matched_subjects: List[str]
    unmatched_subjects: List[str]
    subject_question_counts: Dict[str, int]
    subject_separated_content: Dict[str, str]
    total_estimated_questions: int
    # New: Document structure information
    document_structure: Optional[Dict] = None
    error_message: Optional[str] = None
    reason: Optional[str] = None


class DocumentPreAnalyzer:
    """
    AI-powered document pre-analysis service.
    Analyzes uploaded documents before extraction to:
    - Determine document type (questions with answers, questions only, other)
    - Detect subjects present in the document
    - Match subjects against exam pattern's configured subjects
    - Separate questions by subject
    """
    
    DOCUMENT_TYPES = {
        'questions_with_answers': 'Questions with Answers',
        'questions_only': 'Questions Only',
        'other': 'Other'
    }
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the document pre-analyzer"""
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
        
        if not self.api_key:
            raise DocumentPreAnalysisError("Gemini API key not configured")
        
        # Initialize Gemini client
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
            self.genai = genai
        except ImportError:
            raise DocumentPreAnalysisError(
                "google-generativeai library not installed. "
                "Run: pip install google-generativeai"
            )
        except Exception as e:
            raise DocumentPreAnalysisError(f"Failed to initialize Gemini client: {str(e)}")

    def analyze_document(
        self,
        text_content: str,
        pattern_subjects: List[str]
    ) -> PreAnalysisResult:
        """
        Perform comprehensive document pre-analysis
        
        Args:
            text_content: Raw text from document
            pattern_subjects: List of subjects configured in the exam pattern
            
        Returns:
            PreAnalysisResult with document type, detected subjects, and question counts
        """
        logger.info("Starting document pre-analysis...")
        
        try:
            # Step 1: Detect document type
            doc_type_result = self.detect_document_type(text_content)
            
            if doc_type_result['document_type'] == 'other':
                return PreAnalysisResult(
                    is_valid=False,
                    document_type='other',
                    document_type_display=self.DOCUMENT_TYPES['other'],
                    confidence=doc_type_result['confidence'],
                    detected_subjects=[],
                    matched_subjects=[],
                    unmatched_subjects=[],
                    subject_question_counts={},
                    subject_separated_content={},
                    total_estimated_questions=0,
                    error_message="This document does not contain questions. Please upload a valid question bank file.",
                    reason=doc_type_result.get('reason', 'Document does not appear to contain questions')
                )
            
            # Step 2: Detect subjects in the document
            subject_result = self.detect_subjects(text_content, pattern_subjects)
            
            # Step 3: Separate content by subject
            separated_content = {}
            if len(subject_result['matched_subjects']) > 1:
                separated_content = self.separate_by_subject(
                    text_content, 
                    subject_result['matched_subjects']
                )
            elif len(subject_result['matched_subjects']) == 1:
                # Single subject - all content belongs to it
                separated_content = {subject_result['matched_subjects'][0]: text_content}
            elif len(subject_result['detected_subjects']) > 0:
                # Use detected subjects even if not matched
                separated_content = self.separate_by_subject(
                    text_content,
                    subject_result['detected_subjects']
                )
            else:
                # No subjects detected - treat as single subject
                separated_content = {'General': text_content}
            
            # CRITICAL: Re-count questions in SEPARATED content (not initial AI estimate)
            # This ensures we pass the correct count to the extraction pipeline
            accurate_counts = self._count_questions_in_separated_content(separated_content)
            logger.info(f"Accurate question counts from separated content: {accurate_counts}")
            
            # Use accurate counts instead of initial AI estimate
            if accurate_counts:
                subject_question_counts = accurate_counts
                total_questions = sum(accurate_counts.values())
            else:
                # Fallback to AI estimate if counting fails
                subject_question_counts = subject_result['subject_question_counts']
                total_questions = sum(subject_question_counts.values())
            
            # Step 4: AI-powered document structure detection
            # Analyzes the document to detect sections, question types, and structure
            logger.info("Step 4: Detecting document structure with AI...")
            document_structure = self.detect_document_structure_ai(text_content)
            
            # ENSURE UNIQUE subjects before returning (safety net)
            unique_detected = list(dict.fromkeys(subject_result['detected_subjects']))
            unique_matched = list(dict.fromkeys(subject_result['matched_subjects']))
            unique_unmatched = list(dict.fromkeys(subject_result['unmatched_subjects']))
            
            logger.info(f"Final subjects - detected: {unique_detected}, matched: {unique_matched}")
            
            return PreAnalysisResult(
                is_valid=True,
                document_type=doc_type_result['document_type'],
                document_type_display=self.DOCUMENT_TYPES[doc_type_result['document_type']],
                confidence=doc_type_result['confidence'],
                detected_subjects=unique_detected,
                matched_subjects=unique_matched,
                unmatched_subjects=unique_unmatched,
                subject_question_counts=subject_question_counts,  # Use accurate counts
                subject_separated_content=separated_content,
                total_estimated_questions=total_questions,
                document_structure=document_structure,
                reason=doc_type_result.get('reason')
            )
            
        except Exception as e:
            logger.error(f"Document pre-analysis failed: {str(e)}", exc_info=True)
            raise DocumentPreAnalysisError(f"Failed to analyze document: {str(e)}")
    
    def detect_document_type(self, text_content: str) -> Dict:
        """
        Classify document as one of:
        - "questions_with_answers": Contains questions and their answers/solutions
        - "questions_only": Contains only questions without answers
        - "other": Not a question document
        
        Returns:
            {
                "document_type": str,
                "is_valid_question_document": bool,
                "confidence": float,
                "reason": str
            }
        """
        prompt = self._build_document_type_prompt(text_content)
        
        try:
            response = self._call_gemini(prompt)
            result = self._parse_document_type_response(response)
            
            logger.info(
                f"Document type detected: {result['document_type']} "
                f"(confidence: {result['confidence']:.2f})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Document type detection failed: {e}")
            # Fallback to regex-based detection
            return self._fallback_document_type_detection(text_content)
    
    def detect_document_structure_ai(self, text_content: str) -> Dict:
        """
        AI-powered document structure detection.
        Works with ANY document format - no predefined structure assumed.
        
        The AI analyzes:
        1. Instructions/marking scheme (if present)
        2. How questions are numbered/formatted
        3. Question types by analyzing actual question content
        4. Logical groupings/sections based on content analysis
        
        Returns:
            {
                "has_instructions": bool,
                "instructions_text": str,
                "marking_scheme": {...},
                "sections": [
                    {
                        "name": str,
                        "type_hint": str,  # single_mcq, multiple_mcq, numerical, etc.
                        "question_range": str,  # "1-20" or "Q1-Q20"
                        "question_count": int,
                        "format_description": str,
                        "marks_per_question": float or null,
                        "negative_marking": float or null,
                    }
                ],
                "question_numbering_format": str,
                "answer_format": str,
                "total_sections": int,
                "total_questions_detected": int
            }
        """
        logger.info("Running AI-powered document structure detection...")
        logger.info(f"Document length: {len(text_content)} characters")
        
        try:
            # Build comprehensive prompt for structure analysis
            prompt = self._build_ai_structure_prompt(text_content)
            logger.info(f"Prompt built, length: {len(prompt)} characters")
            
            # Call Gemini with larger token limit for detailed analysis
            response = self._call_gemini(prompt, max_tokens=8192)
            logger.info(f"AI response received, length: {len(response)} characters")
            logger.debug(f"AI response preview: {response[:500]}...")
            
            # Parse the response
            structure = self._parse_ai_structure_response(response)
            
            logger.info(
                f"AI detected {structure.get('total_sections', 0)} sections, "
                f"{structure.get('total_questions_detected', 0)} questions"
            )
            logger.info(f"Detected sections: {[s.get('name') for s in structure.get('sections', [])]}")
            
            return structure
            
        except Exception as e:
            logger.error(f"AI structure detection failed: {e}", exc_info=True)
            # Try fallback regex-based detection
            logger.info("Using fallback regex-based structure detection...")
            return self._fallback_structure_detection(text_content)
    
    def _build_ai_structure_prompt(self, text_content: str) -> str:
        """
        Build a comprehensive prompt for AI to analyze document structure.
        Works with ANY document format globally.
        """
        # Sample document intelligently
        text_len = len(text_content)
        
        if text_len <= 30000:
            sample_text = text_content
        else:
            # Large document - sample strategically
            # Beginning (instructions usually here)
            beginning = text_content[:10000]
            
            # Middle samples (catch section transitions)
            third = text_len // 3
            two_thirds = (2 * text_len) // 3
            
            middle1 = text_content[third - 3000:third + 3000]
            middle2 = text_content[two_thirds - 3000:two_thirds + 3000]
            
            # End (sometimes has different sections)
            end = text_content[-8000:]
            
            sample_text = f"""{beginning}

[... DOCUMENT CONTINUES - SAMPLE FROM 1/3 POSITION ...]

{middle1}

[... DOCUMENT CONTINUES - SAMPLE FROM 2/3 POSITION ...]

{middle2}

[... END OF DOCUMENT ...]

{end}"""

        return f"""You are an expert at analyzing exam/test documents from ANY country, in ANY format.

**YOUR TASK:** Analyze this document and detect its structure WITHOUT assuming any predefined format.

**ANALYSIS STEPS:**

1. **SCAN FOR INSTRUCTIONS** (first few paragraphs)
   - Look for exam rules, time limits, marking schemes
   - Extract any "+X marks for correct, -Y marks for wrong" patterns
   - Note any special instructions

2. **IDENTIFY QUESTION NUMBERING**
   - How are questions numbered? (1., Q1, (1), i., etc.)
   - Are there sub-questions? (1a, 1b or 1.1, 1.2)

3. **ANALYZE EACH QUESTION TYPE** by looking at actual questions:
   - Has 4 options A/B/C/D with single answer → single_mcq
   - Has options with multiple correct answers → multiple_mcq  
   - Asks to calculate/find numerical value → numerical
   - True/False or T/F → true_false
   - Has blanks ___ to fill → fill_blank
   - Asks to explain/describe/discuss → subjective
   - Matrix/matching columns → match_following
   - Assertion-Reason format → assertion_reason
   - Based on a passage/paragraph → comprehension

4. **DETECT SECTIONS** by finding:
   - Explicit headers (Section A, Part 1, भाग-क, etc.)
   - OR group questions by type if no explicit sections
   - Consecutive questions of same type = one section

5. **COUNT QUESTIONS** in each detected section

**OUTPUT FORMAT (JSON only):**
```json
{{
    "has_instructions": true,
    "instructions_text": "Brief summary of instructions found (max 200 chars)",
    "marking_scheme": {{
        "correct_marks": 4,
        "negative_marks": -1,
        "partial_marks": null,
        "description": "+4 for correct, -1 for wrong"
    }},
    "sections": [
        {{
            "name": "Section name as found in document OR auto-generated",
            "type_hint": "single_mcq",
            "question_range": "1-20",
            "question_count": 20,
            "format_description": "4 options (A-D), single correct",
            "marks_per_question": 4,
            "negative_marking": -1
        }}
    ],
    "question_numbering_format": "1., 2., 3...",
    "answer_format": "Answer marked after each question",
    "total_sections": 3,
    "total_questions_detected": 75
}}
```

**IMPORTANT RULES:**
- Do NOT assume standard formats - detect from actual content
- If no clear section headers exist, group by question TYPE
- A section = consecutive questions of the SAME type
- Works for documents in ANY language
- If unsure about a section, mark type_hint as "mixed"
- Count actual questions, don't guess

**DOCUMENT TO ANALYZE:**
{sample_text}

**Respond with JSON only:**"""

    def _parse_ai_structure_response(self, response: str) -> Dict:
        """Parse AI response for document structure detection"""
        default_structure = {
            'has_instructions': False,
            'instructions_text': '',
            'marking_scheme': {},
            'sections': [],
            'question_numbering_format': 'auto-detect',
            'answer_format': 'auto-detect',
            'total_sections': 0,
            'total_questions_detected': 0
        }
        
        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                logger.info("Found JSON in ```json``` block")
            else:
                # Try to find JSON object directly
                json_match = re.search(r'\{[\s\S]*"sections"[\s\S]*\}', response)
                if json_match:
                    json_str = json_match.group(0)
                    logger.info("Found JSON object directly in response")
                else:
                    logger.warning(f"Could not find JSON in AI response. Response preview: {response[:300]}")
                    return default_structure
            
            logger.info(f"Parsing JSON string of length: {len(json_str)}")
            result = json.loads(json_str)
            logger.info(f"Parsed JSON successfully. Keys: {list(result.keys())}")
            
            # Validate and normalize sections
            sections = result.get('sections', [])
            valid_sections = []
            
            for section in sections:
                if isinstance(section, dict):
                    # Normalize type_hint to our standard types
                    type_hint = section.get('type_hint', 'mixed')
                    type_hint = self._normalize_question_type(type_hint)
                    
                    valid_sections.append({
                        'name': section.get('name', 'Section'),
                        'type_hint': type_hint,
                        'question_range': section.get('question_range', 'Unknown'),
                        'question_count': section.get('question_count', 0),
                        'format_description': section.get('format_description', ''),
                        'marks_per_question': section.get('marks_per_question'),
                        'negative_marking': section.get('negative_marking'),
                    })
            
            # Build final structure
            structure = {
                'has_instructions': result.get('has_instructions', False),
                'instructions_text': str(result.get('instructions_text', ''))[:500],
                'marking_scheme': result.get('marking_scheme', {}),
                'sections': valid_sections,
                'question_numbering_format': result.get('question_numbering_format', 'auto-detect'),
                'answer_format': result.get('answer_format', 'auto-detect'),
                'total_sections': len(valid_sections),
                'total_questions_detected': result.get('total_questions_detected', 0)
            }
            
            # Calculate total questions from sections if not provided
            if structure['total_questions_detected'] == 0:
                structure['total_questions_detected'] = sum(
                    s.get('question_count', 0) for s in valid_sections
                )
            
            return structure
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in AI structure response: {e}")
            return default_structure
        except Exception as e:
            logger.error(f"Error parsing AI structure response: {e}")
            return default_structure
    
    def _normalize_question_type(self, type_hint: str) -> str:
        """Normalize various question type names to standard types"""
        if not type_hint:
            return 'mixed'
        
        type_lower = type_hint.lower().strip()
        
        # Map various names to standard types
        type_mapping = {
            # Single MCQ variants
            'single_mcq': 'single_mcq',
            'single mcq': 'single_mcq',
            'single correct': 'single_mcq',
            'mcq': 'single_mcq',
            'multiple choice': 'single_mcq',
            'objective': 'single_mcq',
            
            # Multiple MCQ variants
            'multiple_mcq': 'multiple_mcq',
            'multiple mcq': 'multiple_mcq',
            'multiple correct': 'multiple_mcq',
            'multi correct': 'multiple_mcq',
            'more than one': 'multiple_mcq',
            
            # Numerical variants
            'numerical': 'numerical',
            'integer': 'numerical',
            'integer type': 'numerical',
            'numerical type': 'numerical',
            'calculation': 'numerical',
            'numeric': 'numerical',
            
            # True/False variants
            'true_false': 'true_false',
            'true false': 'true_false',
            'true/false': 'true_false',
            't/f': 'true_false',
            'boolean': 'true_false',
            
            # Fill in blanks variants
            'fill_blank': 'fill_blank',
            'fill blank': 'fill_blank',
            'fill in the blank': 'fill_blank',
            'fill in the blanks': 'fill_blank',
            'blanks': 'fill_blank',
            
            # Subjective variants
            'subjective': 'subjective',
            'descriptive': 'subjective',
            'long answer': 'subjective',
            'essay': 'subjective',
            'short answer': 'subjective',
            'written': 'subjective',
            
            # Match variants
            'match_following': 'match_following',
            'match': 'match_following',
            'matching': 'match_following',
            'matrix': 'match_following',
            'matrix match': 'match_following',
            
            # Assertion-Reason
            'assertion_reason': 'assertion_reason',
            'assertion': 'assertion_reason',
            'assertion-reason': 'assertion_reason',
            
            # Comprehension
            'comprehension': 'comprehension',
            'passage': 'comprehension',
            'passage based': 'comprehension',
            'reading': 'comprehension',
            
            # Mixed/Unknown
            'mixed': 'mixed',
            'general': 'mixed',
            'unknown': 'mixed',
        }
        
        return type_mapping.get(type_lower, 'mixed')

    def detect_document_structure(self, text_content: str) -> Dict:
        """
        Detect the structure of the document including:
        - Instructions/rules at the top
        - Different sections (MCQ, Numerical, True/False, Match, etc.)
        - Question numbering format
        - Answer format
        
        Returns:
            {
                "has_instructions": bool,
                "instructions_text": str,
                "sections": [
                    {
                        "name": "Section A - Single Correct MCQ",
                        "type_hint": "single_mcq",
                        "question_range": "1-20",
                        "format_description": "4 options (A-D), single correct answer",
                        "start_marker": "SECTION A"
                    },
                    ...
                ],
                "question_numbering_format": "Q1., Q2., ...",
                "answer_format": "Answer: A",
                "total_sections": int
            }
        """
        logger.info("Detecting document structure...")
        
        try:
            # Use AI to detect structure
            prompt = self._build_structure_detection_prompt(text_content)
            response = self._call_gemini(prompt)
            structure = self._parse_structure_response(response)
            
            logger.info(f"Detected {structure.get('total_sections', 0)} sections in document")
            
            return structure
            
        except Exception as e:
            logger.warning(f"AI structure detection failed: {e}, using fallback")
            return self._fallback_structure_detection(text_content)
    
    def _build_structure_detection_prompt(self, text_content: str) -> str:
        """Build prompt for document structure detection"""
        # Sample from ENTIRE document to detect ALL sections (not just first 10K)
        # This ensures we find sections that appear later in the document
        text_len = len(text_content)
        
        if text_len <= 20000:
            # Small document - use entire content
            sample_text = text_content
        else:
            # Large document - sample from beginning, multiple middle points, and end
            # This captures sections throughout the entire document
            beginning = text_content[:8000]
            
            # Sample from 25%, 50%, and 75% positions to catch all sections
            quarter_pos = text_len // 4
            half_pos = text_len // 2
            three_quarter_pos = (3 * text_len) // 4
            
            quarter_sample = text_content[quarter_pos - 4000:quarter_pos + 4000]
            middle_sample = text_content[half_pos - 4000:half_pos + 4000]
            three_quarter_sample = text_content[three_quarter_pos - 4000:three_quarter_pos + 4000]
            
            end = text_content[-8000:]
            
            # Combine all samples with markers
            sample_text = f"""{beginning}

[...DOCUMENT CONTINUES - SAMPLING FROM 25% POSITION...]

{quarter_sample}

[...DOCUMENT CONTINUES - SAMPLING FROM 50% POSITION...]

{middle_sample}

[...DOCUMENT CONTINUES - SAMPLING FROM 75% POSITION...]

{three_quarter_sample}

[...END OF DOCUMENT...]

{end}"""
        
        return f"""Analyze this exam/question document and detect its structure.

**CRITICAL:** This document may have sections THROUGHOUT - not just at the beginning!
I am providing samples from BEGINNING, MIDDLE (25%, 50%, 75%), and END of the document.
You MUST identify ALL sections present across the ENTIRE document.

**TASK:** Identify ALL sections and question types present in this document.

**WHAT TO LOOK FOR:**
1. Instructions or rules at the beginning of the document
2. Different sections (could be ANY type - not limited to standard types)
3. Section headers that appear ANYWHERE in the document (beginning, middle, or end)
4. Subject names like Physics, Chemistry, Mathematics, Biology, etc.
5. How questions are numbered (Q1, 1., (1), etc.)
6. How answers are marked (Answer: A, Ans: B, correct option highlighted, etc.)

**COMMON SECTION TYPES (but document may have others):**
- Single Correct MCQ (one correct answer from options)
- Multiple Correct MCQ (multiple correct answers)
- Numerical/Integer Type (answer is a number)
- True/False
- Fill in the Blanks
- Match the Following/Matrix Match
- Assertion-Reason
- Comprehension/Passage Based
- Subjective/Descriptive
- Any other custom section type

**OUTPUT FORMAT (JSON only):**
```json
{{
    "has_instructions": true,
    "instructions_text": "This paper contains 90 questions divided into 3 sections...",
    "sections": [
        {{
            "name": "Section A - Single Correct",
            "type_hint": "single_mcq",
            "question_range": "1-20",
            "format_description": "4 options (A-D), only one correct answer, +4 for correct, -1 for wrong",
            "start_marker": "SECTION A"
        }},
        {{
            "name": "Section B - Multiple Correct",
            "type_hint": "multiple_mcq",
            "question_range": "21-30",
            "format_description": "4 options, one or more correct answers",
            "start_marker": "SECTION B"
        }},
        {{
            "name": "Numerical Type",
            "type_hint": "numerical",
            "question_range": "31-35",
            "format_description": "Answer is a numerical value, no options",
            "start_marker": "NUMERICAL"
        }}
    ],
    "question_numbering_format": "Q1., Q2., Q3...",
    "answer_format": "Answer: (A)",
    "total_sections": 3
}}
```

**IMPORTANT:**
- Detect ALL sections present, not just common ones
- Use the EXACT section names as they appear in the document
- If no clear sections, return a single "General" section
- Include any marking scheme or rules mentioned

**DOCUMENT:**
{sample_text}

**Analyze and respond with JSON only:**"""

    def _parse_structure_response(self, response: str) -> Dict:
        """Parse Gemini response for document structure"""
        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON object
                json_match = re.search(r'\{.*"sections".*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            result = json.loads(json_str)
            
            # Ensure required fields exist
            if 'sections' not in result:
                result['sections'] = []
            if 'has_instructions' not in result:
                result['has_instructions'] = False
            if 'instructions_text' not in result:
                result['instructions_text'] = ''
            if 'total_sections' not in result:
                result['total_sections'] = len(result['sections'])
            if 'question_numbering_format' not in result:
                result['question_numbering_format'] = 'Unknown'
            if 'answer_format' not in result:
                result['answer_format'] = 'Unknown'
            
            return result
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse structure response: {e}")
            return self._fallback_structure_detection('')
    
    def _fallback_structure_detection(self, text_content: str) -> Dict:
        """Fallback regex-based structure detection"""
        structure = {
            'has_instructions': False,
            'instructions_text': '',
            'sections': [],
            'question_numbering_format': 'Unknown',
            'answer_format': 'Unknown',
            'total_sections': 0
        }
        
        # Get header text for instruction detection
        header_text = text_content[:5000]
        
        # Detect instructions at the top - improved patterns
        instructions_patterns = [
            # Section header followed by MCQ description (most common in JEE/NEET)
            r'(##?\s*SECTION\s*[-–:]?\s*[A-Za-z0-9]*.+?(?:Multiple Choice|MCQ|single correct|ONLY ONE|one correct).+?)(?=\d+\.\s)',
            # Direct MCQ instruction text  
            r'(Multiple Choice Questions?:?.+?(?:correct|ONLY ONE|single answer).+?)(?=##|\d+\.\s)',
            # Choose the correct answer block
            r'(##?\s*Choose the correct.+?)(?=\d+\.\s)',
            # Instructions keyword  
            r'(.*?(?:instructions|rules|note|important).*?)(?=\d+\.\s)',
            # Marks/marking scheme
            r'(.*?(?:marks|marking scheme|negative marking).*?)(?=\d+\.\s)',
        ]
        
        for pattern in instructions_patterns:
            match = re.search(pattern, header_text, re.IGNORECASE | re.DOTALL)
            if match:
                instructions = match.group(1).strip()
                if len(instructions) > 30:  # Meaningful instruction length
                    structure['has_instructions'] = True
                    structure['instructions_text'] = instructions[:500]
                    logger.info(f"Fallback found instructions: {instructions[:100]}...")
                    break
        
        # Detect sections
        section_patterns = [
            r'(?:^|\n)\s*(SECTION\s*[A-Z][\s:-]*[^\n]*)',
            r'(?:^|\n)\s*(Part\s*[A-Z0-9][\s:-]*[^\n]*)',
            r'(?:^|\n)\s*[-=]+\s*([^\n]+(?:MCQ|Numerical|True|False|Match|Assertion|Comprehension)[^\n]*)\s*[-=]+',
        ]
        
        detected_sections = []
        for pattern in section_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            for match in matches:
                section_name = match.strip()
                if section_name and len(section_name) < 100:
                    # Determine type hint
                    type_hint = self._guess_section_type(section_name)
                    detected_sections.append({
                        'name': section_name,
                        'type_hint': type_hint,
                        'question_range': 'Unknown',
                        'format_description': '',
                        'start_marker': section_name[:30]
                    })
        
        if detected_sections:
            structure['sections'] = detected_sections
            structure['total_sections'] = len(detected_sections)
        else:
            # No sections found - create a general section
            structure['sections'] = [{
                'name': 'General',
                'type_hint': 'mixed',
                'question_range': 'All',
                'format_description': 'Mixed question types',
                'start_marker': ''
            }]
            structure['total_sections'] = 1
        
        # Detect question numbering format
        if re.search(r'Q\.\s*\d+', text_content):
            structure['question_numbering_format'] = 'Q.1, Q.2, ...'
        elif re.search(r'Q\d+', text_content):
            structure['question_numbering_format'] = 'Q1, Q2, ...'
        elif re.search(r'\(\d+\)', text_content):
            structure['question_numbering_format'] = '(1), (2), ...'
        elif re.search(r'^\s*\d+\.\s', text_content, re.MULTILINE):
            structure['question_numbering_format'] = '1., 2., ...'
        
        # Detect answer format
        if re.search(r'Answer\s*:\s*\(?[A-D]\)?', text_content, re.IGNORECASE):
            structure['answer_format'] = 'Answer: (A)'
        elif re.search(r'Ans\s*:\s*\(?[A-D]\)?', text_content, re.IGNORECASE):
            structure['answer_format'] = 'Ans: A'
        elif re.search(r'Correct\s*(?:answer|option)', text_content, re.IGNORECASE):
            structure['answer_format'] = 'Correct answer marked'
        
        return structure
    
    def _guess_section_type(self, section_name: str) -> str:
        """Guess the section type from its name"""
        name_lower = section_name.lower()
        
        if any(kw in name_lower for kw in ['single', 'one correct', 'single correct']):
            return 'single_mcq'
        elif any(kw in name_lower for kw in ['multiple', 'multi', 'more than one']):
            return 'multiple_mcq'
        elif any(kw in name_lower for kw in ['numerical', 'integer', 'numeric']):
            return 'numerical'
        elif any(kw in name_lower for kw in ['true', 'false', 't/f']):
            return 'true_false'
        elif any(kw in name_lower for kw in ['fill', 'blank']):
            return 'fill_blank'
        elif any(kw in name_lower for kw in ['match', 'matrix', 'column']):
            return 'matching'
        elif any(kw in name_lower for kw in ['assertion', 'reason']):
            return 'assertion_reason'
        elif any(kw in name_lower for kw in ['comprehension', 'passage', 'paragraph']):
            return 'comprehension'
        elif any(kw in name_lower for kw in ['subjective', 'descriptive', 'long answer']):
            return 'subjective'
        elif any(kw in name_lower for kw in ['mcq', 'objective']):
            return 'single_mcq'
        else:
            return 'unknown'
    
    def _build_document_type_prompt(self, text_content: str) -> str:
        """Build prompt for document type detection"""
        # Limit text to first 5000 chars for type detection
        sample_text = text_content[:5000]
        
        return f"""Analyze this document and determine its type.

**TASK:** Classify this document into ONE of these categories:
1. "questions_with_answers" - Contains questions WITH answers/solutions provided
2. "questions_only" - Contains questions WITHOUT answers (just question text and options)
3. "other" - Not a question document (textbook, article, notes, etc.)

**INDICATORS:**
- Questions with answers: Has "Answer:", "Solution:", "Ans:", correct option marked, explanations
- Questions only: Has numbered questions, MCQ options, but NO answers provided
- Other: No question numbering, no MCQ options, narrative text, chapters, etc.

**OUTPUT FORMAT (JSON only):**
```json
{{
    "document_type": "questions_with_answers",
    "confidence": 0.95,
    "reason": "Document contains numbered questions with marked correct answers and solutions"
}}
```

**DOCUMENT SAMPLE:**
{sample_text}

**Analyze and respond with JSON only:**"""

    def _parse_document_type_response(self, response: str) -> Dict:
        """Parse Gemini response for document type"""
        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\{[^{}]*"document_type"[^{}]*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            result = json.loads(json_str)
            
            # Validate document_type
            doc_type = result.get('document_type', 'other').lower().replace(' ', '_')
            if doc_type not in self.DOCUMENT_TYPES:
                doc_type = 'other'
            
            return {
                'document_type': doc_type,
                'is_valid_question_document': doc_type != 'other',
                'confidence': float(result.get('confidence', 0.7)),
                'reason': result.get('reason', '')
            }
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse document type response: {e}")
            return {
                'document_type': 'other',
                'is_valid_question_document': False,
                'confidence': 0.5,
                'reason': 'Could not determine document type'
            }
    
    def _fallback_document_type_detection(self, text_content: str) -> Dict:
        """Fallback regex-based document type detection"""
        # Check for question patterns
        question_patterns = [
            r'(?:^|\n)\s*Q\.?\s*\d+',
            r'(?:^|\n)\s*Question\s+\d+',
            r'(?:^|\n)\s*\d+[\.\)]\s+[A-Z]',
        ]
        
        has_questions = any(
            re.search(p, text_content, re.IGNORECASE | re.MULTILINE)
            for p in question_patterns
        )
        
        # Check for answer patterns
        answer_patterns = [
            r'(?:Answer|Ans|Solution)[\s:]+',
            r'\([A-D]\)\s*(?:is\s+)?(?:correct|right)',
            r'Correct\s+(?:answer|option)',
        ]
        
        has_answers = any(
            re.search(p, text_content, re.IGNORECASE)
            for p in answer_patterns
        )
        
        # Check for MCQ options
        has_options = bool(re.search(
            r'(?:^|\n)\s*\(?[A-D]\)?[\.\)]\s',
            text_content,
            re.IGNORECASE | re.MULTILINE
        ))
        
        if has_questions or has_options:
            if has_answers:
                return {
                    'document_type': 'questions_with_answers',
                    'is_valid_question_document': True,
                    'confidence': 0.7,
                    'reason': 'Detected question patterns with answers'
                }
            else:
                return {
                    'document_type': 'questions_only',
                    'is_valid_question_document': True,
                    'confidence': 0.6,
                    'reason': 'Detected question patterns without answers'
                }
        
        return {
            'document_type': 'other',
            'is_valid_question_document': False,
            'confidence': 0.5,
            'reason': 'No question patterns detected'
        }
    
    def detect_subjects(
        self,
        text_content: str,
        pattern_subjects: List[str]
    ) -> Dict:
        """
        Detect subjects present in the document and match against pattern subjects
        
        Args:
            text_content: Raw text from document
            pattern_subjects: Subjects configured in exam pattern
            
        Returns:
            {
                "detected_subjects": ["Physics", "Chemistry"],
                "matched_subjects": ["Physics", "Chemistry"],
                "unmatched_subjects": [],
                "subject_question_counts": {"Physics": 25, "Chemistry": 30}
            }
        """
        prompt = self._build_subject_detection_prompt(text_content, pattern_subjects)
        
        try:
            response = self._call_gemini(prompt)
            result = self._parse_subject_detection_response(response, pattern_subjects)
            
            logger.info(
                f"Subjects detected: {result['detected_subjects']}, "
                f"matched: {result['matched_subjects']}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Subject detection failed: {e}")
            return self._fallback_subject_detection(text_content, pattern_subjects)
    
    def _build_subject_detection_prompt(
        self,
        text_content: str,
        pattern_subjects: List[str]
    ) -> str:
        """Build prompt for subject detection - uses ONLY pattern subjects"""
        if not pattern_subjects:
            # If no subjects provided, detect any subjects in the document
            subjects_instruction = "Detect any academic subjects present in this document (e.g., Physics, Chemistry, Mathematics, Biology, etc.)"
        else:
            subjects_str = ', '.join(pattern_subjects)
            subjects_instruction = f"Identify which of these subjects are present: {subjects_str}"
        
        # Sample text for analysis - use beginning, middle, and end to capture all subjects
        # This ensures we detect subjects even if they appear later in the document
        text_len = len(text_content)
        if text_len <= 15000:
            sample_text = text_content
        else:
            # Take samples from beginning, middle, and end to capture all subjects
            beginning = text_content[:5000]
            middle_start = (text_len // 2) - 2500
            middle = text_content[middle_start:middle_start + 5000]
            end = text_content[-5000:]
            sample_text = f"{beginning}\n\n[...MIDDLE OF DOCUMENT...]\n\n{middle}\n\n[...END OF DOCUMENT...]\n\n{end}"
        
        return f"""Analyze this document and identify which subjects are present.

**TASK:**
{subjects_instruction}

**INSTRUCTIONS:**
1. Look for section headers, subject names, or topic indicators in the document
2. Estimate approximately how many questions/items belong to each detected subject
3. Only include subjects that actually have content in the document
4. If no clear subject indicators, analyze the content topics to determine subject
5. Count ALL types of questions: MCQs, True/False, Fill in blanks, Numerical, Subjective, etc.

**OUTPUT FORMAT (JSON only):**
```json
{{
    "detected_subjects": ["Subject1", "Subject2"],
    "subject_question_counts": {{
        "Subject1": 25,
        "Subject2": 30
    }}
}}
```

**NOTE:** The counts are estimates - include all question types (MCQ, True/False, Fill blanks, Numerical, Subjective, etc.)

**DOCUMENT:**
{sample_text}

**Analyze and respond with JSON only:**"""

    def _parse_subject_detection_response(
        self,
        response: str,
        pattern_subjects: List[str]
    ) -> Dict:
        """Parse Gemini response for subject detection"""
        try:
            # Extract JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\{[^{}]*"detected_subjects"[^{}]*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            result = json.loads(json_str)
            
            detected = result.get('detected_subjects', [])
            counts = result.get('subject_question_counts', {})
            
            # Normalize subject names and REMOVE DUPLICATES
            detected = list(dict.fromkeys([self._normalize_subject(s) for s in detected]))
            counts = {self._normalize_subject(k): v for k, v in counts.items()}
            
            # Match against pattern subjects - UNIQUE matches only
            pattern_subjects_normalized = [self._normalize_subject(s) for s in pattern_subjects]
            matched = list(dict.fromkeys([s for s in detected if s in pattern_subjects_normalized]))
            unmatched = list(dict.fromkeys([s for s in detected if s not in pattern_subjects_normalized]))
            
            return {
                'detected_subjects': detected,
                'matched_subjects': matched,
                'unmatched_subjects': unmatched,
                'subject_question_counts': counts
            }
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse subject detection response: {e}")
            return self._fallback_subject_detection(response, pattern_subjects)
    
    def _normalize_subject(self, subject: str) -> str:
        """Normalize subject name for comparison - supports ANY subject"""
        subject = subject.strip().title()
        
        # Common aliases - extensible for any subject abbreviation
        # These are just common abbreviations, system accepts any subject
        aliases = {
            'Math': 'Mathematics',
            'Maths': 'Mathematics',
            'Chem': 'Chemistry',
            'Phy': 'Physics',
            'Bio': 'Biology',
            'Comp': 'Computer Science',
            'Cs': 'Computer Science',
            'Eco': 'Economics',
            'Econ': 'Economics',
            'Eng': 'English',
            'Hist': 'History',
            'Geo': 'Geography',
            'Pol': 'Political Science',
            'Psych': 'Psychology',
            'Soc': 'Sociology',
            'Acc': 'Accountancy',
            'Stat': 'Statistics',
            'Lit': 'Literature',
        }
        
        return aliases.get(subject, subject)
    
    def _fallback_subject_detection(
        self,
        text_content: str,
        pattern_subjects: List[str]
    ) -> Dict:
        """
        Fallback regex-based subject detection.
        DYNAMIC: Works with ANY subject provided in pattern_subjects.
        Uses the subject names themselves as primary keywords.
        """
        detected = []
        counts = {}
        text_lower = text_content.lower()
        
        # Dynamically build patterns based on provided subjects
        # Primary detection: look for subject name mentions in the text
        for subject in pattern_subjects:
            subject_normalized = self._normalize_subject(subject)
            subject_lower = subject_normalized.lower()
            
            # Primary pattern: the subject name itself (most reliable)
            primary_patterns = [
                rf'\b{re.escape(subject_lower)}\b',  # Exact match
                rf'\b{re.escape(subject_lower[:4])}\w*\b',  # Prefix match (e.g., "phys" matches "physics")
            ]
            
            # Add common variations
            if ' ' in subject_lower:
                # Multi-word subjects like "Computer Science" -> also match "CS", "comp sci"
                words = subject_lower.split()
                abbreviation = ''.join(w[0] for w in words)
                primary_patterns.append(rf'\b{re.escape(abbreviation)}\b')
            
            match_count = sum(
                len(re.findall(p, text_lower, re.IGNORECASE))
                for p in primary_patterns
            )
            
            if match_count > 0:  # At least one mention
                detected.append(subject_normalized)
                # Rough estimate based on mentions
                counts[subject_normalized] = max(1, match_count * 2)
        
        # If no subjects detected from pattern subjects, check for ANY subject headers
        if not detected:
            # Look for generic subject header patterns: "Section: X", "Part: X", etc.
            header_pattern = r'(?:section|part|subject|chapter)\s*[-:]\s*([A-Za-z\s]+?)(?:\n|$|questions?)'
            headers = re.findall(header_pattern, text_lower, re.IGNORECASE)
            for header in headers:
                header_normalized = self._normalize_subject(header.strip())
                if header_normalized and len(header_normalized) > 2:
                    # Check if this header matches any pattern subject (case-insensitive)
                    for ps in pattern_subjects:
                        if self._normalize_subject(ps).lower() == header_normalized.lower():
                            detected.append(self._normalize_subject(ps))
                            counts[self._normalize_subject(ps)] = 1
        
        # Match against pattern subjects - ensure UNIQUE lists
        pattern_subjects_normalized = [self._normalize_subject(s) for s in pattern_subjects]
        
        # Remove duplicates while preserving order
        detected = list(dict.fromkeys(detected))
        matched = list(dict.fromkeys([s for s in detected if s in pattern_subjects_normalized]))
        unmatched = list(dict.fromkeys([s for s in detected if s not in pattern_subjects_normalized]))
        
        return {
            'detected_subjects': detected,
            'matched_subjects': matched,
            'unmatched_subjects': unmatched,
            'subject_question_counts': counts
        }
    
    def separate_by_subject(
        self,
        text_content: str,
        subjects: List[str]
    ) -> Dict[str, str]:
        """
        Separate document content by subject using regex-based approach
        This is more reliable for large files than AI-based separation
        
        Args:
            text_content: Raw text from document
            subjects: List of subjects to separate
            
        Returns:
            Dictionary mapping subject to its raw content
        """
        logger.info(f"Separating content into subjects: {subjects}, document length: {len(text_content)} chars")
        
        # First try regex-based separation (more reliable for large files)
        result = self._regex_based_separation(text_content, subjects)
        
        # Check if we got meaningful content for each subject
        subjects_with_content = [s for s, content in result.items() if content.strip()]
        
        # Log what we found
        for s in subjects:
            content_len = len(result.get(s, ''))
            logger.info(f"  Subject '{s}': {content_len} chars")
        
        if len(subjects_with_content) >= len(subjects) * 0.5:  # At least 50% subjects found
            logger.info(f"Regex separation successful: {len(subjects_with_content)} subjects with content")
            return result
        
        # If regex didn't work well, try AI-based separation for smaller files
        # Increased threshold to 150000 chars to handle larger documents
        if len(text_content) < 150000:
            logger.info("Trying AI-based separation...")
            try:
                prompt = self._build_separation_prompt(text_content, subjects)
                response = self._call_gemini(prompt, max_tokens=65536)  # Increased token limit
                ai_result = self._parse_separation_response(response, subjects)
                
                # Verify AI result has actual content (not just metadata)
                if ai_result and any(len(v) > 100 for v in ai_result.values()):
                    logger.info(f"AI separation successful")
                    return ai_result
            except Exception as e:
                logger.warning(f"AI separation failed: {e}")
        
        # Return regex result even if partial
        logger.info(f"Using regex result with {len(subjects_with_content)} subjects")
        return result
    
    def _regex_based_separation(
        self,
        text_content: str,
        subjects: List[str]
    ) -> Dict[str, str]:
        """
        Separate content using regex patterns to find subject sections
        Enhanced with multiple detection strategies
        """
        result = {s: '' for s in subjects}
        
        # Strategy 1: Look for explicit subject headers
        subject_positions = self._find_subject_headers(text_content, subjects)
        
        if subject_positions:
            logger.info(f"Found {len(subject_positions)} subject headers")
            result = self._extract_content_by_positions(text_content, subject_positions, subjects)
            
            # Verify we got content for most subjects
            subjects_with_content = sum(1 for s in subjects if result.get(s, '').strip())
            if subjects_with_content >= len(subjects) * 0.5:
                return result
        
        # Strategy 2: Look for subject mentions anywhere and split around them
        logger.info("Trying flexible subject detection...")
        result = self._flexible_subject_detection(text_content, subjects)
        
        subjects_with_content = sum(1 for s in subjects if result.get(s, '').strip())
        if subjects_with_content >= len(subjects) * 0.5:
            return result
        
        # Strategy 3: Keyword-based separation for each question
        logger.info("Trying keyword-based separation...")
        result = self._keyword_based_separation(text_content, subjects)
        
        return result
    
    def _find_subject_headers(
        self,
        text_content: str,
        subjects: List[str]
    ) -> List[Tuple[int, int, str]]:
        """Find all subject header positions in the document"""
        subject_positions = []
        
        for subject in subjects:
            # Comprehensive list of header patterns
            patterns = [
                # Standard headers
                rf'(?:^|\n)\s*[-=_*#]+\s*{re.escape(subject)}\s*[-=_*#]+\s*(?:\n|$)',
                rf'(?:^|\n)\s*(?:SECTION|PART|SUBJECT|CHAPTER)[\s:-]+{re.escape(subject)}[\s:-]*(?:\n|$)',
                rf'(?:^|\n)\s*{re.escape(subject)}[\s:-]+(?:SECTION|PART|QUESTIONS?)[\s:-]*(?:\n|$)',
                # Simple headers
                rf'(?:^|\n)\s*{re.escape(subject)}\s*[:\-]+\s*(?:\n|$)',
                rf'(?:^|\n)\s*{re.escape(subject)}\s*(?:\n|$)(?=\s*(?:Q\.?|Question|\d+[\.\)]))',
                # Markdown style
                rf'(?:^|\n)\s*#+\s*{re.escape(subject)}\s*#+?\s*(?:\n|$)',
                rf'(?:^|\n)\s*\*\*\s*{re.escape(subject)}\s*\*\*\s*(?:\n|$)',
                # With numbers
                rf'(?:^|\n)\s*(?:\d+[\.\)]?\s*)?{re.escape(subject)}[\s:-]*(?:MCQ|Questions?|Problems?)?\s*(?:\n|$)',
                # Bracketed
                rf'(?:^|\n)\s*[\[\(]\s*{re.escape(subject)}\s*[\]\)]\s*(?:\n|$)',
            ]
            
            best_match = None
            for pattern in patterns:
                matches = list(re.finditer(pattern, text_content, re.IGNORECASE | re.MULTILINE))
                if matches:
                    # Take the first match for this subject
                    match = matches[0]
                    if best_match is None or match.start() < best_match[0]:
                        best_match = (match.start(), match.end(), subject)
            
            if best_match:
                subject_positions.append(best_match)
        
        # Sort by position
        subject_positions.sort(key=lambda x: x[0])
        return subject_positions
    
    def _extract_content_by_positions(
        self,
        text_content: str,
        positions: List[Tuple[int, int, str]],
        subjects: List[str]
    ) -> Dict[str, str]:
        """Extract content between subject positions"""
        result = {s: '' for s in subjects}
        
        for i, (start, header_end, subject) in enumerate(positions):
            if i + 1 < len(positions):
                next_start = positions[i + 1][0]
                content = text_content[header_end:next_start].strip()
            else:
                content = text_content[header_end:].strip()
            
            result[subject] = content
        
        return result
    
    def _flexible_subject_detection(
        self,
        text_content: str,
        subjects: List[str]
    ) -> Dict[str, str]:
        """
        More flexible detection - find subject mentions and extract surrounding content
        """
        result = {s: '' for s in subjects}
        
        # Find all positions where subjects are mentioned
        all_mentions = []
        for subject in subjects:
            # Look for subject name with some context
            pattern = rf'(?:^|\n)([^\n]*\b{re.escape(subject)}\b[^\n]*(?:\n|$))'
            for match in re.finditer(pattern, text_content, re.IGNORECASE):
                line = match.group(1).strip()
                # Check if this looks like a header (short line, possibly with special chars)
                if len(line) < 100 and (
                    line.upper() == subject.upper() or
                    subject.lower() in line.lower()[:50]
                ):
                    all_mentions.append((match.start(), match.end(), subject))
        
        if not all_mentions:
            return result
        
        # Sort by position and remove duplicates
        all_mentions.sort(key=lambda x: x[0])
        
        # Extract content between mentions
        for i, (start, end, subject) in enumerate(all_mentions):
            if i + 1 < len(all_mentions):
                next_start = all_mentions[i + 1][0]
                content = text_content[end:next_start].strip()
            else:
                content = text_content[end:].strip()
            
            # Append to existing content for this subject
            if result[subject]:
                result[subject] += '\n\n' + content
            else:
                result[subject] = content
        
        return result
    
    def _keyword_based_separation(
        self,
        text_content: str,
        subjects: List[str]
    ) -> Dict[str, str]:
        """
        Separate content by detecting subject-specific keywords in questions.
        DYNAMIC: Works with ANY subject - uses comprehensive keyword database
        plus dynamic fallback for unknown subjects.
        """
        result = {s: '' for s in subjects}
        
        # Comprehensive subject-specific keywords (weighted)
        # This is a reference database for common subjects, but the system 
        # dynamically handles ANY subject not in this list
        subject_keywords = {
            'Physics': {
                'high': ['velocity', 'acceleration', 'momentum', 'newton', 'joule', 'watt', 'ohm', 'volt', 'ampere', 'hertz', 'coulomb', 'farad', 'tesla', 'weber', 'henry', 'pascal', 'torque', 'inertia', 'friction', 'gravity', 'projectile', 'oscillation', 'pendulum', 'capacitor', 'resistor', 'inductor', 'semiconductor', 'photoelectric', 'radioactive', 'nuclear', 'fission', 'fusion'],
                'medium': ['force', 'mass', 'energy', 'power', 'work', 'wave', 'electric', 'magnetic', 'current', 'voltage', 'resistance', 'frequency', 'wavelength', 'amplitude', 'optics', 'lens', 'mirror', 'reflection', 'refraction', 'diffraction', 'interference', 'polarization', 'thermodynamics', 'heat', 'temperature', 'pressure', 'density', 'viscosity', 'elasticity'],
                'low': ['kinetic', 'potential', 'mechanical', 'thermal', 'sound', 'light', 'speed', 'distance', 'time', 'motion', 'particle', 'field', 'charge', 'circuit']
            },
            'Chemistry': {
                'high': ['molecule', 'atom', 'ion', 'cation', 'anion', 'oxidation', 'reduction', 'redox', 'electrochemistry', 'electrolysis', 'molarity', 'molality', 'normality', 'stoichiometry', 'titration', 'buffer', 'catalyst', 'enzyme', 'polymer', 'monomer', 'isomer', 'stereochemistry', 'chirality', 'enantiomer', 'diastereomer', 'alkane', 'alkene', 'alkyne', 'alcohol', 'aldehyde', 'ketone', 'carboxylic', 'ester', 'amine', 'amide'],
                'medium': ['reaction', 'acid', 'base', 'pH', 'pOH', 'bond', 'covalent', 'ionic', 'metallic', 'hydrogen bond', 'electron', 'proton', 'neutron', 'orbital', 'hybridization', 'resonance', 'compound', 'element', 'periodic', 'group', 'period', 'metal', 'nonmetal', 'metalloid', 'organic', 'inorganic', 'mole', 'avogadro', 'solution', 'solute', 'solvent', 'precipitate', 'equilibrium', 'le chatelier'],
                'low': ['chemical', 'formula', 'equation', 'balance', 'concentration', 'dilution', 'mixture', 'pure', 'substance', 'property', 'physical', 'state', 'gas', 'liquid', 'solid']
            },
            'Mathematics': {
                'high': ['derivative', 'integral', 'differentiation', 'integration', 'limit', 'continuity', 'differentiable', 'antiderivative', 'matrix', 'determinant', 'eigenvalue', 'eigenvector', 'vector', 'scalar', 'dot product', 'cross product', 'polynomial', 'quadratic', 'cubic', 'logarithm', 'exponential', 'trigonometric', 'inverse trigonometric', 'hyperbolic', 'asymptote', 'tangent line', 'normal line', 'maxima', 'minima', 'inflection', 'concave', 'convex'],
                'medium': ['equation', 'function', 'domain', 'range', 'graph', 'slope', 'intercept', 'linear', 'parabola', 'hyperbola', 'ellipse', 'circle', 'conic', 'sine', 'cosine', 'tangent', 'secant', 'cosecant', 'cotangent', 'probability', 'statistics', 'mean', 'median', 'mode', 'variance', 'standard deviation', 'permutation', 'combination', 'factorial', 'binomial', 'sequence', 'series', 'arithmetic', 'geometric', 'harmonic'],
                'low': ['algebra', 'calculus', 'geometry', 'coordinate', 'angle', 'triangle', 'rectangle', 'square', 'polygon', 'area', 'perimeter', 'volume', 'surface area', 'ratio', 'proportion', 'percentage', 'fraction', 'decimal', 'integer', 'real number', 'complex number', 'imaginary']
            },
            'Biology': {
                'high': ['DNA', 'RNA', 'chromosome', 'gene', 'allele', 'genotype', 'phenotype', 'mutation', 'transcription', 'translation', 'replication', 'mitosis', 'meiosis', 'cytokinesis', 'photosynthesis', 'chlorophyll', 'chloroplast', 'mitochondria', 'ribosome', 'endoplasmic reticulum', 'golgi', 'lysosome', 'vacuole', 'nucleus', 'cytoplasm', 'membrane', 'ATP', 'ADP', 'NADH', 'FADH', 'glycolysis', 'krebs cycle', 'electron transport'],
                'medium': ['cell', 'protein', 'enzyme', 'substrate', 'organism', 'species', 'genus', 'family', 'order', 'class', 'phylum', 'kingdom', 'domain', 'evolution', 'natural selection', 'adaptation', 'genetics', 'heredity', 'dominant', 'recessive', 'homozygous', 'heterozygous', 'respiration', 'fermentation', 'ecosystem', 'biodiversity', 'food chain', 'food web', 'producer', 'consumer', 'decomposer'],
                'low': ['anatomy', 'physiology', 'tissue', 'organ', 'system', 'blood', 'heart', 'lung', 'brain', 'nerve', 'muscle', 'bone', 'skin', 'digestion', 'circulation', 'excretion', 'reproduction', 'growth', 'development', 'hormone', 'immune', 'disease', 'infection', 'virus', 'bacteria']
            },
            # Additional common subjects for global support
            'Computer Science': {
                'high': ['algorithm', 'programming', 'database', 'binary', 'compiler', 'recursion', 'stack', 'queue', 'linked list', 'tree', 'graph', 'hash', 'sorting', 'searching', 'complexity', 'OOP', 'inheritance', 'polymorphism', 'encapsulation', 'abstraction'],
                'medium': ['code', 'function', 'variable', 'loop', 'array', 'class', 'object', 'method', 'syntax', 'debug', 'memory', 'CPU', 'network', 'protocol', 'API', 'software', 'hardware'],
                'low': ['computer', 'program', 'data', 'input', 'output', 'file', 'system', 'user', 'interface']
            },
            'Economics': {
                'high': ['GDP', 'inflation', 'deflation', 'fiscal', 'monetary', 'macroeconomics', 'microeconomics', 'elasticity', 'marginal utility', 'equilibrium', 'monopoly', 'oligopoly', 'externality', 'subsidy', 'tariff'],
                'medium': ['demand', 'supply', 'price', 'market', 'cost', 'revenue', 'profit', 'tax', 'budget', 'investment', 'consumption', 'savings', 'interest', 'rate'],
                'low': ['economy', 'trade', 'goods', 'services', 'money', 'bank', 'business', 'income', 'wage']
            },
            'History': {
                'high': ['civilization', 'empire', 'dynasty', 'revolution', 'independence', 'colonialism', 'nationalism', 'constitution', 'monarchy', 'republic', 'democracy', 'imperialism', 'feudalism', 'renaissance', 'reformation'],
                'medium': ['war', 'treaty', 'king', 'emperor', 'ruler', 'battle', 'conquest', 'trade route', 'ancient', 'medieval', 'modern', 'century', 'era', 'period'],
                'low': ['history', 'historical', 'past', 'event', 'culture', 'society', 'movement', 'leader']
            },
            'Geography': {
                'high': ['latitude', 'longitude', 'equator', 'meridian', 'topography', 'cartography', 'tectonics', 'erosion', 'weathering', 'hydrological', 'demographic', 'urbanization', 'migration'],
                'medium': ['continent', 'ocean', 'sea', 'river', 'mountain', 'climate', 'weather', 'terrain', 'population', 'region', 'country', 'capital', 'border', 'map', 'scale'],
                'low': ['geography', 'location', 'place', 'area', 'land', 'water', 'environment', 'natural', 'resource']
            },
            'English': {
                'high': ['grammar', 'syntax', 'semantics', 'morphology', 'phonetics', 'comprehension', 'literature', 'rhetoric', 'metaphor', 'simile', 'alliteration', 'onomatopoeia', 'personification'],
                'medium': ['noun', 'verb', 'adjective', 'adverb', 'pronoun', 'preposition', 'conjunction', 'tense', 'vocabulary', 'sentence', 'paragraph', 'essay', 'passage', 'poem', 'prose'],
                'low': ['word', 'language', 'reading', 'writing', 'speaking', 'listening', 'text', 'meaning']
            },
            'Political Science': {
                'high': ['sovereignty', 'legislature', 'executive', 'judiciary', 'constitution', 'federalism', 'democracy', 'autocracy', 'totalitarianism', 'suffrage', 'referendum', 'plebiscite'],
                'medium': ['government', 'state', 'nation', 'politics', 'policy', 'law', 'rights', 'citizen', 'election', 'parliament', 'congress', 'senate', 'president', 'prime minister'],
                'low': ['political', 'power', 'authority', 'rule', 'vote', 'party', 'leader', 'public']
            },
            'Psychology': {
                'high': ['cognition', 'behavior', 'consciousness', 'perception', 'memory', 'learning', 'emotion', 'motivation', 'personality', 'psychoanalysis', 'conditioning', 'neuroscience', 'psychotherapy'],
                'medium': ['stimulus', 'response', 'reinforcement', 'punishment', 'anxiety', 'depression', 'stress', 'intelligence', 'IQ', 'development', 'social', 'cognitive', 'behavioral'],
                'low': ['psychology', 'mind', 'brain', 'mental', 'thought', 'feeling', 'attitude', 'belief']
            },
            'Accountancy': {
                'high': ['ledger', 'journal', 'trial balance', 'balance sheet', 'income statement', 'depreciation', 'amortization', 'accrual', 'deferred', 'receivable', 'payable', 'equity'],
                'medium': ['debit', 'credit', 'asset', 'liability', 'revenue', 'expense', 'profit', 'loss', 'transaction', 'voucher', 'invoice', 'audit', 'taxation'],
                'low': ['account', 'accounting', 'financial', 'book', 'record', 'entry', 'statement', 'cash', 'bank']
            },
            'Sociology': {
                'high': ['socialization', 'stratification', 'deviance', 'norms', 'values', 'institution', 'bureaucracy', 'ethnography', 'demography', 'urbanization', 'globalization'],
                'medium': ['society', 'culture', 'community', 'group', 'class', 'status', 'role', 'identity', 'family', 'religion', 'education', 'media', 'inequality'],
                'low': ['social', 'people', 'relationship', 'interaction', 'behavior', 'change', 'structure']
            },
        }
        
        # Split content into question blocks using multiple patterns
        question_blocks = self._split_into_questions(text_content)
        
        if not question_blocks:
            # No clear question numbering, put all in first subject
            if subjects:
                result[subjects[0]] = text_content
            return result
        
        logger.info(f"Found {len(question_blocks)} question blocks")
        
        # Process each question block
        current_content = {s: [] for s in subjects}
        
        for q_num, q_text in question_blocks:
            if not q_text.strip():
                continue
            
            # Determine subject by keywords with weighted scoring
            q_lower = q_text.lower()
            best_subject = subjects[0] if subjects else 'General'
            best_score = 0
            
            for subject in subjects:
                # Get keywords - check both the subject name and normalized version
                subject_normalized = self._normalize_subject(subject)
                keywords_dict = (
                    subject_keywords.get(subject) or 
                    subject_keywords.get(subject_normalized) or
                    # Dynamic fallback: use subject name itself as keyword
                    {'high': [subject.lower()], 'medium': [], 'low': []}
                )
                score = 0
                
                # Subject name match - highest priority (score 5)
                if subject.lower() in q_lower or subject_normalized.lower() in q_lower:
                    score += 5
                
                # High weight keywords
                for kw in keywords_dict.get('high', []):
                    if kw.lower() in q_lower:
                        score += 3
                
                # Medium weight keywords
                for kw in keywords_dict.get('medium', []):
                    if kw.lower() in q_lower:
                        score += 2
                
                # Low weight keywords
                for kw in keywords_dict.get('low', []):
                    if kw.lower() in q_lower:
                        score += 1
                
                if score > best_score:
                    best_score = score
                    best_subject = subject
            
            # Reconstruct question with number
            full_question = f"Q.{q_num}. {q_text.strip()}"
            current_content[best_subject].append(full_question)
        
        # Combine questions for each subject
        for subject in subjects:
            if current_content[subject]:
                result[subject] = '\n\n'.join(current_content[subject])
        
        return result
    
    def _count_questions_in_separated_content(self, separated_content: Dict[str, str]) -> Dict[str, int]:
        """
        Count actual questions in each subject's separated content.
        This gives us ACCURATE counts instead of AI estimates.
        
        Args:
            separated_content: Dict mapping subject to content string
            
        Returns:
            Dict mapping subject to actual question count
        """
        counts = {}
        
        for subject, content in separated_content.items():
            if not content or not content.strip():
                counts[subject] = 0
                continue
            
            # Use the same question splitting logic to count
            questions = self._split_into_questions(content)
            count = len(questions)
            
            # If pattern-based count is low, try counting "Answer:" patterns as backup
            if count < 3:
                answer_pattern = r'(?:Answer|Ans)[\s:]+[A-Da-d]'
                answer_matches = re.findall(answer_pattern, content, re.IGNORECASE)
                answer_count = len(answer_matches)
                if answer_count > count:
                    count = answer_count
            
            counts[subject] = count
            logger.info(f"  Subject '{subject}': {count} questions in separated content ({len(content)} chars)")
        
        return counts
    
    def _split_into_questions(self, text_content: str) -> List[Tuple[str, str]]:
        """
        Split content into question blocks using multiple patterns
        Returns list of (question_number, question_text) tuples
        
        IMPORTANT: Only counts UNIQUE question numbers in SEQUENTIAL order to avoid
        counting answer options like (1), (2), (3), (4) as separate questions.
        """
        questions = []
        
        # Multiple patterns for question detection - ordered by specificity
        patterns = [
            # Q1. or Q.1 or Q 1 - most specific
            r'(?:^|\n)\s*Q\.?\s*(\d+)[\.\):\s]+',
            # Question 1 or Question: 1
            r'(?:^|\n)\s*Question[\s:]*(\d+)[\.\):\s]+',
            # Number followed by . and actual question content
            # Matches: "61. The product..." or "89. 20 mL of..." 
            r'(?:^|\n)\s*(\d+)\.\s+',
        ]
        
        # Try each pattern
        for pattern in patterns:
            matches = list(re.finditer(pattern, text_content, re.IGNORECASE | re.MULTILINE))
            if len(matches) >= 3:  # At least 3 questions found
                # CRITICAL: Filter to only UNIQUE question numbers in APPROXIMATE sequence
                # This prevents counting (1), (2), (3), (4) answer options multiple times
                seen_numbers = set()
                unique_matches = []
                
                for match in matches:
                    q_num = int(match.group(1))
                    # Only count if we haven't seen this number yet
                    if q_num not in seen_numbers:
                        seen_numbers.add(q_num)
                        unique_matches.append(match)
                
                # Extract questions from unique matches
                for i, match in enumerate(unique_matches):
                    q_num = match.group(1)
                    start = match.end()
                    
                    if i + 1 < len(unique_matches):
                        end = unique_matches[i + 1].start()
                    else:
                        end = len(text_content)
                    
                    q_text = text_content[start:end].strip()
                    questions.append((q_num, q_text))
                
                logger.info(f"Found {len(questions)} UNIQUE questions using pattern: {pattern[:30]}...")
                return questions
        
        # FALLBACK: Use Answer pattern to count questions
        # Many exam documents have "Answer (N)" or "Ans. (N)" patterns
        answer_patterns = [
            r'(?:Answer|Ans)\.?\s*[\(\[]?(\d+)[\)\]]?',
            r'##\s*Answer\s*[\(\[]?(\d+)[\)\]]?',
        ]
        
        for pattern in answer_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            if len(matches) >= 3:
                unique_nums = sorted(set(int(m) for m in matches if m.isdigit()))
                logger.info(f"Found {len(unique_nums)} questions via Answer pattern")
                # Return placeholder questions for counting purposes
                return [(str(n), '') for n in unique_nums]
        
        # LAST RESORT: If no pattern worked, try splitting by double newlines
        blocks = re.split(r'\n\s*\n', text_content)
        for i, block in enumerate(blocks):
            if block.strip():
                questions.append((str(i + 1), block.strip()))
        
        return questions
    
    def _build_separation_prompt(
        self,
        text_content: str,
        subjects: List[str]
    ) -> str:
        """Build prompt for content separation by subject - NO question extraction"""
        subjects_str = ', '.join(subjects)
        
        # For large documents, we should NOT use AI separation - use regex instead
        # This method is only called for smaller files (< 50000 chars) as per separate_by_subject
        # But we still need to handle the content properly
        max_content = text_content[:100000] if len(text_content) > 100000 else text_content
        
        return f"""You are a document separator. Your ONLY job is to split this document into sections by subject.

SUBJECTS: {subjects_str}

INSTRUCTIONS:
1. Find where each subject's content starts and ends
2. Copy the EXACT text for each subject - do NOT summarize or modify
3. Return JSON with subject names as keys and their FULL raw content as values

IMPORTANT:
- Copy ALL text exactly as written
- Include ALL questions, options, answers, solutions
- Do NOT summarize or describe the content
- Do NOT say "here are the questions" - just return the actual text

OUTPUT FORMAT:
```json
{{
    "Physics": "[paste ALL physics content here exactly as it appears]",
    "Chemistry": "[paste ALL chemistry content here exactly as it appears]"
}}
```

DOCUMENT TO SEPARATE:
{max_content}

Return JSON only with the actual content (not descriptions):"""

    def _parse_separation_response(
        self,
        response: str,
        subjects: List[str]
    ) -> Dict[str, str]:
        """Parse Gemini response for subject separation"""
        try:
            # Extract JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON object
                json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            result = json.loads(json_str)
            
            # Normalize keys
            normalized = {}
            for key, value in result.items():
                normalized_key = self._normalize_subject(key)
                if normalized_key in [self._normalize_subject(s) for s in subjects]:
                    normalized[normalized_key] = value
            
            return normalized
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse separation response: {e}")
            return self._fallback_separation(response, subjects)
    
    def _fallback_separation(
        self,
        text_content: str,
        subjects: List[str]
    ) -> Dict[str, str]:
        """Fallback - just use the regex-based separation"""
        return self._regex_based_separation(text_content, subjects)
    
    def match_subjects_to_pattern(
        self,
        detected_subjects: List[str],
        pattern_subjects: List[str]
    ) -> Tuple[List[str], List[str]]:
        """
        Match detected subjects against pattern's configured subjects
        
        Args:
            detected_subjects: Subjects detected in document
            pattern_subjects: Subjects configured in exam pattern
            
        Returns:
            Tuple of (matched_subjects, unmatched_subjects)
        """
        pattern_normalized = {self._normalize_subject(s): s for s in pattern_subjects}
        
        matched = []
        unmatched = []
        
        for subject in detected_subjects:
            normalized = self._normalize_subject(subject)
            if normalized in pattern_normalized:
                matched.append(pattern_normalized[normalized])
            else:
                unmatched.append(subject)
        
        return matched, unmatched
    
    def _call_gemini(self, prompt: str, max_tokens: int = 65536) -> str:
        """Call Gemini API with configurable max tokens - increased to 64K for large documents"""
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,  # Very low for exact copying
                    'top_p': 0.95,
                    'max_output_tokens': max_tokens,
                }
            )
            return response.text
        except Exception as e:
            raise DocumentPreAnalysisError(f"Gemini API call failed: {str(e)}")
    
    def to_dict(self, result: PreAnalysisResult) -> Dict:
        """Convert PreAnalysisResult to dictionary for API response"""
        return {
            'is_valid': result.is_valid,
            'document_type': result.document_type,
            'document_type_display': result.document_type_display,
            'confidence': result.confidence,
            'detected_subjects': result.detected_subjects,
            'matched_subjects': result.matched_subjects,
            'unmatched_subjects': result.unmatched_subjects,
            'subject_question_counts': result.subject_question_counts,
            'total_estimated_questions': result.total_estimated_questions,
            'document_structure': result.document_structure,
            'error_message': result.error_message,
            'reason': result.reason,
        }
