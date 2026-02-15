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
    
    # Configuration for retry logic
    RETRY_THRESHOLD = 0.8  # Retry if extracted < 80% of expected
    MAX_EXTRACTION_RETRIES = 2  # Maximum retry attempts
    
    def extract_questions_by_sections(
        self,
        text_content: str,
        document_structure: Dict,
        subject: str,
        expected_question_count: int = 0,  # NEW: Expected count from pre-analysis
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """Extract ALL questions and classify them by type using AI.
        
        ENHANCED: Now includes:
        - Retry logic if extraction count < 80% of expected
        - Improved deduplication across chunks
        - Section type enforcement from document structure
        """
        logger.info(f"Starting AI extraction for subject: {subject}")
        
        # Preprocess content to handle problematic base64 SVG and truncate Answer Keys
        text_content = self._preprocess_content(text_content)
        logger.info(f"Content length: {len(text_content)} chars")
        
        # Count actual questions in content if expected_count not provided
        if expected_question_count <= 0:
            expected_question_count = self._count_questions_in_content(text_content)
        
        logger.info(f"Expected question count for {subject}: {expected_question_count}")
        
        if progress_callback:
            progress_callback(10, "Analyzing content with AI...")
        
        try:
            # ENHANCED: Extract with retry logic
            all_questions = self._extract_with_retry(
                text_content, subject, document_structure, 
                expected_question_count, progress_callback
            )
            
            # ENHANCED: Apply improved deduplication
            all_questions = self._deduplicate_questions(all_questions)
            logger.info(f"After deduplication: {len(all_questions)} questions")
            
            # ENHANCED: Enforce section types before mapping
            all_questions = self._enforce_section_types(all_questions, document_structure)
            
            if progress_callback:
                progress_callback(70, "Mapping questions to sections...")
            
            # Use detected sections to group questions
            results = []
            total_extracted = 0
            assigned_indices = set()
            
            detected_sections = document_structure.get('sections', [])
            
            if not detected_sections:
                # Fallback to type-based grouping if no sections detected
                questions_by_type = self._group_by_type(all_questions)
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
                    logger.info(f"Type '{q_type}': {len(questions)} questions")
            else:
                for section in detected_sections:
                    section_name = section.get('name', 'Unknown Section')
                    type_hint = section.get('type_hint', 'mixed')
                    q_range_str = section.get('question_range', '')
                    
                    section_questions = []
                    # Parse range (e.g., "1-10")
                    try:
                        if '-' in q_range_str:
                            start_q, end_q = map(int, q_range_str.split('-'))
                            for i, q in enumerate(all_questions):
                                q_num = q.get('question_number', 0)
                                if start_q <= q_num <= end_q:
                                    # RE-CLASSIFY: If section has a specific type, enforce it
                                    if type_hint and type_hint != 'mixed' and q.get('question_type') != type_hint:
                                        logger.info(f"Mapping Q{q_num} to {type_hint} based on {section_name}")
                                        q['question_type'] = type_hint
                                    
                                    section_questions.append(q)
                                    assigned_indices.add(i)
                    except Exception as e:
                        logger.warning(f"Failed to map questions to section {section_name}: {e}")

                    results.append(SectionQuestionResult(
                        section_name=section_name,
                        section_type=type_hint,
                        questions=section_questions,
                        total_extracted=len(section_questions),
                        expected_count=section.get('question_count', 0),
                        extraction_confidence=0.9,
                        warnings=[]
                    ))
                    total_extracted += len(section_questions)
                    logger.info(f"Section '{section_name}': {len(section_questions)} questions")

                # Handle unassigned questions
                unassigned = [q for i, q in enumerate(all_questions) if i not in assigned_indices]
                if unassigned:
                    # Group remaining by type
                    remaining_by_type = self._group_by_type(unassigned)
                    for q_type, questions in remaining_by_type.items():
                        results.append(SectionQuestionResult(
                            section_name=f"{subject} - Extra {self._get_type_display(q_type)}",
                            section_type=q_type,
                            questions=questions,
                            total_extracted=len(questions),
                            expected_count=0,
                            extraction_confidence=0.7,
                            warnings=["These questions were found outside detected section ranges"]
                        ))
                        total_extracted += len(questions)
                        logger.info(f"Extra Type '{q_type}': {len(questions)} questions")

            if progress_callback:
                progress_callback(100, "Extraction complete")
            
            # Use original count if total_extracted is 0 or very different
            display_expected = expected_question_count if expected_question_count > 0 else total_extracted
            
            return {
                'subject': subject,
                'sections': results,
                'total_extracted': total_extracted,
                'total_expected': display_expected,
                'extraction_summary': {
                    'sections_processed': len(results),
                    'types_found': list(set([s.section_type for s in results])),
                    'completeness': (total_extracted / display_expected * 100) if display_expected > 0 else 100.0,
                    'expected_count': display_expected,
                    'extracted_count': total_extracted
                }
            }
            
        except Exception as e:
            logger.error(f"AI extraction failed: {e}", exc_info=True)
            raise SectionExtractionError(f"Extraction failed: {str(e)}")
    
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
    
    def _extract_with_retry(
        self,
        text_content: str,
        subject: str,
        document_structure: Dict,
        expected_count: int,
        progress_callback: Optional[callable] = None
    ) -> List[Dict]:
        """
        Extract questions with retry logic if count is below threshold.
        
        If extracted count < 80% of expected, retry with more aggressive extraction.
        """
        all_questions = self._ai_extract_and_classify(
            text_content, subject, document_structure, expected_count
        )
        
        extracted_count = len(all_questions)
        
        # Check if we need to retry
        if expected_count > 0 and extracted_count < expected_count * self.RETRY_THRESHOLD:
            logger.warning(
                f"Extraction incomplete: {extracted_count}/{expected_count} "
                f"({extracted_count/expected_count*100:.1f}%). Retrying with aggressive extraction..."
            )
            
            for retry in range(self.MAX_EXTRACTION_RETRIES):
                if progress_callback:
                    progress_callback(
                        30 + retry * 15, 
                        f"Retry {retry + 1}: Re-extracting missing questions..."
                    )
                
                # Try aggressive extraction with smaller chunks and explicit missing ranges
                missing_questions = self._extract_missing_questions(
                    text_content, subject, document_structure, 
                    all_questions, expected_count
                )
                
                if missing_questions:
                    # Merge with existing questions
                    existing_nums = {q.get('question_number') for q in all_questions}
                    for q in missing_questions:
                        if q.get('question_number') not in existing_nums:
                            all_questions.append(q)
                            existing_nums.add(q.get('question_number'))
                    
                    logger.info(
                        f"Retry {retry + 1}: Added {len(missing_questions)} questions. "
                        f"Total now: {len(all_questions)}"
                    )
                
                # Check if we've reached threshold
                if len(all_questions) >= expected_count * self.RETRY_THRESHOLD:
                    logger.info(f"Reached threshold after retry {retry + 1}")
                    break
        
        return all_questions
    
    def _extract_missing_questions(
        self,
        text_content: str,
        subject: str,
        document_structure: Dict,
        existing_questions: List[Dict],
        expected_count: int
    ) -> List[Dict]:
        """
        Extract questions that were missed in the initial extraction.
        Uses smaller chunks and focuses on missing question numbers.
        """
        existing_nums = {q.get('question_number') for q in existing_questions if q.get('question_number')}
        
        # Find missing question numbers
        all_expected_nums = set(range(1, expected_count + 1))
        missing_nums = all_expected_nums - existing_nums
        
        if not missing_nums:
            logger.info("No missing question numbers detected")
            return []
        
        logger.info(f"Missing question numbers: {sorted(missing_nums)[:20]}...")
        
        # Try to extract missing questions using fallback regex method
        # This is more reliable for specific question numbers
        fallback_questions = self._fallback_extraction(text_content, subject)
        
        # Filter to only missing numbers
        missing_questions = [
            q for q in fallback_questions 
            if q.get('question_number') in missing_nums
        ]
        
        logger.info(f"Found {len(missing_questions)} missing questions via fallback extraction")
        return missing_questions
    
    def _deduplicate_questions(self, questions: List[Dict]) -> List[Dict]:
        """
        Remove duplicate questions using multiple strategies:
        1. Exact question number match
        2. Text similarity for questions without numbers
        
        ENHANCED: Uses text similarity to catch near-duplicates.
        """
        if not questions:
            return []
        
        unique_questions = []
        seen_numbers = set()
        seen_text_hashes = set()
        
        for q in questions:
            q_num = q.get('question_number')
            q_text = q.get('question_text', '').strip()
            
            # Skip empty questions
            if not q_text:
                continue
            
            # Strategy 1: Check by question number
            if q_num is not None:
                if q_num in seen_numbers:
                    logger.debug(f"Skipping duplicate question number: {q_num}")
                    continue
                seen_numbers.add(q_num)
            
            # Strategy 2: Check by text similarity (first 100 chars normalized)
            text_hash = self._get_text_hash(q_text)
            if text_hash in seen_text_hashes:
                logger.debug(f"Skipping duplicate question text: {q_text[:50]}...")
                continue
            seen_text_hashes.add(text_hash)
            
            unique_questions.append(q)
        
        removed_count = len(questions) - len(unique_questions)
        if removed_count > 0:
            logger.info(f"Deduplication removed {removed_count} duplicate questions")
        
        return unique_questions
    
    def _get_text_hash(self, text: str) -> str:
        """
        Generate a normalized hash for text comparison.
        Removes whitespace, punctuation, and converts to lowercase.
        """
        import hashlib
        
        # Normalize text
        normalized = text.lower()
        normalized = re.sub(r'\s+', '', normalized)  # Remove whitespace
        normalized = re.sub(r'[^\w]', '', normalized)  # Remove punctuation
        normalized = normalized[:150]  # Use first 150 chars for comparison
        
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def _enforce_section_types(
        self,
        questions: List[Dict],
        document_structure: Dict
    ) -> List[Dict]:
        """
        Enforce question types based on section structure.
        
        If a question falls within a section's range, override its type
        with the section's type_hint (unless it's 'mixed').
        """
        sections = document_structure.get('sections', [])
        if not sections:
            return questions
        
        # Build a mapping of question number ranges to types
        range_to_type = {}
        for section in sections:
            type_hint = section.get('type_hint', 'mixed')
            if type_hint == 'mixed':
                continue
            
            q_range = section.get('question_range', '')
            if '-' in q_range:
                try:
                    start, end = map(int, q_range.split('-'))
                    for num in range(start, end + 1):
                        range_to_type[num] = type_hint
                except ValueError:
                    continue
        
        # Apply type overrides
        overrides_applied = 0
        for q in questions:
            q_num = q.get('question_number')
            if q_num and q_num in range_to_type:
                expected_type = range_to_type[q_num]
                current_type = q.get('question_type', 'single_mcq')
                
                if current_type != expected_type:
                    logger.debug(
                        f"Overriding Q{q_num} type: {current_type} -> {expected_type}"
                    )
                    q['question_type'] = expected_type
                    overrides_applied += 1
        
        if overrides_applied > 0:
            logger.info(f"Applied {overrides_applied} question type overrides from section structure")
        
        return questions
    
    def _preprocess_content(self, content: str) -> str:
        """Preprocess content to handle problematic elements before AI extraction.
        
        - Replaces inline base64 SVG/image data with placeholders
        - Truncates answer key / solution summary sections to prevent duplicates
        """
        # Replace inline base64 SVG images that can cause JSON parsing issues
        base64_svg_pattern = r'<img[^>]*src="data:image/svg\+xml;base64,[^"]+?"[^>]*>'
        content = re.sub(base64_svg_pattern, '[CHEMISTRY_STRUCTURE_IMAGE]', content, flags=re.IGNORECASE)
        
        # Also handle generic base64 images
        base64_img_pattern = r'<img[^>]*src="data:image/[^;]+;base64,[^"]+?"[^>]*>'
        content = re.sub(base64_img_pattern, '[INLINE_IMAGE]', content, flags=re.IGNORECASE)
        
        # Truncate Answer Key / Solutions Summary to prevent duplicate extraction
        key_markers = [
            r'##\s*Answer\s*Key',
            r'ANSWER\s*KEY\s*SUMMARY',
            r'Key\s*Results',
            r'®\s*ANSWER\s*KEY',
            r'Section\s*A\s*-\s*Single\s*Correct\s*MCQ\s*\|', # Table header style
        ]
        
        for marker in key_markers:
            match = re.search(marker, content, re.IGNORECASE)
            if match:
                # Only truncate if it's in the latter half of the document
                if match.start() > len(content) * 0.5:
                    logger.info(f"Truncating Answer Key section at position {match.start()} for AI extraction")
                    content = content[:match.start()]
                    break

        return content

    def _ai_extract_and_classify(self, content: str, subject: str, document_structure: Dict, expected_count: int = 0) -> List[Dict]:
        """Use AI to extract all questions and classify each by type"""
        # Preprocess content to handle problematic base64 SVG images
        content = self._preprocess_content(content)
        
        max_chunk_size = 40000
        if len(content) > max_chunk_size:
            return self._extract_in_chunks(content, subject, max_chunk_size)
        
        prompt = self._build_extraction_prompt(content, subject, document_structure, expected_count)
        
        logger.info(f"Gemini Extraction Prompt for {subject}:")
        logger.info(prompt[:500] + "... (truncated)" if len(prompt) > 2000 else prompt)
        
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
            
            logger.warning("Gemini Raw Response for Section Extraction:")
            logger.warning(response_text[:1000] + "... (truncated)" if len(response_text) > 5000 else response_text)
            
            questions = self._parse_ai_response(response_text, content, subject)
            
            # POST-PROCESS: Filter out instruction-like questions and deduplicate
            filtered_questions = []
            seen_q_nums = set()
            instruction_keywords = [
                'instruction', 'mark the correct', 'marks are awarded', 
                'four options', 'no negative marking', 'consists of', 
                'blue/black pen', 'rough work', 'do not use', 'mark t or f',
                'each question carries'
            ]
            
            for q in questions:
                q_text = q.get('question_text', '').lower()
                q_num = q.get('question_number')
                
                # Check for instructions masquerading as questions
                is_instruction = False
                if any(kw in q_text for kw in instruction_keywords):
                    # It looks like an instruction, check if it's ONLY an instruction
                    if '?' not in q_text and 'find' not in q_text and 'calculate' not in q_text and \
                       'derive' not in q_text and 'state' not in q_text and 'explain' not in q_text:
                        is_instruction = True
                
                if is_instruction:
                    logger.info(f"Filtering out instruction-like question: {q_text[:50]}...")
                    continue
                
                # Basic deduplication for same extraction chunk
                if q_num:
                    q_key = f"{q_num}_{q_text[:50]}"
                    if q_key in seen_q_nums:
                        continue
                    seen_q_nums.add(q_key)
                
                filtered_questions.append(q)
            
            logger.info(f"AI extracted {len(filtered_questions)} questions (filtered from {len(questions)})")
            
            if not filtered_questions:
                logger.warning("AI returned no questions after filtering, using fallback extraction")
                return self._fallback_extraction(content, subject)
            
            return filtered_questions
            
        except Exception as e:
            logger.error(f"AI call failed: {e}")
            return self._fallback_extraction(content, subject)
    
    def _extract_in_chunks(self, content: str, subject: str, chunk_size: int) -> List[Dict]:
        """Extract from large content in chunks with preserved numbering"""
        all_questions = []
        chunks = self._smart_split(content, chunk_size)
        
        logger.info(f"Splitting {subject} into {len(chunks)} chunks for extraction")
        
        # Use a seen set to prevent duplicate extraction across chunk boundaries
        seen_questions = set()

        for i, chunk in enumerate(chunks):
            logger.info(f"Processing chunk {i+1}/{len(chunks)}")
            try:
                # Count questions in this chunk for accurate extraction
                chunk_expected = self._count_questions_in_content(chunk)
                
                # Use a specific prompt that doesn't re-trigger chunking
                prompt = self._build_extraction_prompt(chunk, subject, {}, chunk_expected)
                
                response = self.client.generate_content(
                    prompt,
                    generation_config={
                        'temperature': 0.1,
                        'top_p': 0.95,
                        'max_output_tokens': 65536,
                    }
                )
                
                response_text = response.text if hasattr(response, 'text') else str(response)
                questions = self._parse_ai_response(response_text, chunk, subject)
                
                for q in questions:
                    q_num = q.get('question_number')
                    q_text = q.get('question_text', '')[:100]
                    q_key = f"{q_num}_{q_text}"
                    
                    if q_key not in seen_questions:
                        all_questions.append(q)
                        seen_questions.add(q_key)
                
            except Exception as e:
                logger.error(f"Chunk {i+1} extraction failed: {e}")
                
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

    def _build_extraction_prompt(self, content: str, subject: str, document_structure: Dict, expected_count: int = 0) -> str:
        """Build the AI extraction prompt with expected question count and detected structure"""
        count_instruction = ""
        if expected_count > 0:
            count_instruction = f"""
**CRITICAL: This content contains EXACTLY {expected_count} questions for {subject}.**
You MUST extract exactly {expected_count} questions - no more, no less.
DO NOT hallucinate or invent questions that don't exist in the content.
"""
        
        structure_instruction = ""
        if document_structure and document_structure.get('sections'):
            sections = document_structure['sections']
            sections_str = "\n".join([
                f"- {s.get('name')}: {s.get('type_hint')} (Questions {s.get('question_range')})" 
                for s in sections
            ])
            structure_instruction = f"""
**DETECTED DOCUMENT STRUCTURE:**
The following sections were detected in this document:
{sections_str}

Use this structure to guide your 'question_type' classification for each question.
"""

        return f"""You are an expert question extractor. Extract ALL questions from this {subject} content.
{count_instruction}
{structure_instruction}

**CRITICAL: DETECT QUESTION TYPE FROM SECTION HEADERS AND CONTENT**
Look for section headers (e.g. "SECTION A", "SECTION B") to determine the type of questions that follow.
**MATCH EACH QUESTION TO THE CORRECT 'question_type' FROM THE DETECTED DOCUMENT STRUCTURE CORRESPONDING TO ITS QUESTION NUMBER.**
**QUESTION TYPE RULES:**

1. **single_mcq** - Multiple Choice Questions
   - Options can be labeled (1), (2), (3), (4) OR (A), (B), (C), (D) or just A, B, C, D.
   - EXTRACT OPTIONS INTO THE 'options' LIST. Do not keep them in question_text.
   - Answer format: "1", "2", "3", "4" OR "A", "B", "C", "D"

2. **multiple_mcq** - ONE OR MORE correct answers from options A/B/C/D
   - Same format as single_mcq but may have multiple letters in 'correct_answer' (e.g. "A, B, D")

3. **numerical** - Answer is a NUMBER (Integer or Decimal)
   - Answer format: "5", "3.14", "42", "100"
   - NO options, just a direct numeric answer.

4. **true_false** - Answer is True or False
   - Questions are statements to verify.

5. **fill_blank** - Has blanks (_____ or ______) to fill
   - Answer is the word or phrase that fills the blank.

6. **subjective** - Open-ended questions requiring a descriptive or derivation-based answer.

**FIELD SEPARATION RULES (CRITICAL):**
- **question_text**: The main question ONLY. Do NOT include options (A, B, C, D) or the 'Sol.' text here.
- **options**: Array of option strings. 
  - **CRITICAL**: If multiple options are on one line (e.g., "(A) 10m (B) 20m"), YOU MUST SPLIT them into separate elements in the array.
  - Remove labels (A), (B), (C), (D) or (1), (2), (3), (4).
  - Example output: `["10m", "20m", "30m", "40m"]`.
- **correct_answer**: 
  - If "Answer: (B)" or similar is found, use "B".
  - If an option has a marker like `\boxtimes`, `\checkmark`, `[X]`, `(X)`, or is **bolded**, that is the correct answer. 
  - Convert markers to labels (e.g., if option B has `\boxtimes`, correct_answer is "B").
- **solution**: Text starting after "Sol.", "Solution:", or "Explanation:".

**CRITICAL RULES:**
1. **EXTRACT ONLY ACTUAL QUESTIONS**. 
   - DO NOT extract text that starts with "Instructions:", "Note:", "Directions:", "Section:", or "Date:".
   - DO NOT extract rules about marking schemes (e.g., "+4 marks", "no negative marking").
   - DO NOT extract text that describes how to use the OMR sheet.
   - If a question number is found in a line of instructions, IGNORE IT.
2. **SPLIT IN-LINE OPTIONS**: If you see `(A) option1 (B) option2`, you MUST produce `["option1", "option2"]`. NEVER put both in one string.
3. LOOK AT SECTION HEADERS and the provided structure to determine question type.
4. Extract EVERY question that ACTUALLY EXISTS in the content - don't invent or skip any.
5. If the content only has Questions 1-30, DO NOT output Question 31, 61, or 91.
6. **PRESERVE IMAGE LINKS**: If you see image links like `![](https://cdn.mathpix.com/...)`, include them EXACTLY as they are in the `question_text` or `solution`.
7. **TOTAL EXPECTED: {expected_count} questions** - if you find significantly more or less, double-check your extraction!

**OUTPUT FORMAT (JSON array):**
```json
[
  {{
    "question_number": 1, 
    "question_text": "What is the acceleration? ![](https://cdn.mathpix.com/example.jpg)", 
    "options": ["2 m/s", "5 m/s", "10 m/s", "20 m/s"], 
    "correct_answer": "B", 
    "solution": "a = F/m", 
    "question_type": "single_mcq"
  }}
]
```

**CONTENT TO EXTRACT FROM:**
{content}

**IGNORE PAGE HEADERS/FOOTERS:**
- Ignore text like "Page no. 128", "Exam 2024", "Space for rough work"
- Do not treat them as part of the question text

**Return ONLY the JSON array:**"""

    def _parse_ai_response(self, response: str, original_content: str, subject: str) -> List[Dict]:
        """Parse AI response to extract questions with robust JSON handling"""
        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            # Clean up the string before parsing
            json_str = json_str.strip()
            # Remove markdown code blocks if still present (double check)
            json_str = re.sub(r'^```json\s*', '', json_str, flags=re.MULTILINE)
            json_str = re.sub(r'^```\s*', '', json_str, flags=re.MULTILINE)
            json_str = re.sub(r'\s*```$', '', json_str, flags=re.MULTILINE)

            # Try multiple parsing strategies
            questions = None
            parse_errors = []
            
            # Strategy 1: Direct JSON parse
            try:
                questions = json.loads(json_str)
            except json.JSONDecodeError as e:
                parse_errors.append(f"Direct parse: {e}")
            
            # Strategy 2: Fix trailing commas
            if questions is None:
                try:
                    fixed_str = re.sub(r',\s*([\]}])', r'\1', json_str)
                    questions = json.loads(fixed_str)
                    logger.info("JSON parsed after fixing trailing commas")
                except json.JSONDecodeError as e:
                    parse_errors.append(f"Trailing comma fix: {e}")
            
            # Strategy 3: Handle truncated response - find last complete object
            if questions is None:
                try:
                    # Find the last complete JSON object by looking for "},"
                    last_complete = json_str.rfind('},')
                    if last_complete > 0:
                        truncated_str = json_str[:last_complete + 1] + ']'
                        questions = json.loads(truncated_str)
                        logger.warning(f"JSON parsed from truncated response, recovered partial data")
                except Exception as e:
                    parse_errors.append(f"Truncation fix: {e}")
            
            # Strategy 4: Try ast.literal_eval (more forgiving)
            if questions is None:
                try:
                    import ast
                    questions = ast.literal_eval(json_str)
                except Exception as e:
                    parse_errors.append(f"ast.literal_eval: {e}")
            
            # Strategy 5: Extract individual question objects with regex
            if questions is None:
                try:
                    # Match individual question objects
                    q_pattern = r'\{[^{}]*"question_text"\s*:\s*"[^"]*"[^{}]*\}'
                    q_matches = re.findall(q_pattern, json_str, re.DOTALL)
                    if q_matches:
                        questions = []
                        for q_match in q_matches:
                            try:
                                q_obj = json.loads(q_match)
                                questions.append(q_obj)
                            except:
                                continue
                        if questions:
                            logger.warning(f"Extracted {len(questions)} questions via regex pattern matching")
                except Exception as e:
                    parse_errors.append(f"Regex extraction: {e}")
            
            if questions is None:
                logger.warning(f"All JSON parse strategies failed: {parse_errors}")
                raise json.JSONDecodeError("Failed to repair JSON", json_str, 0)

            if not isinstance(questions, list):
                if isinstance(questions, dict) and 'questions' in questions:
                    questions = questions['questions']
                else:
                    questions = [questions]
            
            validated = []
            for q in questions:
                if not q.get('question_text', '').strip():
                    continue
                
                # Normalize the question data (split options, detect answer markers)
                q = self._normalize_question_data(q)
                
                q.setdefault('question_type', 'single_mcq')
                q.setdefault('confidence', 0.85)
                q['question_type'] = self._normalize_type(q.get('question_type', 'single_mcq'))
                
                validated.append(q)
            
            return validated
            
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse failed: {e}, using fallback extraction")
            return self._fallback_extraction(original_content, subject)

    def _normalize_question_data(self, q: Dict) -> Dict:
        """
        Post-process AI extraction to fix common issues:
        1. Split merged options (e.g., ["(A) 10m (B) 20m"])
        2. Clean labels from options
        3. Detect correct answers from visual markers (\boxtimes, bold, etc.)
        """
        options = q.get('options', [])
        if not isinstance(options, list):
            options = [str(options)] if options else []
        
        new_options = []
        correct_answer_index = None

        # 1. SPLIT MERGED OPTIONS
        # If AI returns ["(A) 10m (B) 20m", "(C) 30m (D) 40m"], split them
        for opt_text in options:
            if not opt_text: continue
            
            # Pattern to find labels inside strings: (B) or (C) or (D)
            # but only if preceded by some text to avoid splitting the legitimate first label
            split_pattern = r'\s+[\(\[]?([B-Db-d2-4])[\)\]\.]\s+'
            
            if re.search(split_pattern, opt_text):
                # Found merging. Use regex to find all segments starting with a label
                # This pattern matches (A) text, (B) text, etc.
                segments = re.split(r'\s*[\(\[]?[A-Da-d1-4][\)\]\.]\s*', ' ' + opt_text)
                # Filter out empty segments from split
                segments = [s.strip() for s in segments if s.strip()]
                new_options.extend(segments)
            else:
                # Clean single label if present at start
                cleaned = re.sub(r'^[\(\[]?[A-Da-d1-4][\)\]\.]\s*', '', opt_text).strip()
                new_options.append(cleaned)

        # 2. DETECT CORRECT ANSWER MARKERS (\boxtimes, bold, etc.)
        # If answer is already set as a letter, keep it unless we find a specific marker
        has_explicit_answer = bool(q.get('correct_answer'))
        
        # Labels for mapping index to A, B, C, D
        labels = ['A', 'B', 'C', 'D', 'E', 'F']
        
        for i, opt in enumerate(new_options):
            # Check for LaTeX checked box or bolding which often denotes the answer key in OCR
            markers = [
                r'\\boxtimes', 
                r'\\checkmark', 
                r'\\textbf', 
                r'\\mathbf', 
                r'\*\*.*?\*\*', # Markdown bold
                r'\[x\]', 
                r'\(x\)',
                r'correct'
            ]
            
            if any(re.search(m, opt, re.IGNORECASE) for m in markers):
                if i < len(labels):
                    correct_answer_index = i
                    # Clean the marker after detection
                    for m in markers:
                        new_options[i] = re.sub(m, '', new_options[i], flags=re.IGNORECASE).strip()
                    # Also clean bold syntax
                    new_options[i] = re.sub(r'[\{\}\*]', '', new_options[i]).strip()

        # Update question dict
        q['options'] = new_options
        
        # 3. CLEAN CORRECT ANSWER
        correct_answer = str(q.get('correct_answer', '')).strip()
        if correct_answer:
            # If answer is like "(B)" or "B.", simplify to "B"
            match = re.search(r'[\(\[]?([A-Da-d1-4])[\)\]\.]', correct_answer)
            if match:
                q['correct_answer'] = match.group(1).upper()
            elif len(correct_answer) > 2:
                # If AI returned the whole text of the option as the answer, match it back
                best_label = None
                for i, opt in enumerate(new_options):
                    if opt.lower() == correct_answer.lower() or correct_answer.lower() in opt.lower():
                        if i < len(labels):
                            best_label = labels[i]
                            break
                if best_label:
                    q['correct_answer'] = best_label
                else:
                    # Keep it as is if no match
                    pass
            else:
                q['correct_answer'] = correct_answer.upper()
        
        # If we found a marker (like \boxtimes) earlier, it takes priority
        if correct_answer_index is not None:
            q['correct_answer'] = labels[correct_answer_index]

        return q

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
            r'Q\.\s*(\d+)',  # Handles "Q.1" and "Q. 1"
            r'Question\s*(\d+)[\.\):\s]',
            r'Q(\d+)[\.\)]',
            r'(?:^|\n)\s*(\d+)\.\s+[A-Z]',
            r'(?:^|\n)\s*(\d+)\s+[A-Z]',
            r'(?:^|\n)\s*\((\d+)\)\s',
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
            
            # Extract options - support (A)/(a) or (1) style
            option_pattern = r'(?:^|\n)\s*\(?([A-Da-d1-4])\)?[\.\)]\s*(.+?)(?=(?:\n\s*\(?[A-Da-d1-4]\)?[\.\)])|(?:\n\s*(?:Answer|Ans|Solution))|$)'
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
