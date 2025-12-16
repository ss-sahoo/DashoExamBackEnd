"""
AI-Powered Question Extractor Service
Uses AI to extract ALL questions and intelligently classify them by type.
Maps questions to pattern sections based on detected question type.
"""
import json
import re
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from django.conf import settings

logger = logging.getLogger('extraction')


class SectionExtractionError(Exception):
    """Raised when extraction fails"""
    pass


@dataclass
class SectionQuestionResult:
    """Result of extracting questions for a section type"""
    section_name: str
    section_type: str
    questions: List[Dict]
    total_extracted: int
    expected_count: int
    extraction_confidence: float
    warnings: List[str]


class SectionQuestionExtractor:
    """
    AI-powered question extractor that:
    1. Extracts ALL questions from content
    2. Classifies each question by type (single_mcq, multiple_mcq, numerical, etc.)
    3. Groups questions by type for mapping to pattern sections
    """
    
    QUESTION_TYPES = {
        'single_mcq': 'Single Correct MCQ - One correct answer from options A/B/C/D',
        'multiple_mcq': 'Multiple Correct MCQ - One or more correct answers',
        'numerical': 'Numerical - Answer is a number/value',
        'true_false': 'True/False - Answer is True or False',
        'fill_blank': 'Fill in the Blank - Complete the sentence',
        'subjective': 'Subjective - Long answer/essay type',
    }
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the extractor"""
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
        
        if not self.api_key:
            raise SectionExtractionError("Gemini API key not configured")
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
        except ImportError:
            raise SectionExtractionError("google-generativeai not installed")
        except Exception as e:
            raise SectionExtractionError(f"Failed to initialize Gemini: {str(e)}")
    
    def extract_questions_by_sections(
        self,
        text_content: str,
        document_structure: Dict,
        subject: str,
        expected_question_count: int = 0,  # NEW: Expected count from pre-analysis
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """Extract questions section by section using detected document structure."""
        logger.info(f"Starting AI extraction for subject: {subject}")
        logger.info(f"Content length: {len(text_content)} chars")
        
        # Get sections from document structure
        sections = document_structure.get('sections', [])
        
        # If no sections detected, fallback to old behavior (group by type)
        if not sections:
            logger.warning("No sections detected in document_structure, falling back to type-based extraction")
            return self._extract_and_group_by_type(text_content, subject, expected_question_count, progress_callback)
        
        logger.info(f"Extracting questions from {len(sections)} detected sections")
        
        if progress_callback:
            progress_callback(10, f"Extracting from {len(sections)} sections...")
        
        try:
            results = []
            total_extracted = 0
            all_types_found = set()
            
            # Extract questions section by section
            for i, section_info in enumerate(sections):
                section_name = section_info.get('name', f'Section {i+1}')
                section_type = section_info.get('type_hint', 'mixed')
                start_marker = section_info.get('start_marker', '')
                question_range = section_info.get('question_range', '')
                expected_count = section_info.get('question_count', 0)
                
                logger.info(f"Processing section: {section_name} (type: {section_type})")
                
                if progress_callback:
                    progress_callback(10 + (i * 70 // len(sections)), f"Extracting from {section_name}...")
                
                # Extract content for this section
                section_content = self._extract_section_content(text_content, start_marker, sections, i)
                
                if not section_content:
                    logger.warning(f"Could not extract content for section: {section_name}")
                    continue
                
                # Extract questions from this section
                if expected_count > 0:
                    section_questions = self._ai_extract_and_classify(section_content, subject, expected_count)
                else:
                    # Count questions in this section
                    section_expected = self._count_questions_in_content(section_content)
                    section_questions = self._ai_extract_and_classify(section_content, subject, section_expected)
                
                # Ensure question type matches section type
                for q in section_questions:
                    # Use section type if question type doesn't match or is unclear
                    detected_type = q.get('question_type', 'single_mcq')
                    if section_type != 'mixed' and detected_type != section_type:
                        # Trust the section type hint if it's specific
                        logger.debug(f"Overriding question type {detected_type} with section type {section_type}")
                        q['question_type'] = section_type
                    all_types_found.add(q.get('question_type', section_type))
                
                result = SectionQuestionResult(
                    section_name=section_name,
                    section_type=section_type,
                    questions=section_questions,
                    total_extracted=len(section_questions),
                    expected_count=expected_count if expected_count > 0 else len(section_questions),
                    extraction_confidence=0.85,
                    warnings=[]
                )
                
                results.append(result)
                total_extracted += len(section_questions)
                logger.info(f"Section '{section_name}': {len(section_questions)} questions extracted")
            
            if progress_callback:
                progress_callback(100, "Extraction complete")
            
            # SANITY CHECK: Warn if extracted doesn't match expected
            if expected_question_count > 0 and total_extracted != expected_question_count:
                diff = total_extracted - expected_question_count
                if diff > 0:
                    logger.warning(
                        f"OVER-EXTRACTION: Got {total_extracted} questions but expected {expected_question_count}. "
                        f"{diff} extra questions may be hallucinated!"
                    )
                else:
                    logger.warning(
                        f"UNDER-EXTRACTION: Got {total_extracted} questions but expected {expected_question_count}. "
                        f"{abs(diff)} questions may be missing!"
                    )
            
            return {
                'subject': subject,
                'sections': results,
                'total_extracted': total_extracted,
                'total_expected': expected_question_count if expected_question_count > 0 else total_extracted,
                'extraction_summary': {
                    'sections_processed': len(results),
                    'types_found': list(all_types_found),
                    'completeness': (total_extracted / expected_question_count * 100) if expected_question_count > 0 else 100.0,
                    'expected_count': expected_question_count,
                    'extracted_count': total_extracted
                }
            }
            
        except Exception as e:
            logger.error(f"AI extraction failed: {e}", exc_info=True)
            raise SectionExtractionError(f"Extraction failed: {str(e)}")
    
    def _extract_and_group_by_type(
        self,
        text_content: str,
        subject: str,
        expected_question_count: int,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """Fallback: Extract all questions and group by type (old behavior)."""
        # Count actual questions in content if expected_count not provided
        if expected_question_count <= 0:
            expected_question_count = self._count_questions_in_content(text_content)
        
        if progress_callback:
            progress_callback(10, "Analyzing content with AI...")
        
        all_questions = self._ai_extract_and_classify(text_content, subject, expected_question_count)
        
        if progress_callback:
            progress_callback(70, "Grouping questions by type...")
        
        questions_by_type = self._group_by_type(all_questions)
        
        results = []
        total_extracted = 0
        
        for q_type, questions in questions_by_type.items():
            result = SectionQuestionResult(
                section_name=f"{subject} - {self._get_type_display(q_type)}",
                section_type=q_type,
                questions=questions,
                total_extracted=len(questions),
                expected_count=len(questions),
                extraction_confidence=0.85,
                warnings=[]
            )
            results.append(result)
            total_extracted += len(questions)
        
        if progress_callback:
            progress_callback(100, "Extraction complete")
        
        return {
            'subject': subject,
            'sections': results,
            'total_extracted': total_extracted,
            'total_expected': expected_question_count if expected_question_count > 0 else total_extracted,
            'extraction_summary': {
                'sections_processed': len(results),
                'types_found': list(questions_by_type.keys()),
                'completeness': (total_extracted / expected_question_count * 100) if expected_question_count > 0 else 100.0,
                'expected_count': expected_question_count,
                'extracted_count': total_extracted
            }
        }
    
    def _extract_section_content(self, text_content: str, start_marker: str, all_sections: List[Dict], section_index: int) -> str:
        """Extract content for a specific section using start_marker."""
        if not start_marker:
            # If no marker, try to find section boundaries using section name
            section_info = all_sections[section_index]
            section_name = section_info.get('name', '')
            # Try to find section header in content
            patterns = [
                re.escape(section_name),
                section_name.replace(' ', r'\s+'),
                section_name.split('-')[-1].strip() if '-' in section_name else section_name
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text_content, re.IGNORECASE)
                if match:
                    start_pos = match.start()
                    break
            else:
                # If no match found, return empty (will use full content as fallback)
                logger.warning(f"Could not find section marker for: {section_name}")
                return text_content if section_index == 0 else ""
        else:
            # Find start position using marker
            # Try exact match first
            start_pos = text_content.find(start_marker)
            if start_pos == -1:
                # Try case-insensitive
                match = re.search(re.escape(start_marker), text_content, re.IGNORECASE)
                if match:
                    start_pos = match.start()
                else:
                    # Try partial match (first few words)
                    marker_words = start_marker.split()[:3]  # First 3 words
                    marker_pattern = r'\b' + r'\s+'.join(re.escape(w) for w in marker_words) + r'\b'
                    match = re.search(marker_pattern, text_content, re.IGNORECASE)
                    if match:
                        start_pos = match.start()
                    else:
                        logger.warning(f"Could not find start_marker: {start_marker}")
                        return text_content if section_index == 0 else ""
        
        # Find end position (start of next section or end of content)
        if section_index + 1 < len(all_sections):
            next_section = all_sections[section_index + 1]
            next_marker = next_section.get('start_marker', '')
            next_name = next_section.get('name', '')
            
            # Try to find next section start
            end_pos = len(text_content)
            if next_marker:
                next_pos = text_content.find(next_marker, start_pos)
                if next_pos != -1:
                    end_pos = next_pos
            else:
                # Try finding by name
                patterns = [
                    re.escape(next_name),
                    next_name.replace(' ', r'\s+'),
                ]
                for pattern in patterns:
                    match = re.search(pattern, text_content[start_pos:], re.IGNORECASE)
                    if match:
                        end_pos = start_pos + match.start()
                        break
        else:
            end_pos = len(text_content)
        
        section_content = text_content[start_pos:end_pos]
        logger.debug(f"Extracted section content: {len(section_content)} chars from position {start_pos} to {end_pos}")
        return section_content
    
    def _count_questions_in_content(self, content: str) -> int:
        """Count actual questions in content using regex patterns"""
        patterns = [
            r'(?:^|\n)\s*Q\.?\s*(\d+)[\.\):\s]+',
            r'(?:^|\n)\s*Question[\s:]*(\d+)[\.\):\s]+',
            r'(?:^|\n)\s*\(?(\d+)\)?[\.\)]\s+',
        ]
        
        max_count = 0
        for pattern in patterns:
            matches = list(re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE))
            if len(matches) > max_count:
                max_count = len(matches)
        
        # Also try counting Answer: patterns as backup
        answer_pattern = r'(?:Answer|Ans)[\s:]+[A-Da-d]'
        answer_matches = re.findall(answer_pattern, content, re.IGNORECASE)
        if len(answer_matches) > max_count:
            max_count = len(answer_matches)
        
        logger.info(f"Counted {max_count} questions in content ({len(content)} chars)")
        return max_count
    
    def _ai_extract_and_classify(self, content: str, subject: str, expected_count: int = 0) -> List[Dict]:
        """Use AI to extract all questions and classify each by type"""
        max_chunk_size = 40000
        if len(content) > max_chunk_size:
            return self._extract_in_chunks(content, subject, max_chunk_size)
        
        prompt = self._build_extraction_prompt(content, subject, expected_count)
        
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,
                    'top_p': 0.95,
                    'max_output_tokens': 65536,
                }
            )
            
            response_text = response.text if hasattr(response, 'text') else str(response)
            questions = self._parse_ai_response(response_text, content, subject)
            logger.info(f"AI extracted {len(questions)} questions")
            
            if not questions:
                logger.warning("AI returned no questions, using fallback extraction")
                return self._fallback_extraction(content, subject)
            
            return questions
            
        except Exception as e:
            logger.error(f"AI call failed: {e}")
            return self._fallback_extraction(content, subject)
    
    def _extract_in_chunks(self, content: str, subject: str, chunk_size: int) -> List[Dict]:
        """Extract from large content in chunks"""
        all_questions = []
        chunks = self._smart_split(content, chunk_size)
        
        # Estimate questions per chunk
        total_expected = self._count_questions_in_content(content)
        questions_per_chunk = max(1, total_expected // len(chunks)) if chunks else 0
        
        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)}")
            try:
                # Count questions in this chunk for accurate extraction
                chunk_expected = self._count_questions_in_content(chunk)
                questions = self._ai_extract_and_classify(chunk, subject, chunk_expected)
                for q in questions:
                    q['question_number'] = len(all_questions) + 1
                    all_questions.append(q)
            except Exception as e:
                logger.warning(f"Chunk {i+1} failed: {e}")
                continue
        
        return all_questions
    
    def _smart_split(self, content: str, chunk_size: int) -> List[str]:
        """Split content at question boundaries"""
        chunks = []
        current_pos = 0
        
        while current_pos < len(content):
            end_pos = min(current_pos + chunk_size, len(content))
            
            if end_pos < len(content):
                search_start = max(current_pos + chunk_size - 5000, current_pos)
                search_text = content[search_start:end_pos]
                
                patterns = [r'\n\s*Q\.?\s*\d+', r'\n\s*\d+[\.\)]']
                best_break = None
                
                for pattern in patterns:
                    matches = list(re.finditer(pattern, search_text))
                    if matches:
                        last_match = matches[-1]
                        break_pos = search_start + last_match.start()
                        if best_break is None or break_pos > best_break:
                            best_break = break_pos
                
                if best_break:
                    end_pos = best_break
            
            chunks.append(content[current_pos:end_pos])
            current_pos = end_pos
        
        return chunks

    def _build_extraction_prompt(self, content: str, subject: str, expected_count: int = 0) -> str:
        """Build the AI extraction prompt with expected question count"""
        count_instruction = ""
        if expected_count > 0:
            count_instruction = f"""
