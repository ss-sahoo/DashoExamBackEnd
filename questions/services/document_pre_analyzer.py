"""
Document Pre-Analysis Service
AI-powered document analysis to determine document type, detect subjects,
and separate questions by subject before extraction.
"""
import json
import re
import os
import time
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
    subject_separated_content: Dict[str, Dict]  # Changed to Dict[str, Dict] with 'content' and 'instructions' keys
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
            # Log which API key is being used (first 10 and last 4 chars for security)
            if self.api_key:
                key_preview = f"{self.api_key[:10]}...{self.api_key[-4:]}" if len(self.api_key) > 14 else "***"
                logger.info(f"🔑 Initializing Gemini with model: {self.model}, API key: {key_preview}")
                # Verify it matches the expected key
                expected_key = "AIzaSyBRBA_VMMB1B0zzYuL4QJWUmRmTE90TsmI"
                if self.api_key == expected_key:
                    logger.info("✅ API Key verified: Matches expected key (AIzaSyBRBA...TsmI)")
                else:
                    logger.warning(f"⚠️ API Key does NOT match expected key!")
                    logger.warning(f"   Expected: {expected_key[:10]}...{expected_key[-4:]}")
                    logger.warning(f"   Using:    {self.api_key[:10]}...{self.api_key[-4:]}")
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
        logger.info("=" * 80)
        logger.info("🚀 Starting document pre-analysis...")
        logger.info("=" * 80)
        analysis_start_time = time.time()
        
        # Check if we should skip AI and use regex only (for quota issues)
        # This prevents wasting time on API calls that will fail
        use_ai = True
        # Allow disabling AI via environment variable for quota issues
        disable_ai = os.getenv('DISABLE_GEMINI_AI', '').lower() in ('true', '1', 'yes')
        if disable_ai:
            logger.info("⚠️ AI disabled via DISABLE_GEMINI_AI environment variable, using regex-only mode")
            use_ai = False
        else:
            # Test API credentials
            logger.info("🔍 Testing Gemini API credentials...")
            api_key_preview = self.api_key[:10] + "..." if self.api_key else "None"
            logger.info(f"   API Key: {api_key_preview}")
            logger.info(f"   Model: {self.model}")
            
            # Quick test call to verify credentials
            try:
                test_start = time.time()
                test_response = self.client.generate_content(
                    "Say 'API working' if you can read this.",
                    generation_config={'max_output_tokens': 10}
                )
                test_elapsed = time.time() - test_start
                
                # Handle response text extraction safely
                try:
                    response_text = test_response.text
                except AttributeError:
                    # Fallback to parts accessor
                    if hasattr(test_response, 'parts') and test_response.parts:
                        response_text = ''.join(part.text for part in test_response.parts if hasattr(part, 'text'))
                    elif hasattr(test_response, 'candidates') and test_response.candidates:
                        response_text = ''.join(
                            part.text for part in test_response.candidates[0].content.parts 
                            if hasattr(part, 'text')
                        )
                    else:
                        response_text = "Response received (format check passed)"
                
                logger.info(f"✅ API credentials verified! Test call took {test_elapsed:.2f} seconds")
                logger.info(f"   Test response: {response_text[:50]}")
            except Exception as e:
                error_msg = str(e)
                # Don't fail on text extraction errors - API is working if we got a response
                if 'quick accessor' in error_msg or 'parts' in error_msg.lower():
                    logger.info(f"✅ API credentials verified! (Response format check passed)")
                    logger.info(f"   Note: {error_msg[:100]}")
                else:
                    logger.error(f"❌ API credentials test FAILED: {error_msg}")
                    logger.warning("⚠️ Will use regex fallback for all operations")
                    use_ai = False
        
        try:
            # Step 1: Detect document type
            step1_start = time.time()
            if use_ai:
                try:
                    logger.info("📝 Step 1: Detecting document type with AI...")
                    doc_type_result = self.detect_document_type(text_content)
                    logger.info(f"✅ Document type detected: {doc_type_result.get('document_type')} (AI)")
                except Exception as e:
                    logger.warning(f"⚠️ AI document type detection failed: {e}, using regex fallback")
                    doc_type_result = self._fallback_document_type_detection(text_content)
                    logger.info(f"✅ Document type detected: {doc_type_result.get('document_type')} (Regex)")
            else:
                logger.info("📝 Step 1: Detecting document type with regex...")
                doc_type_result = self._fallback_document_type_detection(text_content)
                logger.info(f"✅ Document type detected: {doc_type_result.get('document_type')} (Regex)")
            logger.info(f"   Step 1 took {time.time() - step1_start:.2f} seconds")
            
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
            step2_start = time.time()
            if use_ai:
                try:
                    logger.info("📚 Step 2: Detecting subjects with AI...")
                    subject_result = self.detect_subjects(text_content, pattern_subjects)
                    logger.info(f"✅ Subjects detected (AI): {subject_result.get('detected_subjects')}")
                except Exception as e:
                    logger.warning(f"⚠️ AI subject detection failed: {e}, using regex fallback")
                    subject_result = self._fallback_subject_detection(text_content, pattern_subjects)
                    logger.info(f"✅ Subjects detected (Regex): {subject_result.get('detected_subjects')}")
            else:
                logger.info("📚 Step 2: Detecting subjects with regex...")
                subject_result = self._fallback_subject_detection(text_content, pattern_subjects)
                logger.info(f"✅ Subjects detected (Regex): {subject_result.get('detected_subjects')}")
            logger.info(f"   Step 2 took {time.time() - step2_start:.2f} seconds")

            # Step 4: AI-powered document structure detection (Moved BEFORE Step 3)
            # We do this earlier so we can find subjects inside section headers that Step 2 might have missed
            step4_start = time.time()
            if use_ai:
                try:
                    logger.info("📊 Step 4: Detecting document structure with AI...")
                    document_structure = self.detect_document_structure_ai(text_content)
                    sections_count = document_structure.get('total_sections', 0)
                    logger.info(f"✅ Structure detected (AI): {sections_count} sections found")
                except Exception as e:
                    logger.warning(f"⚠️ AI structure detection failed: {e}, using regex fallback")
                    document_structure = self._fallback_structure_detection(text_content)
                    sections_count = document_structure.get('total_sections', 0)
                    logger.info(f"✅ Structure detected (Regex): {sections_count} sections found")
            else:
                logger.info("📊 Step 4: Detecting document structure with regex (AI unavailable)...")
                document_structure = self._fallback_structure_detection(text_content)
                sections_count = document_structure.get('total_sections', 0)
                logger.info(f"✅ Structure detected (Regex): {sections_count} sections found")
            logger.info(f"   Step 4 took {time.time() - step4_start:.2f} seconds")

            # ENHANCEMENT: Extract subjects from valid section structure and merge with detected subjects
            # This handles cases where Step 2 missed a subject but Step 4 found it in a section header (e.g. "Part C - BIOLOGY")
            if document_structure and document_structure.get('sections'):
                structure_subjects = []
                # Common subject names to look for
                known_subjects = ['Physics', 'Chemistry', 'Mathematics', 'Maths', 'Biology', 'Botany', 'Zoology', 'English', 'Science', 'Social']
                
                for section in document_structure.get('sections', []):
                    section_name = section.get('name', '').upper()
                    for known in known_subjects:
                        if known.upper() in section_name:
                            # Avoid false positives like "Physical Chemistry" -> Physics
                            if known.upper() == 'PHYSICS' and 'CHEMISTRY' in section_name:
                                continue
                            if known not in structure_subjects:
                                structure_subjects.append(known)
                
                # Merge with detected subjects
                current_detected = set(subject_result.get('detected_subjects', []))
                merged_subjects = list(current_detected.union(set(structure_subjects)))
                
                if len(merged_subjects) > len(current_detected):
                    logger.info(f"🔄 Updated detected subjects from structure: {current_detected} -> {merged_subjects}")
                    subject_result['detected_subjects'] = merged_subjects
                    
                    # Also update matched subjects if we have pattern subjects
                    if pattern_subjects:
                        subject_result['matched_subjects'] = [
                            s for s in merged_subjects 
                            if any(ps.lower() in s.lower() or s.lower() in ps.lower() for ps in pattern_subjects)
                        ]
                    else:
                        subject_result['matched_subjects'] = merged_subjects
            
            # Step 3: Separate content by subject (Now uses consolidated subject list)
            separated_content = {}
            # Extract general instructions from document beginning
            general_instructions = self._extract_instructions_from_text(text_content[:2000])
            
            # Prioritize matched subjects for separation
            subjects_to_separate = subject_result.get('matched_subjects', [])
            if not subjects_to_separate:
                subjects_to_separate = subject_result.get('detected_subjects', [])

            if len(subjects_to_separate) > 1:
                separated_content = self.separate_by_subject(
                    text_content, 
                    subjects_to_separate
                )
            elif len(subjects_to_separate) == 1:
                # Single subject - all content belongs to it
                subject = subjects_to_separate[0]
                separated_content = {
                    subject: {
                        'content': text_content,
                        'instructions': general_instructions
                    }
                }
            else:
                # No subjects detected - treat as single subject
                separated_content = {
                    'General': {
                        'content': text_content,
                        'instructions': general_instructions
                    }
                }
            
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
            
        except DocumentPreAnalysisError as e:
            error_str = str(e)
            if '429' in error_str or 'quota' in error_str.lower():
                logger.warning("Quota exhausted for document type detection, using regex fallback")
                return self._fallback_document_type_detection(text_content)
            else:
                logger.error(f"Document type detection failed: {e}")
                return self._fallback_document_type_detection(text_content)
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
            try:
                response = self._call_gemini(prompt, max_tokens=8192)
                logger.info(f"AI response received, length: {len(response)} characters")
                logger.debug(f"AI response preview: {response[:500]}...")
                
                # Parse the response
                structure = self._parse_ai_structure_response(response)
            except DocumentPreAnalysisError as e:
                error_str = str(e)
                is_quota_error = '429' in error_str or 'quota' in error_str.lower()
                is_timeout_error = '504' in error_str or 'timeout' in error_str.lower() or 'Deadline Exceeded' in error_str
                
                if is_quota_error or is_timeout_error:
                    logger.warning(f"{'Quota exhausted' if is_quota_error else 'Request timed out'} for structure detection, using regex fallback")
                    # Use regex-based fallback
                    structure = self._fallback_structure_detection(text_content)
                else:
                    raise
            
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
        # Sample document intelligently - REDUCED SIZE to prevent timeouts
        text_len = len(text_content)
        max_sample_size = 30000  # Keep larger sample for better analysis
        
        if text_len <= max_sample_size:
            sample_text = text_content
        else:
            # Large document - sample strategically but keep comprehensive samples
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
   - Asks to calculate/find numerical value OR answer is just a number (like "Answer (4)" or "Answer: 23") → numerical
   - Questions asking for numerical values, calculations, or where answer format is "Answer (NUMBER)" → numerical
   - True/False or T/F → true_false
   - Has blanks ___ to fill → fill_blank
   - Asks to explain/describe/discuss → subjective
   - Matrix/matching columns → match_following
   - Assertion-Reason format → assertion_reason
   - Based on a passage/paragraph → comprehension

