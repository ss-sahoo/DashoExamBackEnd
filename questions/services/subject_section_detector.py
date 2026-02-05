"""
Subject-Level Section Detection Service
Detects sections within a specific subject's content, using subject-specific instructions.
"""
import json
import re
import logging
import time
from typing import Dict, List, Optional
from django.conf import settings

logger = logging.getLogger('extraction')


class SubjectSectionDetectionError(Exception):
    """Raised when section detection fails"""
    pass


class SubjectSectionDetector:
    """
    Detects sections within a specific subject's content.
    Uses subject-specific instructions and content to identify sections.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the detector"""
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
        
        if not self.api_key:
            raise SubjectSectionDetectionError("Gemini API key not configured")
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
        except ImportError:
            raise SubjectSectionDetectionError("google-generativeai not installed")
        except Exception as e:
            raise SubjectSectionDetectionError(f"Failed to initialize Gemini: {str(e)}")
    
    def detect_sections_for_subject(
        self,
        subject: str,
        subject_content: str,
        subject_instructions: str = '',
        expected_question_count: int = 0
    ) -> Dict:
        """
        Detect sections within a specific subject's content.
        
        Args:
            subject: Name of the subject (e.g., "Physics", "Chemistry")
            subject_content: The content for this subject
            subject_instructions: Subject-specific instructions
            expected_question_count: Expected number of questions in this subject
            
        Returns:
            Dictionary with detected sections structure
        """
        logger.info(f"Detecting sections for subject: {subject}")
        logger.info(f"Content length: {len(subject_content)} chars")
        logger.info(f"Instructions length: {len(subject_instructions)} chars")
        
        # Combine instructions and content for analysis
        full_content = subject_content
        if subject_instructions:
            full_content = f"{subject_instructions}\n\n{'='*60}\n\n{subject_content}"
        
        # First, try regex-based detection (no API call needed)
        logger.info(f"Attempting regex-based section detection for {subject}")
        regex_structure = self._detect_sections_regex(
            subject,
            full_content,
            subject_instructions,
            expected_question_count
        )
        
        # If regex found multiple sections, use it (saves API calls)
        if regex_structure and len(regex_structure.get('sections', [])) > 1:
            logger.info(f"Regex detected {len(regex_structure.get('sections', []))} sections, using regex result")
            return regex_structure
        
        # If regex found only one section or none, try AI (but with retry logic)
        logger.info(f"Regex found {len(regex_structure.get('sections', []))} sections, trying AI detection")
        
        # Build prompt for section detection
        prompt = self._build_section_detection_prompt(
            subject,
            full_content,
            subject_instructions,
            expected_question_count
        )
        
        # Try AI with retry logic for quota and timeout errors
        max_retries = 3
        retry_delay = 5  # Start with 5 seconds for timeouts
        
        # Don't truncate prompts - keep full content for better analysis
        # We'll handle timeouts with retry logic instead
        logger.info(f"📝 Prompt size: {len(prompt)} chars (full content)")
        
        for attempt in range(max_retries):
            try:
                response = self.client.generate_content(
                    prompt,
                    generation_config={
                        'temperature': 0.1,
                        'top_p': 0.95,
                        'max_output_tokens': 4096,  # Reduced to prevent timeouts
                    }
                )
                
                response_text = response.text if hasattr(response, 'text') else str(response)
                logger.info(f"AI response received, length: {len(response_text)}")
                
                # Parse the response
                structure = self._parse_section_response(response_text, subject_instructions)
                
                logger.info(
                    f"Detected {len(structure.get('sections', []))} sections for {subject}: "
                    f"{[s.get('name', 'Unknown') for s in structure.get('sections', [])]}"
                )
                
                return structure
                
            except Exception as e:
                error_str = str(e)
                is_quota_error = '429' in error_str or 'quota' in error_str.lower() or 'ResourceExhausted' in error_str
                is_timeout_error = '504' in error_str or 'timeout' in error_str.lower() or 'Deadline Exceeded' in error_str
                
                if is_timeout_error and attempt < max_retries - 1:
                    logger.warning(
                        f"⏱️ Timeout error on attempt {attempt + 1}/{max_retries}. "
                        f"Retrying with longer delay ({retry_delay} seconds)..."
                    )
                    time.sleep(retry_delay)
                    retry_delay = retry_delay * 2  # Exponential backoff: 5s, 10s, 20s
                    continue
                elif is_timeout_error:
                    logger.error(f"❌ Timeout error after {max_retries} attempts. Falling back to regex.")
                    break
                
                if is_quota_error and attempt < max_retries - 1:
                    # Extract retry delay from error if available
                    retry_match = re.search(r'retry.*?(\d+\.?\d*)\s*s', error_str, re.IGNORECASE)
                    if retry_match:
                        retry_delay = float(retry_match.group(1)) + 1  # Add 1 second buffer
                    else:
                        retry_delay = retry_delay * 2  # Exponential backoff
                    
                    logger.warning(
                        f"Quota error on attempt {attempt + 1}/{max_retries} for {subject}. "
                        f"Retrying in {retry_delay} seconds..."
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    # Not a quota error or max retries reached
                    logger.error(f"Section detection failed for {subject}: {e}", exc_info=True)
                    if is_quota_error:
                        logger.warning(f"Quota exhausted, falling back to regex-based detection for {subject}")
                    # Fall back to regex-based detection
                    return regex_structure if regex_structure else self._get_fallback_structure(
                        subject, expected_question_count, subject_instructions
                    )
        
        # If we get here, all retries failed
        logger.warning(f"All AI attempts failed for {subject}, using regex fallback")
        return regex_structure if regex_structure else self._get_fallback_structure(
            subject, expected_question_count, subject_instructions
        )
    
    def _build_section_detection_prompt(
        self,
        subject: str,
        content: str,
        instructions: str,
        expected_count: int
    ) -> str:
        """Build the AI prompt for section detection"""
        
        count_note = ""
        if expected_count > 0:
            count_note = f"\n**EXPECTED QUESTION COUNT: {expected_count} questions in this {subject} content.**"
        
        instructions_note = ""
        if instructions:
            instructions_note = f"""
**SUBJECT-SPECIFIC INSTRUCTIONS:**
{instructions}

These instructions are specific to {subject} and should guide your section detection.
"""
        
        return f"""You are an expert at analyzing exam question documents for {subject}.

**YOUR TASK:** Analyze this {subject} content and detect ALL sections present within it.

{instructions_note}

**CRITICAL: DETECT ALL SECTIONS IN THIS {subject.upper()} CONTENT**

Look for section headers like:
- "SECTION - A", "SECTION A", "Section A", "## SECTION - A"
- "SECTION - B", "SECTION B", "Section B", "## SECTION - B"
- "SECTION - C", "SECTION C", "Section C", "## SECTION - C"
- Or any other section markers

**SECTION DETECTION RULES:**

1. **FIND ALL SECTION HEADERS** in the content
   - Search for patterns: "SECTION - A", "SECTION A", "Section A", etc.
   - Each section header indicates a new section
   - A document can have MULTIPLE sections (e.g., Section A, Section B, Section C)

2. **IDENTIFY QUESTION RANGES** for each section
   - Section A might contain questions 1-20
   - Section B might contain questions 21-30
   - Look at actual question numbers in the content

3. **DETERMINE QUESTION TYPE** for each section:
   - **single_mcq**: Has options (1), (2), (3), (4) or A, B, C, D with single correct answer
   - **numerical**: Answer is a number (like "Answer (4)" or "Answer: 23"), NO options
   - **multiple_mcq**: Multiple correct answers possible
   - **true_false**: True/False questions
   - **fill_blank**: Fill in the blanks
   - **subjective**: Long answer questions

4. **USE INSTRUCTIONS** to understand section types:
   - If instructions say "Section A: Multiple Choice Questions" → type_hint = "single_mcq"
   - If instructions say "Section B: Numerical Value Type" → type_hint = "numerical"
   - If instructions mention "attempt any 5 out of 10" → type_hint = "numerical"

5. **COUNT QUESTIONS** in each section by looking at question numbers

{count_note}

**OUTPUT FORMAT (JSON only):**
```json
{{
    "has_instructions": true,
    "instructions_text": "Section-specific instructions found in content",
    "marking_scheme": {{
        "correct_marks": 4,
        "negative_marks": -1,
        "description": "+4 for correct, -1 for wrong"
    }},
    "sections": [
        {{
            "name": "SECTION - A",
            "type_hint": "single_mcq",
            "question_range": "1-20",
            "question_count": 20,
            "format_description": "4 options (1-4), single correct answer",
            "marks_per_question": 4,
            "negative_marking": -1,
            "start_marker": "SECTION - A"
        }},
        {{
            "name": "SECTION - B",
            "type_hint": "numerical",
            "question_range": "21-30",
            "question_count": 10,
            "format_description": "Numerical value type, answer is a number",
            "marks_per_question": 4,
            "negative_marking": -1,
            "start_marker": "SECTION - B"
        }}
    ],
    "question_numbering_format": "1., 2., 3...",
    "answer_format": "Answer marked after each question",
    "total_sections": 2,
    "total_questions_detected": 30
}}
```

**CRITICAL RULES:**
- **MUST DETECT ALL SECTIONS**: If content has "SECTION - A" and "SECTION - B", return BOTH
- **DO NOT** combine multiple sections into one "General" section
- **USE SECTION HEADERS** from the actual content
- **IDENTIFY QUESTION RANGES** by looking at question numbers in each section
- **DETERMINE TYPE** from section headers, instructions, and actual question format
- If you see "Answer (4)" or "Answer: 23" (number) → numerical type
- If you see "Answer (A)" or "Answer: B" (letter) → single_mcq type
- Count actual questions, don't guess

**{subject.upper()} CONTENT TO ANALYZE:**
{content[:30000]}  # Keep larger content for better analysis

**Respond with JSON only:**"""
    
    def _parse_section_response(self, response: str, subject_instructions: str) -> Dict:
        """Parse AI response for section detection"""
        default_structure = {
            'has_instructions': bool(subject_instructions),
            'instructions_text': subject_instructions[:500] if subject_instructions else '',
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
                        'start_marker': section.get('start_marker', ''),
                    })
            
            # Clean instructions_text to remove question content
            instructions_text = str(result.get('instructions_text', ''))
            if not instructions_text and subject_instructions:
                instructions_text = subject_instructions[:500]
            
            # Remove question content patterns
            instructions_text = re.sub(r'Q\.?\s*\d+.*?(?=\n|$)', '', instructions_text, flags=re.IGNORECASE | re.MULTILINE)
            instructions_text = re.sub(r'\d+\.\s+[A-Z].*?(?=\n|$)', '', instructions_text, flags=re.MULTILINE)
            instructions_text = re.sub(r'Sol\.\s+.*?(?=\n|$)', '', instructions_text, flags=re.IGNORECASE | re.MULTILINE)
            instructions_text = re.sub(r'Answer\s*\([A-D\d]+\)\s*.*?(?=\n|$)', '', instructions_text, flags=re.IGNORECASE | re.MULTILINE)
            instructions_text = re.sub(r'\s+', ' ', instructions_text).strip()
            
            # Build final structure
            structure = {
                'has_instructions': result.get('has_instructions', bool(subject_instructions)),
                'instructions_text': instructions_text[:1000],  # Limit to 1000 chars
                'marking_scheme': result.get('marking_scheme', {}),
                'sections': valid_sections,
                'question_numbering_format': result.get('question_numbering_format', 'auto-detect'),
                'answer_format': result.get('answer_format', 'auto-detect'),
                'total_sections': len(valid_sections),
                'total_questions_detected': result.get('total_questions_detected', 0)
            }
            
            return structure
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return default_structure
        except Exception as e:
            logger.error(f"Error parsing section response: {e}", exc_info=True)
            return default_structure
    
    def _normalize_question_type(self, q_type: str) -> str:
        """Normalize question type to standard values"""
        q_type = q_type.lower().strip()
        
        type_mapping = {
            'single_mcq': 'single_mcq',
            'single': 'single_mcq',
            'mcq': 'single_mcq',
            'single correct': 'single_mcq',
            'multiple choice': 'single_mcq',
            'multiple_mcq': 'multiple_mcq',
            'multiple': 'multiple_mcq',
            'multiple correct': 'multiple_mcq',
            'numerical': 'numerical',
            'numeric': 'numerical',
            'integer': 'numerical',
            'number': 'numerical',
            'true_false': 'true_false',
            'true/false': 'true_false',
            'boolean': 'true_false',
            'fill_blank': 'fill_blank',
            'fill in the blank': 'fill_blank',
            'fill': 'fill_blank',
            'subjective': 'subjective',
            'mixed': 'mixed',
        }
        
        return type_mapping.get(q_type, 'mixed')
    
    def _detect_sections_regex(
        self,
        subject: str,
        content: str,
        instructions: str,
        expected_count: int
    ) -> Dict:
        """
        Detect sections using regex patterns (no AI call needed).
        This is a fallback when API quota is exhausted.
        """
        logger.info(f"Using regex-based section detection for {subject}")
        
        sections = []
        
        # Pattern to find section headers
        section_patterns = [
            r'(?:^|\n)\s*##?\s*SECTION\s*[-–—]?\s*([A-Z])\s*[^\n]*(?:\n|$)',
            r'(?:^|\n)\s*SECTION\s*[-–—]?\s*([A-Z])\s*[^\n]*(?:\n|$)',
            r'(?:^|\n)\s*Section\s*[-–—]?\s*([A-Z])\s*[^\n]*(?:\n|$)',
        ]
        
        section_markers = []
        for pattern in section_patterns:
            matches = list(re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE))
            for match in matches:
                section_letter = match.group(1).upper()
                section_markers.append({
                    'letter': section_letter,
                    'position': match.start(),
                    'full_match': match.group(0).strip()
                })
        
        # Sort by position
        section_markers.sort(key=lambda x: x['position'])
        
        # Remove duplicates (same section letter)
        seen_letters = set()
        unique_markers = []
        for marker in section_markers:
            if marker['letter'] not in seen_letters:
                seen_letters.add(marker['letter'])
                unique_markers.append(marker)
        
        logger.info(f"Found {len(unique_markers)} section markers: {[m['letter'] for m in unique_markers]}")
        
        if len(unique_markers) == 0:
            # No sections found, return single section
            return self._get_fallback_structure(subject, expected_count, instructions)
        
        # For each section, determine question range and type
        for i, marker in enumerate(unique_markers):
            section_letter = marker['letter']
            start_pos = marker['position']
            
            # Find end position (next section or end of content)
            if i + 1 < len(unique_markers):
                end_pos = unique_markers[i + 1]['position']
            else:
                end_pos = len(content)
            
            section_content = content[start_pos:end_pos]
            
            # Detect question range by finding question numbers in this section
            question_patterns = [
                r'(?:^|\n)\s*(\d+)\.\s+',
                r'(?:^|\n)\s*Q\.?\s*(\d+)',
                r'(?:^|\n)\s*\((\d+)\)\s+',
            ]
            
            question_numbers = []
            for pattern in question_patterns:
                matches = re.finditer(pattern, section_content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    q_num = int(match.group(1))
                    if q_num not in question_numbers:
                        question_numbers.append(q_num)
            
            question_numbers.sort()
            
            # Determine question type from content
            type_hint = 'mixed'
            if 'numerical' in section_content.lower() or 'numeric' in section_content.lower():
                type_hint = 'numerical'
            elif 'multiple choice' in section_content.lower() or 'mcq' in section_content.lower():
                type_hint = 'single_mcq'
            elif 'true' in section_content.lower() and 'false' in section_content.lower():
                type_hint = 'true_false'
            
            # Check answer format to determine type
            if re.search(r'Answer\s*\((\d+)\)', section_content, re.IGNORECASE):
                type_hint = 'numerical'
            elif re.search(r'Answer\s*\(([A-D])\)', section_content, re.IGNORECASE):
                type_hint = 'single_mcq'
            
            # Determine question range
            if question_numbers:
                question_range = f"{min(question_numbers)}-{max(question_numbers)}"
                question_count = len(question_numbers)
            else:
                # Estimate based on expected count and number of sections
                if expected_count > 0 and len(unique_markers) > 0:
                    questions_per_section = expected_count // len(unique_markers)
                    start_q = (ord(section_letter) - ord('A')) * questions_per_section + 1
                    end_q = start_q + questions_per_section - 1
                    question_range = f"{start_q}-{end_q}"
                    question_count = questions_per_section
                else:
                    question_range = 'Unknown'
                    question_count = 0
            
            sections.append({
                'name': f'SECTION - {section_letter}',
                'type_hint': type_hint,
                'question_range': question_range,
                'question_count': question_count,
                'format_description': f'Section {section_letter} questions',
                'start_marker': marker['full_match']
            })
        
        return {
            'has_instructions': bool(instructions),
            'instructions_text': instructions[:1000] if instructions else '',
            'marking_scheme': {},
            'sections': sections,
            'question_numbering_format': 'auto-detect',
            'answer_format': 'auto-detect',
            'total_sections': len(sections),
            'total_questions_detected': sum(s.get('question_count', 0) for s in sections) or expected_count
        }
    
    def _get_fallback_structure(
        self,
        subject: str,
        expected_count: int,
        instructions: str
    ) -> Dict:
        """Get a basic fallback structure when detection fails"""
        return {
            'has_instructions': bool(instructions),
            'instructions_text': instructions[:500] if instructions else '',
            'marking_scheme': {},
            'sections': [{
                'name': f'{subject} - General',
                'type_hint': 'mixed',
                'question_range': f'1-{expected_count}' if expected_count > 0 else 'All',
                'question_count': expected_count,
                'format_description': 'Mixed question types',
                'start_marker': ''
            }],
            'question_numbering_format': 'auto-detect',
            'answer_format': 'auto-detect',
            'total_sections': 1,
            'total_questions_detected': expected_count
        }