**CRITICAL: This content contains EXACTLY {expected_count} questions for {subject}.**
You MUST extract exactly {expected_count} questions - no more, no less.
DO NOT hallucinate or invent questions that don't exist in the content.
"""
        
        return f"""You are an expert question extractor. Extract ALL questions from this {subject} content.
{count_instruction}
**CRITICAL: DETECT QUESTION TYPE FROM SECTION HEADERS AND CONTENT**

The document has DIFFERENT SECTIONS with different question types. Look for section headers like:
- "Section A", "SECTION A", "Section A - MCQ" -> single_mcq
- "Section B", "SECTION B", "Numerical" -> numerical  
- "Section C", "SECTION C", "True/False", "True or False" -> true_false
- "Section D", "SECTION D", "Fill in the blank", "Fill-Ups" -> fill_blank

**QUESTION TYPE RULES:**

1. **single_mcq** - Has options A/B/C/D with ONE correct answer (letter)
   - Answer format: "A", "B", "C", or "D"
   - Usually in "Section A" or "MCQ" sections

2. **numerical** - Answer is a NUMBER, not a letter
   - Answer format: "5", "3.14", "42", "100 m/s"
   - Usually in "Section B" or "Numerical" sections
   - NO options A/B/C/D, just a numeric answer

3. **true_false** - Answer is True or False
   - Answer format: "True", "False", "T", "F"
   - Usually in "Section C" or "True/False" sections
   - Questions are statements to verify