4. **DETECT SECTIONS** - THIS IS CRITICAL:
   - **MANDATORY**: Look for explicit section headers like:
     * "SECTION - A", "SECTION A", "Section A", "## SECTION - A"
     * "SECTION - B", "SECTION B", "Section B", "## SECTION - B"
     * "SECTION - C", "SECTION C", "Section C", "## SECTION - C"
   - **EACH SECTION MUST BE LISTED SEPARATELY** - if you see "SECTION - A" and "SECTION - B", create TWO separate section entries
   - Each section has different question types:
     * Section A usually = single_mcq (MCQ with options A/B/C/D)
     * Section B usually = numerical (numeric answers, no options)
     * Section C usually = true_false or other types
   - **QUESTION RANGES**: Identify which question numbers belong to each section:
     * Section A might be questions 1-20 or 1-30
     * Section B might be questions 21-30 or 31-40
   - **DETECT FROM ACTUAL CONTENT**: Look for section headers in the document text itself
   - If you find "SECTION - A" followed by questions 1-20, and "SECTION - B" followed by questions 21-30, create TWO sections
   - **DO NOT** combine sections - if document has Section A and Section B, return BOTH

5. **COUNT QUESTIONS** in each detected section by looking at question numbers

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

**CRITICAL RULES FOR SECTION DETECTION:**
- **MUST DETECT ALL SECTIONS**: If document has "SECTION - A" and "SECTION - B", you MUST return BOTH sections
- **DO NOT** combine multiple sections into one "General" section
- **LOOK FOR SECTION HEADERS**: Search the entire document for patterns like:
  * "SECTION - A", "SECTION A", "Section A", "## SECTION - A"
  * "SECTION - B", "SECTION B", "Section B", "## SECTION - B"