4. **fill_blank** - Has blanks (_____ or ______) to fill
   - Answer is a word or phrase that fills the blank
   - Usually in "Section D" or "Fill in the blank" sections

**OUTPUT FORMAT (JSON array):**
```json
[
  {{"question_number": 1, "question_text": "What is the acceleration?", "options": ["2 m/s", "5 m/s", "10 m/s", "20 m/s"], "correct_answer": "B", "solution": "a = F/m", "question_type": "single_mcq"}},
  {{"question_number": 31, "question_text": "Calculate the velocity.", "options": [], "correct_answer": "20", "solution": "v = sqrt(2gh)", "question_type": "numerical"}},
  {{"question_number": 61, "question_text": "Gravity is constant everywhere.", "options": [], "correct_answer": "False", "solution": "Varies with altitude", "question_type": "true_false"}},
  {{"question_number": 91, "question_text": "The SI unit of force is ______.", "options": [], "correct_answer": "Newton", "solution": "", "question_type": "fill_blank"}}
]
```

**CRITICAL RULES:**
1. LOOK AT SECTION HEADERS to determine question type
2. Questions 1-30 are usually MCQ (single_mcq)
3. Questions 31-60 are usually Numerical (numerical)
4. Questions 61-90 are usually True/False (true_false)
5. Questions 91-100 are usually Fill in the blank (fill_blank)
6. Extract EVERY question that EXISTS - don't invent or skip any
{f"7. TOTAL EXPECTED: {expected_count} questions - verify your count!" if expected_count > 0 else ""}