- **IDENTIFY QUESTION RANGES**: For each section, identify which question numbers it contains:
  * Example: Section A = questions 1-20, Section B = questions 21-30
- **DETERMINE QUESTION TYPE** from section headers and content:
  * "Section A" with "Multiple Choice" or "MCQ" → single_mcq
  * "Section B" with "Numerical" or "Numeric" → numerical
  * Look at actual questions: if they have options A/B/C/D → single_mcq, if answer is a number → numerical
- **COUNT QUESTIONS**: Count actual question numbers in each section (e.g., if Section A has questions 1-20, count = 20)
- **OUTPUT FORMAT**: Return a "sections" array with ONE entry per detected section
- If document has 2 sections, return 2 section objects in the array
- Pay attention to answer formats: "Answer (4)" or "Answer: 23" indicates numerical type, not MCQ
- "Answer (A)" or "Answer: B" indicates single_mcq type

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
            
            # Clean instructions_text to remove question content
            instructions_text = str(result.get('instructions_text', ''))
            # Remove question content patterns
            instructions_text = re.sub(r'Q\.?\s*\d+.*?(?=\n|$)', '', instructions_text, flags=re.IGNORECASE | re.MULTILINE)
            instructions_text = re.sub(r'\d+\.\s+[A-Z].*?(?=\n|$)', '', instructions_text, flags=re.MULTILINE)
            instructions_text = re.sub(r'Sol\.\s+.*?(?=\n|$)', '', instructions_text, flags=re.IGNORECASE | re.MULTILINE)
            instructions_text = re.sub(r'Answer\s*\([A-D\d]+\)\s*.*?(?=\n|$)', '', instructions_text, flags=re.IGNORECASE | re.MULTILINE)
            instructions_text = re.sub(r'\s+', ' ', instructions_text).strip()  # Normalize whitespace
            
            # Build final structure
            structure = {
                'has_instructions': result.get('has_instructions', False),
                'instructions_text': instructions_text[:500],  # Limit to 500 chars
                'marking_scheme': result.get('marking_scheme', {}),
                'sections': valid_sections,
                'question_numbering_format': result.get('question_numbering_format', 'auto-detect'),
                'answer_format': result.get('answer_format', 'auto-detect'),
                'total_sections': len(valid_sections),
                'total_questions_detected': result.get('total_questions_detected', 0)
            }
            
            # IMPROVED: Calculate total from sections and prefer that if reasonable
            section_total = sum(s.get('question_count', 0) for s in valid_sections)
            ai_total = structure['total_questions_detected']
            
            # If AI total is 0 or wildly different from section totals, use section count
            if section_total > 0:
                # Section total is almost always more reliable because it's based on explicit question ranges
                if ai_total == 0 or abs(ai_total - section_total) > 2:
                    logger.info(f"Using section-based total questions: {section_total} (AI said {ai_total})")
                    structure['total_questions_detected'] = section_total
            elif ai_total == 0:
                # Last resort fallback if both are 0
                structure['total_questions_detected'] = 0
            
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
        
        type_lower = type_hint.lower().strip().replace(' ', '_')
        
        # Map various names to standard types
        type_mapping = {
            # Single MCQ variants
            'single_mcq': 'single_mcq',
            'single_correct': 'single_mcq',
            'single_correct_mcq': 'single_mcq',
            'mcq': 'single_mcq',
            'multiple_choice': 'single_mcq',
            'objective': 'single_mcq',
            
            # Multiple MCQ variants
            'multiple_mcq': 'multiple_mcq',
            'multiple_correct': 'multiple_mcq',
            'multi_correct': 'multiple_mcq',
            'more_than_one': 'multiple_mcq',
            
            # Numerical variants
            'numerical': 'numerical',
            'integer': 'numerical',
            'integer_type': 'numerical',
            'numerical_type': 'numerical',
            'calculation': 'numerical',
            'numeric': 'numerical',
            
            # True/False variants
            'true_false': 'true_false',
            'true/false': 'true_false',
            't/f': 'true_false',
            'boolean': 'true_false',
            
            # Fill in blanks variants
            'fill_blank': 'fill_blank',
            'fill_in_the_blank': 'fill_blank',
            'fill_in_the_blanks': 'fill_blank',
            'blanks': 'fill_blank',
            
            # Subjective variants
            'subjective': 'subjective',
            'descriptive': 'subjective',
            'long_answer': 'subjective',
            'essay': 'subjective',
            'short_answer': 'subjective',
            'written': 'subjective',
            
            # Match variants
            'match_following': 'match_following',
            'match': 'match_following',
            'matching': 'match_following',
            'matrix': 'match_following',
            'matrix_match': 'match_following',
            
            # Assertion-Reason
            'assertion_reason': 'assertion_reason',
            'assertion': 'assertion_reason',
            'assertion-reason': 'assertion_reason',
            
            # Comprehension
            'comprehension': 'comprehension',
            'passage': 'comprehension',
            'passage_based': 'comprehension',
            'reading': 'comprehension',
            
            # Mixed/Unknown
            'mixed': 'mixed',
            'general': 'mixed',
            'unknown': 'mixed',
        }
        
        # Priority mapping
        if 'multiple' in type_lower and 'correct' in type_lower:
            return 'multiple_mcq'
        if 'single' in type_lower and 'correct' in type_lower:
            return 'single_mcq'
        if 'integer' in type_lower or 'numerical' in type_lower:
            return 'numerical'
            
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
        elif any(kw in name_lower for kw in ['multiple', 'multi', 'more than one', 'multiple correct']):
            return 'multiple_mcq'
        elif any(kw in name_lower for kw in ['numerical', 'integer', 'numeric', 'value']):
            return 'numerical'
        elif any(kw in name_lower for kw in ['true', 'false', 't/f']):
            return 'true_false'
        elif any(kw in name_lower for kw in ['fill', 'blank']):
            return 'fill_blank'
        elif any(kw in name_lower for kw in ['match', 'matrix', 'column']):
            return 'match_following'
        elif any(kw in name_lower for kw in ['assertion', 'reason']):
            return 'assertion_reason'
        elif any(kw in name_lower for kw in ['comprehension', 'passage', 'paragraph']):
            return 'comprehension'
        elif any(kw in name_lower for kw in ['subjective', 'descriptive', 'long answer', 'short answer']):
            return 'subjective'
        elif 'mcq' in name_lower or 'objective' in name_lower:
            return 'single_mcq'
        else:
            return 'mixed'
    
    def _build_document_type_prompt(self, text_content: str) -> str:
        """Build prompt for document type detection"""
        # Limit text to first 3000 chars for type detection (reduced to prevent timeouts)
        sample_text = text_content[:3000]
        
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
            
        except DocumentPreAnalysisError as e:
            error_str = str(e)
            is_quota_error = '429' in error_str or 'quota' in error_str.lower()
            is_timeout_error = '504' in error_str or 'timeout' in error_str.lower() or 'Deadline Exceeded' in error_str
            
            if is_quota_error or is_timeout_error:
                logger.warning(f"{'Quota exhausted' if is_quota_error else 'Request timed out'} for subject detection, using regex fallback")
                return self._fallback_subject_detection(text_content, pattern_subjects)
            else:
                logger.error(f"Subject detection failed: {e}")
                return self._fallback_subject_detection(text_content, pattern_subjects)
        except Exception as e:
            error_str = str(e)
            is_timeout_error = '504' in error_str or 'timeout' in error_str.lower() or 'Deadline Exceeded' in error_str
            if is_timeout_error:
                logger.warning("Request timed out for subject detection, using regex fallback")
            else:
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
        # Keep larger samples for better subject detection
        text_len = len(text_content)
        max_sample = 15000  # Keep larger sample for better detection
        if text_len <= max_sample:
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
    ) -> Dict[str, Dict]:
        """
        Separate document content by subject using regex-based approach
        This is more reliable for large files than AI-based separation
        
        Args:
            text_content: Raw text from document
            subjects: List of subjects to separate
            
        Returns:
            Dictionary mapping subject to dict with 'content' and 'instructions' keys
            Format: {
                'Physics': {
                    'content': 'raw content string',
                    'instructions': 'instructions text for Physics'
                },
                ...
            }
        """
        logger.info(f"Separating content into subjects: {subjects}, document length: {len(text_content)} chars")
        
        # First try regex-based separation (more reliable for large files)
        result = self._regex_based_separation(text_content, subjects)
        
        # Check if we got meaningful content for each subject
        subjects_with_content = [s for s, data in result.items() if isinstance(data, dict) and data.get('content', '').strip()]
        
        # Log what we found
        for s in subjects:
            data = result.get(s, {})
            if isinstance(data, dict):
                content_len = len(data.get('content', ''))
                instructions_len = len(data.get('instructions', ''))
                logger.info(f"  Subject '{s}': {content_len} chars content, {instructions_len} chars instructions")
            else:
                # Backward compatibility: if old format (string), convert it
                result[s] = {'content': str(data), 'instructions': ''}
                logger.info(f"  Subject '{s}': {len(str(data))} chars (converted from old format)")
        
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
                if ai_result:
                    # Check if it's new format (dict) or old format (string)
                    has_content = False
                    for v in ai_result.values():
                        if isinstance(v, dict) and len(v.get('content', '')) > 100:
                            has_content = True
                            break
                        elif isinstance(v, str) and len(v) > 100:
                            has_content = True
                            break
                    
                    if has_content:
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
    ) -> Dict[str, Dict]:
        """
        Separate content using regex patterns to find subject sections
        Enhanced with multiple detection strategies
        Now extracts instructions for each subject
        """
        result = {s: {'content': '', 'instructions': ''} for s in subjects}
        
        # Strategy 1: Look for explicit subject headers
        subject_positions = self._find_subject_headers(text_content, subjects)
        
        if subject_positions:
            logger.info(f"Found {len(subject_positions)} subject headers")
            result = self._extract_content_by_positions(text_content, subject_positions, subjects)
            
            # Verify we got content for most subjects
            subjects_with_content = sum(1 for s in subjects if isinstance(result.get(s), dict) and result.get(s, {}).get('content', '').strip())
            if subjects_with_content >= len(subjects) * 0.5:
                return result
        
        # Strategy 2: Look for subject mentions anywhere and split around them
        logger.info("Trying flexible subject detection...")
        result = self._flexible_subject_detection(text_content, subjects)
        
        subjects_with_content = sum(1 for s in subjects if isinstance(result.get(s), dict) and result.get(s, {}).get('content', '').strip())
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
    ) -> Dict[str, Dict]:
        """Extract content between subject positions, including instructions before each subject"""
        result = {s: {'content': '', 'instructions': ''} for s in subjects}
        
        for i, (start, header_end, subject) in enumerate(positions):
            # Extract instructions before this subject section
            # Look backwards from the header start to find instructions
            instructions_start = max(0, start - 2000)  # Look up to 2000 chars before header
            instructions_text = self._extract_instructions_from_text(
                text_content[instructions_start:start]
            )
            
            # Extract content after the header
            if i + 1 < len(positions):
                next_start = positions[i + 1][0]
                content = text_content[header_end:next_start].strip()
            else:
                content = text_content[header_end:].strip()
            
            result[subject] = {
                'content': content,
                'instructions': instructions_text
            }
            
            logger.info(f"Extracted for {subject}: {len(content)} chars content, {len(instructions_text)} chars instructions")
        
        return result
    
    def _flexible_subject_detection(
        self,
        text_content: str,
        subjects: List[str]
    ) -> Dict[str, Dict]:
        """
        More flexible detection - find subject mentions and extract surrounding content
        Now also extracts instructions for each subject
        """
        result = {s: {'content': '', 'instructions': ''} for s in subjects}
        
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
            # Extract instructions before this subject section
            instructions_start = max(0, start - 2000)
            instructions_text = self._extract_instructions_from_text(
                text_content[instructions_start:start]
            )
            
            if i + 1 < len(all_mentions):
                next_start = all_mentions[i + 1][0]
                content = text_content[end:next_start].strip()
            else:
                content = text_content[end:].strip()
            
            # Append to existing content for this subject
            if result[subject]['content']:
                result[subject]['content'] += '\n\n' + content
                # Merge instructions if found
                if instructions_text and instructions_text not in result[subject]['instructions']:
                    result[subject]['instructions'] = (result[subject]['instructions'] + '\n\n' + instructions_text).strip()
            else:
                result[subject] = {
                    'content': content,
                    'instructions': instructions_text
                }
        
        return result
    
    def _extract_instructions_from_text(self, text_before_subject: str) -> str:
        """
        Extract instructions from text that appears before a subject section.
        Looks for common instruction patterns including section-specific instructions.
        EXCLUDES question content - stops when it encounters actual questions.
        """
        if not text_before_subject or len(text_before_subject.strip()) < 20:
            return ''
        
        # Reverse the text to look from the end (closest to subject header)
        text = text_before_subject[-3000:] if len(text_before_subject) > 3000 else text_before_subject
        
        # STOP when we encounter actual questions - these patterns indicate question content, not instructions
        question_indicators = [
            r'\n\s*Q\.?\s*\d+',  # Q1, Q.1, Q 1, Q. 1
            r'\n\s*Question\s*\d+',  # Question 1, Question 10
            r'\n\s*\d+\.\s+[A-Z]',  # 1. Question text starting with capital
            r'\n\s*\d+\s+[A-Z]',  # 1 Question text
            r'\n\s*\(\d+\)\s+',  # (1) Question
            r'Answer\s*\([A-D]\)',  # Answer (A) - indicates MCQ question
            r'Answer\s*:\s*\d+',  # Answer: 23 - indicates numerical question
            r'Sol\.\s+',  # Solution - indicates question solution
        ]
        
        # Find the earliest question indicator to stop extraction there
        earliest_question_pos = len(text)
        for pattern in question_indicators:
            matches = list(re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE))
            if matches:
                earliest_question_pos = min(earliest_question_pos, matches[0].start())
        
        # Only extract from text before questions
        text_before_questions = text[:earliest_question_pos] if earliest_question_pos < len(text) else text
        
        # Patterns to detect instructions - improved to catch SECTION headers
        instruction_patterns = [
            # Section headers with instructions (e.g., "## SECTION - A\nMultiple Choice Questions...")
            r'(?:^|\n)\s*##?\s*SECTION\s*[-–—]?\s*[A-Z]\s*[^\n]*(?:\n[^\n]{0,200}){0,10}(?=\n\s*(?:SECTION|PART|SUBJECT|Q\.?|\d+\.|$))',
            # Instructions keyword followed by text (but not question content)
            r'(?:^|\n).*?(?:instructions?|rules?|note|important|marking scheme|read carefully)[\s:]*[-–—]?\s*([^\n]{20,500})(?=\n\s*(?:SECTION|PART|SUBJECT|Q\.?|\d+\.|$))',
            # Marking scheme patterns
            r'(?:^|\n).*?(?:\+?\d+\s*marks?|marking|negative|correct|wrong)[^\n]{10,200}(?=\n\s*(?:SECTION|PART|SUBJECT|Q\.?|\d+\.|$))',
        ]
        
        all_instructions = []
        
        for pattern in instruction_patterns:
            matches = re.finditer(pattern, text_before_questions, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            for match in reversed(list(matches)):  # Start from the end (closest to subject)
                instruction_text = match.group(1 if match.lastindex else 0).strip()
                
                # EXCLUDE question-like content
                if any(re.search(q_pattern, instruction_text, re.IGNORECASE) for q_pattern in question_indicators):
                    continue
                
                # Filter out very short or very long matches
                if 30 <= len(instruction_text) <= 1000:
                    # Clean up the instruction text
                    instruction_text = re.sub(r'\s+', ' ', instruction_text)  # Normalize whitespace
                    # Avoid duplicates
                    if instruction_text not in all_instructions:
                        all_instructions.append(instruction_text)
                        logger.debug(f"Found instructions: {instruction_text[:100]}...")
        
        # Combine all found instructions
        if all_instructions:
            # Reverse to get chronological order (first found = first in document)
            combined = '\n\n'.join(reversed(all_instructions))
            # Final cleanup - remove any remaining question content
            combined = re.sub(r'Q\.?\s*\d+.*?$', '', combined, flags=re.IGNORECASE | re.MULTILINE)
            combined = re.sub(r'\d+\.\s+[A-Z].*?$', '', combined, flags=re.MULTILINE)
            return combined[:1000].strip()  # Limit total length
        
        return ''
    
    def _keyword_based_separation(
        self,
        text_content: str,
        subjects: List[str]
    ) -> Dict[str, Dict]:
        """
        Separate content by detecting subject-specific keywords in questions.
        DYNAMIC: Works with ANY subject - uses comprehensive keyword database
        plus dynamic fallback for unknown subjects.
        Now also extracts general instructions from document start.
        """
        result = {s: {'content': '', 'instructions': ''} for s in subjects}
        
        # Extract general instructions from document beginning (first 2000 chars)
        general_instructions = self._extract_instructions_from_text(text_content[:2000])
        
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
                result[subjects[0]] = {
                    'content': text_content,
                    'instructions': general_instructions
                }
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
        
        # Combine questions for each subject and add instructions
        for subject in subjects:
            if current_content[subject]:
                result[subject] = {
                    'content': '\n\n'.join(current_content[subject]),
                    'instructions': general_instructions  # Use general instructions for keyword-based separation
                }
        
        return result
    
    def _count_questions_in_separated_content(self, separated_content: Dict[str, Dict]) -> Dict[str, int]:
        """
        Count actual questions in each subject's separated content.
        This gives us ACCURATE counts instead of AI estimates.
        
        Args:
            separated_content: Dict mapping subject to dict with 'content' and 'instructions' keys
            
        Returns:
            Dict mapping subject to actual question count
        """
        counts = {}
        
        for subject, data in separated_content.items():
            # Handle both new format (dict) and old format (string) for backward compatibility
            if isinstance(data, dict):
                content = data.get('content', '')
            else:
                # Old format - just a string
                content = str(data)
            
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
        
        ENHANCED: Now validates question patterns more strictly to avoid false positives
        from step numbers, list items, and solution markers.
        """
        questions = []
        
        # Multiple patterns for question detection - ordered by specificity
        # Pattern 1 & 2 are most reliable; Pattern 3 needs validation
        patterns = [
            # Q1. or Q.1 or Q 1 - most specific, HIGHEST confidence
            (r'(?:^|\n)\s*Q\.?\s*(\d+)[\.:\)\s]+', 'q_prefix', 0.95),
            # Question 1 or Question: 1
            (r'(?:^|\n)\s*Question[\s:]*(\d+)[\.:\)\s]+', 'question_word', 0.95),
            # Markdown heading style: ## Q1. or ## 1.
            (r'(?:^|\n)\s*#{1,4}\s*(?:Q\.?\s*)?(\d+)[\.:\)\s]+', 'markdown_heading', 0.95),
            # Number followed by . and actual question content (needs validation)
            (r'(?:^|\n)\s*(\d+)[\.\)]\s+[A-Za-z0-9\\\$]', 'numbered', 0.70),
            # Table row pattern: | 31 | Newton's ...
            (r'(?:^|\n|\|)\s*(\d+)\s*\|\s*[A-Za-z0-9\\\$]', 'table_row', 0.90),
        ]
        
        # Truncate Answer Key / Solutions Summary to prevent double counting
        # Checks for common headers near the end of the document
        key_markers = [
            r'##\s*Answer\s*Key',
            r'ANSWER\s*KEY\s*SUMMARY',
            r'Key\s*Results',
            r'®\s*ANSWER\s*KEY',
            r'Section\s*A\s*-\s*Single\s*Correct\s*MCQ\s*\|', # Table header style
        ]
        
        check_text = text_content
        for marker in key_markers:
            match = re.search(marker, text_content, re.IGNORECASE)
            if match:
                # Only truncate if it's in the latter half of the document
                if match.start() > len(text_content) * 0.5:
                    check_text = text_content[:match.start()]
                    logger.info(f"Truncated Answer Key section at position {match.start()}")
                    break

        # Try each pattern and collect candidates
        all_unique_matches = []
        seen_ranges = [] # To avoid overlapping matches for the same question
        
        for pattern, pattern_type, confidence in patterns:
            matches = list(re.finditer(pattern, check_text, re.IGNORECASE | re.MULTILINE))
            if len(matches) >= 3:
                for match in matches:
                    try:
                        q_num = match.group(1)
                        m_start = match.start()
                        m_end = match.end()
                        
                        # Filter out common false positives (Instructions, etc.)
                        # Get the line content for context
                        line_start = check_text.rfind('\n', 0, m_start) + 1
                        line_end = check_text.find('\n', m_start)
                        if line_end == -1: line_end = len(check_text)
                        line_content = check_text[line_start:line_end].lower()
                        
                        # Skip if it looks like an instruction
                        if any(wd in line_content for wd in ['instruction', 'consist', 'carry', 'mark', 'duration', 'attempt']):
                            continue
                        
                        # Check if this question number at this position is already captured
                        # (Allow small overlap but not identical starts)
                        is_duplicate = False
                        for s_start, s_end in seen_ranges:
                            if abs(m_start - s_start) < 5: # Same starting point roughly
                                is_duplicate = True
                                break
                        
                        if not is_duplicate:
                            if pattern_type == 'numbered':
                                pre_context_start = max(0, m_start - 30)
                                pre_context = text_content[pre_context_start:m_start].lower()
                                if pre_context.rstrip().endswith(('step', 'sol.', 'sol')):
                                    continue
                                if 'step' in pre_context and '\n' not in pre_context:
                                    continue
                                if int(q_num) <= 4 and any(marker in pre_context for marker in ['option', '(a)', '(b)', '(c)', '(d)']):
                                    continue
                            
                            all_unique_matches.append(match)
                            seen_ranges.append((m_start, m_end))
                    except:
                        continue
        
        # Process all collected unique matches
        if all_unique_matches:
            # Sort all matches by their position in the document
            all_unique_matches.sort(key=lambda m: m.start())
            
            # Remove duplicate question numbers that appear VERY close to each other 
            # (different patterns matching the same thing)
            final_matches = []
            seen_nums_positions = {} # num -> last_pos
            
            for m in all_unique_matches:
                num = m.group(1)
                pos = m.start()
                
                if num in seen_nums_positions:
                    # If this number was seen recently (within 200 chars), it's likely a duplicate match
                    if pos - seen_nums_positions[num] < 200:
                        continue
                
                final_matches.append(m)
                seen_nums_positions[num] = pos
            
            logger.info(f"Collected {len(final_matches)} unique questions using merged patterns")
            
            for i, match in enumerate(final_matches):
                q_num = match.group(1)
                start = match.end()
                end = final_matches[i+1].start() if i+1 < len(final_matches) else len(text_content)
                q_text = text_content[start:end].strip()
                questions.append((q_num, q_text))
            return questions
        
        # FALLBACK: Use Answer pattern to count questions
        answer_patterns = [
            r'(?:Answer|Ans)\.?\s*[\(\[]?(\d+)[\)\]]?',
            r'##\s*Answer\s*[\(\[]?(\d+)[\)\]]?',
        ]
        
        for pattern in answer_patterns:
            matches = re.findall(pattern, text_content, re.IGNORECASE)
            if len(matches) >= 3:
                unique_nums = sorted(set(int(m) for m in matches if m.isdigit()))
                logger.info(f"Found {len(unique_nums)} questions via Answer pattern")
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
        """Build prompt for content separation by subject - NO question extraction, but includes instructions"""
        subjects_str = ', '.join(subjects)
        
        # For large documents, we should NOT use AI separation - use regex instead
        # This method is only called for smaller files (< 50000 chars) as per separate_by_subject
        # But we still need to handle the content properly
        max_content = text_content[:100000] if len(text_content) > 100000 else text_content
        
        return f"""You are a document separator. Your job is to split this document into sections by subject AND extract instructions for each subject.

SUBJECTS: {subjects_str}

INSTRUCTIONS:
1. Find where each subject's content starts and ends
2. For each subject, look for instructions that appear BEFORE that subject's section (rules, marking scheme, etc.)
3. Copy the EXACT text for each subject - do NOT summarize or modify
4. Return JSON with subject names as keys and objects containing 'content' and 'instructions'

IMPORTANT:
- Copy ALL text exactly as written
- Include ALL questions, options, answers, solutions in the 'content' field
- Extract any instructions/rules that appear before each subject section into the 'instructions' field
- If no specific instructions found for a subject, use general instructions from document start
- Do NOT summarize or describe the content
- Do NOT say "here are the questions" - just return the actual text

OUTPUT FORMAT:
```json
{{
    "Physics": {{
        "content": "[paste ALL physics content here exactly as it appears]",
        "instructions": "[paste instructions/rules for Physics section if found, otherwise general instructions]"
    }},
    "Chemistry": {{
        "content": "[paste ALL chemistry content here exactly as it appears]",
        "instructions": "[paste instructions/rules for Chemistry section if found, otherwise general instructions]"
    }}
}}
```

DOCUMENT TO SEPARATE:
{max_content}

Return JSON only with the actual content (not descriptions):"""

    def _parse_separation_response(
        self,
        response: str,
        subjects: List[str]
    ) -> Dict[str, Dict]:
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
            
            # Normalize keys and ensure new format
            normalized = {}
            for key, value in result.items():
                normalized_key = self._normalize_subject(key)
                if normalized_key in [self._normalize_subject(s) for s in subjects]:
                    # Handle both new format (dict) and old format (string) for backward compatibility
                    if isinstance(value, dict):
                        normalized[normalized_key] = {
                            'content': value.get('content', ''),
                            'instructions': value.get('instructions', '')
                        }
                    else:
                        # Old format - convert to new format
                        normalized[normalized_key] = {
                            'content': str(value),
                            'instructions': ''
                        }
            
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
        """Call Gemini API with configurable max tokens and timeout handling"""
        import time
        import re
        
        max_retries = 3  # More retries for timeout issues
        retry_delay = 5  # Start with 5 seconds for timeouts
        
        # Log API key being used (first 10 chars for security)
        api_key_preview = self.api_key[:10] + "..." if self.api_key else "None"
        logger.info(f"🔑 Using Gemini API Key: {api_key_preview} | Model: {self.model}")
        
        # Don't truncate prompts - keep full content for better analysis
        # We'll handle timeouts with retry logic instead
        logger.info(f"📝 Prompt size: {len(prompt)} chars (full content)")
        
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                logger.info(f"🤖 Calling Gemini API (attempt {attempt + 1}/{max_retries})...")
                logger.info(f"   Prompt size: {len(prompt)} chars | Max tokens: {min(max_tokens, 4096)}")
                
                response = self.client.generate_content(
                    prompt,
                    generation_config={
                        'temperature': 0.1,  # Very low for exact copying
                        'top_p': 0.95,
                        'max_output_tokens': min(max_tokens, 4096),  # Reduced to prevent timeouts
                    }
                )
                
                elapsed_time = time.time() - start_time
                
                # Handle response text extraction safely
                try:
                    response_text = response.text
                except (AttributeError, ValueError) as text_error:
                    # Fallback to parts accessor if text property doesn't work
                    try:
                        if hasattr(response, 'parts') and response.parts:
                            response_text = ''.join(part.text for part in response.parts if hasattr(part, 'text'))
                        elif hasattr(response, 'candidates') and response.candidates:
                            response_text = ''.join(
                                part.text for part in response.candidates[0].content.parts 
                                if hasattr(part, 'text')
                            )
                        else:
                            response_text = str(response)
                    except Exception as parts_error:
                        logger.warning(f"Could not extract text from response: {parts_error}")
                        response_text = str(response)
                
                logger.info(f"✅ Gemini API call SUCCESSFUL in {elapsed_time:.2f} seconds")
                logger.info(f"   Response length: {len(response_text)} chars")
                return response_text
            except Exception as e:
                error_str = str(e)
                is_quota_error = '429' in error_str or 'quota' in error_str.lower() or 'ResourceExhausted' in error_str
                is_timeout_error = '504' in error_str or 'timeout' in error_str.lower() or 'Deadline Exceeded' in error_str
                
                # For timeout errors, retry with longer delay
                if is_timeout_error and attempt < max_retries - 1:
                    logger.warning(
                        f"⏱️ TIMEOUT ERROR on attempt {attempt + 1}/{max_retries}. "
                        f"Retrying with longer delay ({retry_delay} seconds)..."
                    )
                    time.sleep(retry_delay)
                    retry_delay = retry_delay * 2  # Exponential backoff: 5s, 10s, 20s
                    continue
                elif is_timeout_error:
                    logger.error(
                        f"❌ TIMEOUT ERROR after {max_retries} attempts. "
                        f"API is taking too long. Falling back to regex."
                    )
                    raise DocumentPreAnalysisError(f"Request timed out after {max_retries} attempts")
                
                # For quota errors, retry with delay
                if is_quota_error and attempt < max_retries - 1:
                    retry_match = re.search(r'retry.*?(\d+\.?\d*)\s*s', error_str, re.IGNORECASE)
                    if retry_match:
                        retry_delay = float(retry_match.group(1)) + 2
                    else:
                        retry_delay = retry_delay * 2
                    
                    logger.warning(
                        f"Quota error on attempt {attempt + 1}/{max_retries}. "
                        f"Retrying in {retry_delay} seconds..."
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    # Not a retryable error or max retries reached
                    raise DocumentPreAnalysisError(f"Gemini API call failed: {str(e)}")
        
        # If we get here, all retries failed
        raise DocumentPreAnalysisError(f"Gemini API call failed after {max_retries} attempts")
    
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