**CONTENT TO EXTRACT FROM:**
{content}

**Return ONLY the JSON array:**"""

    def _parse_ai_response(self, response: str, original_content: str, subject: str) -> List[Dict]:
        """Parse AI response to extract questions"""
        try:
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            questions = json.loads(json_str)
            
            if not isinstance(questions, list):
                questions = [questions]
            
            validated = []
            for q in questions:
                if not q.get('question_text', '').strip():
                    continue
                
                q.setdefault('question_type', 'single_mcq')
                q.setdefault('options', [])
                q.setdefault('correct_answer', '')
                q.setdefault('solution', '')
                q.setdefault('confidence', 0.85)
                
                q['question_type'] = self._normalize_type(q['question_type'])
                validated.append(q)
            
            return validated
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}, using fallback extraction")
            return self._fallback_extraction(original_content, subject)

    def _normalize_type(self, q_type: str) -> str:
        """Normalize question type to standard values"""
        q_type = q_type.lower().strip()
        
        type_mapping = {
            'single_mcq': 'single_mcq',
            'single': 'single_mcq',
            'mcq': 'single_mcq',
            'single correct': 'single_mcq',
            'multiple_mcq': 'multiple_mcq',
            'multiple': 'multiple_mcq',
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
        }
        
        return type_mapping.get(q_type, 'single_mcq')

    def _group_by_type(self, questions: List[Dict]) -> Dict[str, List[Dict]]:
        """Group questions by their type"""
        by_type = {}
        for q in questions:
            q_type = q.get('question_type', 'single_mcq')
            if q_type not in by_type:
                by_type[q_type] = []
            by_type[q_type].append(q)
        return by_type

    def _get_type_display(self, q_type: str) -> str:
        """Get display name for question type"""
        display_names = {
            'single_mcq': 'Single Correct MCQ',
            'multiple_mcq': 'Multiple Correct MCQ',
            'numerical': 'Numerical',
            'true_false': 'True/False',
            'fill_blank': 'Fill in the Blank',
            'subjective': 'Subjective',
        }
        return display_names.get(q_type, q_type)


    def _detect_section_types(self, content: str) -> Dict[int, str]:
        """Detect section boundaries and their question types from content."""
        section_types = {}
        
        # Common section header patterns
        section_patterns = [
            (r'Section\s*A.*?(?:MCQ|Single|Multiple\s*Choice)', 'single_mcq', (1, 30)),
            (r'SECTION\s*A.*?(?:MCQ|Single|Multiple\s*Choice)', 'single_mcq', (1, 30)),
            (r'Section\s*A.*?Q?1.*?Q?30', 'single_mcq', (1, 30)),
            (r'Section\s*B.*?(?:Numerical|Numeric|Integer)', 'numerical', (31, 60)),
            (r'SECTION\s*B.*?(?:Numerical|Numeric|Integer)', 'numerical', (31, 60)),
            (r'Section\s*B.*?Q?31.*?Q?60', 'numerical', (31, 60)),
            (r'Section\s*C.*?(?:True.*?False|T/F|Boolean)', 'true_false', (61, 90)),
            (r'SECTION\s*C.*?(?:True.*?False|T/F|Boolean)', 'true_false', (61, 90)),
            (r'Section\s*C.*?Q?61.*?Q?90', 'true_false', (61, 90)),
            (r'Section\s*D.*?(?:Fill|Blank|Fill-Up)', 'fill_blank', (91, 100)),
            (r'SECTION\s*D.*?(?:Fill|Blank|Fill-Up)', 'fill_blank', (91, 100)),
            (r'Section\s*D.*?Q?91.*?Q?100', 'fill_blank', (91, 100)),
        ]
        
        for pattern, q_type, default_range in section_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                for q_num in range(default_range[0], default_range[1] + 1):
                    section_types[q_num] = q_type
        
        if not section_types:
            range_patterns = [
                (r'Q?(\d+)\s*[-\u2013\u2014]\s*Q?(\d+).*?(?:MCQ|Single)', 'single_mcq'),
                (r'Q?(\d+)\s*[-\u2013\u2014]\s*Q?(\d+).*?(?:Numerical|Numeric)', 'numerical'),
                (r'Q?(\d+)\s*[-\u2013\u2014]\s*Q?(\d+).*?(?:True.*?False)', 'true_false'),
                (r'Q?(\d+)\s*[-\u2013\u2014]\s*Q?(\d+).*?(?:Fill|Blank)', 'fill_blank'),
            ]
            
            for pattern, q_type in range_patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    start = int(match.group(1))
                    end = int(match.group(2))
                    for q_num in range(start, end + 1):
                        section_types[q_num] = q_type
        
        return section_types

    def _get_type_for_question_number(self, q_num: int, section_types: Dict[int, str]) -> Optional[str]:
        """Get question type based on question number and detected sections"""
        return section_types.get(q_num)

    def _fallback_extraction(self, content: str, subject: str) -> List[Dict]:
        """Fallback regex-based extraction when AI fails"""
        logger.info("Using fallback regex extraction")
        questions = []
        
        section_types = self._detect_section_types(content)
        logger.info(f"Detected section types: {section_types}")
        
        patterns = [
            r'Q\.(\d+)',
            r'Q(\d+)[\.\)]',
            r'(?:^|\n)\s*(\d+)\.\s+[A-Z]',
        ]
        
        q_starts = []
        for pattern in patterns:
            q_starts = list(re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE))
            if q_starts:
                logger.info(f"Using pattern: {pattern}")
                break
        
        logger.info(f"Found {len(q_starts)} question starts")
        
        for i, match in enumerate(q_starts):
            q_num = int(match.group(1))
            start_pos = match.end()
            
            if i + 1 < len(q_starts):
                end_pos = q_starts[i + 1].start()
            else:
                end_pos = len(content)
            
            q_content = content[start_pos:end_pos].strip()
            
            if len(q_content) < 10:
                continue
            
            detected_type = self._get_type_for_question_number(q_num, section_types)
            
            question = {
                'question_number': q_num,
                'question_text': '',
                'options': [],
                'correct_answer': '',
                'solution': '',
                'question_type': detected_type or 'single_mcq',
                'confidence': 0.6
            }
            
            # Extract options
            option_pattern = r'(?:^|\n)\s*\(?([A-Da-d])\)?[\.\)]\s*(.+?)(?=(?:\n\s*\(?[A-Da-d]\)?[\.\)])|(?:\n\s*(?:Answer|Ans|Solution))|$)'
            options = re.findall(option_pattern, q_content, re.DOTALL | re.IGNORECASE)
            
            if options:
                question['options'] = [opt[1].strip() for opt in options]
                first_opt_match = re.search(r'(?:^|\n)\s*\(?[A-Da-d]\)?[\.\)]', q_content)
                if first_opt_match:
                    question['question_text'] = q_content[:first_opt_match.start()].strip()
                else:
                    question['question_text'] = q_content[:200].strip()
            else:
                question['question_text'] = q_content[:500].strip()
            
            # Extract answer
            answer = ''
            answer_patterns = [
                r'\*\*Answer:\s*([A-D])[\.\)]',
                r'\*\*Answer:\s*([A-D])\s',
                r'Answer:\s*([A-D])[\.\)]',
                r'Answer:\s*([A-D])\s',
                r'\*\*Ans(?:wer)?:\s*([A-D])',
                r'Ans(?:wer)?:\s*([A-D])',
            ]
            
            for pat in answer_patterns:
                ans_match = re.search(pat, q_content, re.IGNORECASE)
                if ans_match:
                    answer = ans_match.group(1).upper()
                    break
            
            if not answer:
                answer_match = re.search(r'(?:Answer|Ans)[\s:]+([^\n*]+)', q_content, re.IGNORECASE)
                if answer_match:
                    answer = answer_match.group(1).strip()
                    answer = re.sub(r'\*+', '', answer).strip()
                    if '\u2014' in answer:
                        answer = answer.split('\u2014')[0].strip()
                    letter_match = re.match(r'^([A-D])[\.\)]\s*', answer, re.IGNORECASE)
                    if letter_match:
                        answer = letter_match.group(1).upper()
            
            question['correct_answer'] = answer
            
            # Infer type from content if not detected from sections
            if not detected_type:
                q_text_lower = question['question_text'].lower()
                answer_lower = answer.lower() if answer else ''
                
                # Check for True/False indicators
                if 't/f:' in q_text_lower or '/f:' in q_text_lower:
                    question['question_type'] = 'true_false'
                elif '**true**' in q_text_lower or '**false**' in q_text_lower:
                    question['question_type'] = 'true_false'
                elif answer_lower in ['true', 'false', 't', 'f', 'yes', 'no']:
                    question['question_type'] = 'true_false'
                elif ',' in answer or ' and ' in answer_lower:
                    question['question_type'] = 'multiple_mcq'
                elif answer and re.match(r'^[\d\.\-]+$', answer):
                    question['question_type'] = 'numerical'
                elif '______' in question['question_text'] or '____' in question['question_text']:
                    question['question_type'] = 'fill_blank'
                elif len(answer) == 1 and answer.upper() in 'ABCDE':
                    question['question_type'] = 'single_mcq'
            
            # Extract solution
            solution_match = re.search(r'(?:Solution|Explanation)[\s:]+(.+?)(?:\n\n|$)', q_content, re.IGNORECASE | re.DOTALL)
            if solution_match:
                question['solution'] = solution_match.group(1).strip()[:500]
            
            questions.append(question)
        
        logger.info(f"Fallback extracted {len(questions)} questions")
        return questions
