"""
Stage 4: Question Extractor
Per-chunk AI extraction using type-specific prompts.
This stage takes tagged chunks from Stage 3 and extracts questions
using the prompt specialized for the chunk's question type.
"""
import json
import re
import logging
import time
from typing import Dict, List, Optional, Callable
from django.conf import settings

from .prompts import (
    MCQ_EXTRACTION_PROMPT,
    NUMERICAL_EXTRACTION_PROMPT,
    SUBJECTIVE_EXTRACTION_PROMPT,
    TRUE_FALSE_EXTRACTION_PROMPT,
    FILL_BLANK_EXTRACTION_PROMPT,
    GENERIC_EXTRACTION_PROMPT,
)

logger = logging.getLogger('extraction')


class QuestionExtractorError(Exception):
    """Raised when extraction fails"""
    pass


class QuestionExtractor:
    """
    Stage 4 of the extraction pipeline.
    
    Extracts questions from tagged chunks using type-specific prompts.
    Each chunk knows its subject, section type, and expected question range,
    allowing this stage to use the BEST prompt for each chunk type.
    
    Key improvements over old system:
    - MCQ-specific prompts that emphasize option parsing
    - Numerical-specific prompts that emphasize LaTeX + numeric answers
    - Subjective-specific prompts that handle sub-parts
    - Per-chunk retry logic independent of other chunks
    """
    
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 2
    
    def __init__(self):
        self._client = None
        self._model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
        self._temperature = getattr(settings, 'GEMINI_TEMPERATURE', 0.2)
        self._max_tokens = getattr(settings, 'GEMINI_MAX_TOKENS', 65536)
        
        # Track token usage
        self.total_tokens_used = 0
    
    @property
    def client(self):
        """Lazy-initialize Gemini client"""
        if self._client is None:
            api_key = getattr(settings, 'GEMINI_API_KEY', None)
            if not api_key:
                raise QuestionExtractorError("GEMINI_API_KEY not configured")
            try:
                import google.generativeai as genai
                genai.configure(api_key=api_key)
                self._client = genai.GenerativeModel(self._model_name)
            except ImportError:
                raise QuestionExtractorError("google-generativeai not installed")
        return self._client
    
    def extract_all(
        self,
        chunks: list,
        image_path: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        Extract questions from all chunks.
        
        Args:
            chunks: List of DocumentChunk objects from Stage 3
            image_path: Optional image for Vision API
            progress_callback: Optional fn(percent, message) for progress updates
            
        Returns:
            List of extracted question dicts, each with source metadata
        """
        logger.info(f"[Stage 4] Extracting questions from {len(chunks)} chunks...")
        
        all_questions = []
        
        for i, chunk in enumerate(chunks):
            # Progress update
            if progress_callback:
                pct = int((i / len(chunks)) * 60) + 20  # 20-80% range
                progress_callback(
                    pct,
                    f"Extracting {chunk.subject} / {chunk.section_name} "
                    f"(Q{chunk.start_question}-Q{chunk.end_question})"
                )
            
            logger.info(
                f"[Stage 4] Chunk {i+1}/{len(chunks)}: "
                f"{chunk.subject} / {chunk.section_name} "
                f"(Q{chunk.start_question}-{chunk.end_question}, "
                f"type={chunk.question_type}, expect={chunk.expected_count}q)"
            )
            
            # Extract with retry
            questions = self._extract_chunk_with_retry(
                chunk, image_path=image_path
            )
            
            # Tag each question with source metadata
            for q in questions:
                q['_source'] = {
                    'subject': chunk.subject,
                    'section_name': chunk.section_name,
                    'question_type': chunk.question_type,
                    'chunk_index': chunk.chunk_index,
                    'marks_per_question': chunk.marks_per_question,
                    'negative_marking': chunk.negative_marking,
                }
            
            all_questions.extend(questions)
            
            logger.info(
                f"[Stage 4] Chunk {i+1}: extracted {len(questions)} questions "
                f"(expected {chunk.expected_count})"
            )
        
        logger.info(f"[Stage 4] Total extracted: {len(all_questions)} questions")
        
        return all_questions
    
    def _extract_chunk_with_retry(
        self,
        chunk,
        image_path: Optional[str] = None
    ) -> List[Dict]:
        """Extract questions from a single chunk with retry logic"""
        
        last_error = None
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # Build type-specific prompt
                prompt = self._build_prompt(chunk, aggressive=(attempt > 1))
                
                # Call Gemini
                if image_path:
                    response_text = self._call_gemini_vision(prompt, image_path)
                else:
                    response_text = self._call_gemini_text(prompt)
                
                # Parse response
                questions = self._parse_response(response_text)
                
                # Post-process
                questions = self._post_process(questions, chunk)
                
                # Check if we got enough questions
                extracted = len(questions)
                expected = chunk.expected_count
                
                # Accept if we got at least 70% of expected
                if extracted >= expected * 0.7 or attempt == self.MAX_RETRIES:
                    if extracted < expected * 0.7:
                        logger.warning(
                            f"[Stage 4] Chunk under-extracted after {attempt} attempts: "
                            f"{extracted}/{expected} questions"
                        )
                    return questions
                
                logger.info(
                    f"[Stage 4] Retry {attempt}: got {extracted}/{expected}, "
                    f"retrying with aggressive prompt..."
                )
                
                time.sleep(self.RETRY_DELAY_SECONDS)
                
            except Exception as e:
                last_error = e
                logger.warning(f"[Stage 4] Attempt {attempt} failed: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY_SECONDS * attempt)
        
        # All retries failed — try regex fallback
        logger.warning(f"[Stage 4] All AI attempts failed. Trying regex fallback.")
        fallback = self._regex_fallback(chunk)
        if fallback:
            return fallback
        
        # If even fallback fails, return empty with warning
        logger.error(f"[Stage 4] Extraction completely failed for chunk: {last_error}")
        return []
    
    def _build_prompt(self, chunk, aggressive: bool = False) -> str:
        """Build type-specific prompt for the chunk"""
        
        # Type descriptions for the prompt
        type_descriptions = {
            'single_mcq': 'Single correct MCQ — exactly ONE letter answer (A/B/C/D)',
            'multiple_mcq': 'Multiple correct MCQ — one or more correct answers',
            'numerical': 'Numerical/Integer — answer is a numeric value',
            'subjective': 'Subjective/Essay — requires written explanation',
            'true_false': 'True/False — binary answer',
            'fill_blank': 'Fill in the blank — one or more blanks to fill',
        }
        
        q_type = chunk.question_type
        type_desc = type_descriptions.get(q_type, f'{q_type} question type')
        
        # Select prompt template based on question type
        if q_type in ('single_mcq', 'multiple_mcq'):
            template = MCQ_EXTRACTION_PROMPT
        elif q_type == 'numerical':
            template = NUMERICAL_EXTRACTION_PROMPT
        elif q_type == 'subjective':
            template = SUBJECTIVE_EXTRACTION_PROMPT
        elif q_type == 'true_false':
            template = TRUE_FALSE_EXTRACTION_PROMPT
        elif q_type == 'fill_blank':
            template = FILL_BLANK_EXTRACTION_PROMPT
        else:
            template = GENERIC_EXTRACTION_PROMPT
        
        prompt = template.format(
            expected_count=chunk.expected_count,
            section_name=chunk.section_name,
            subject=chunk.subject,
            question_type=q_type,
            type_description=type_desc,
            start_q=chunk.start_question,
            chunk_text=chunk.text,
        )
        
        if aggressive:
            prompt = (
                "CRITICAL: Previous extraction attempt missed questions. "
                "You MUST extract EVERY question this time. Count carefully!\n\n"
                + prompt
            )
        
        return prompt
    
    def _call_gemini_text(self, prompt: str) -> str:
        """Call Gemini API for text extraction"""
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': self._temperature,
                    'top_p': 0.95,
                    'max_output_tokens': self._max_tokens,
                }
            )
            
            # Track truncation
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'finish_reason'):
                    if str(candidate.finish_reason) == 'MAX_TOKENS':
                        logger.warning("Gemini response truncated at MAX_TOKENS")
            
            return response.text
            
        except Exception as e:
            raise QuestionExtractorError(f"Gemini API call failed: {str(e)}")
    
    def _call_gemini_vision(self, prompt: str, image_path: str) -> str:
        """Call Gemini Vision API for image-based extraction"""
        try:
            from PIL import Image
            image = Image.open(image_path)
            
            response = self.client.generate_content(
                [prompt, image],
                generation_config={
                    'temperature': self._temperature,
                    'top_p': 0.95,
                    'max_output_tokens': self._max_tokens,
                }
            )
            return response.text
            
        except Exception as e:
            raise QuestionExtractorError(f"Gemini Vision call failed: {str(e)}")
    
    def _parse_response(self, response: str) -> List[Dict]:
        """Parse JSON questions from Gemini response"""
        # Extract JSON from markdown code fence
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON array
            json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = response
        
        try:
            questions = json.loads(json_str)
        except json.JSONDecodeError:
            questions = self._repair_json(json_str)
        
        if not isinstance(questions, list):
            return []
        
        return questions
    
    def _repair_json(self, json_str: str) -> List[Dict]:
        """Attempt to repair truncated/malformed JSON"""
        questions = []
        
        # Find individual JSON objects with question_text
        obj_pattern = r'\{[^{}]*"question_text"\s*:\s*"[^"]*"[^{}]*\}'
        matches = re.findall(obj_pattern, json_str, re.DOTALL)
        
        for match in matches:
            try:
                obj = json.loads(match)
                if obj.get('question_text'):
                    questions.append(obj)
            except json.JSONDecodeError:
                continue
        
        if not questions:
            # Try more aggressive: find any JSON object
            try:
                # Close unclosed array/object
                fixed = json_str.rstrip()
                if not fixed.endswith(']'):
                    # Try to close incomplete JSON
                    last_brace = fixed.rfind('}')
                    if last_brace > 0:
                        fixed = fixed[:last_brace + 1] + ']'
                        questions = json.loads(fixed)
            except Exception:
                pass
        
        return questions if isinstance(questions, list) else []
    
    def _post_process(self, questions: List[Dict], chunk) -> List[Dict]:
        """Post-process extracted questions with type-specific validation"""
        processed = []
        
        for q in questions:
            # Ensure required fields exist
            q.setdefault('question_number', 0)
            q.setdefault('question_text', '')
            q.setdefault('question_type', chunk.question_type)
            q.setdefault('options', [])
            q.setdefault('correct_answer', '')
            q.setdefault('solution', '')
            q.setdefault('difficulty', 'medium')
            q.setdefault('has_latex', False)
            q.setdefault('structure', {})
            
            # --- Handle Nested / Structured Data ---
            # If AI extracted 'parts' or 'sub_questions', move to structure field
            extracted_parts = q.pop('parts', []) or q.pop('sub_parts', [])
            if extracted_parts:
                q['structure']['parts'] = extracted_parts
                q['structure']['is_nested'] = True
            
            # If AI flagged as nested
            if q.pop('is_nested', False) or q.pop('internal_choice', False):
                q['structure']['is_nested'] = True
                if 'nested_type' not in q['structure']:
                     # Infer nested type if not present
                    q['structure']['nested_type'] = 'parts'  # Default to parts
            
            # Skip empty questions
            if not str(q.get('question_text') or '').strip():
                continue
            
            # Normalize detected type — override if AI returned invalid type
            detected_type = q.get('question_type', '')
            if detected_type not in (
                'single_mcq', 'multiple_mcq', 'numerical',
                'subjective', 'true_false', 'fill_blank'
            ):
                q['question_type'] = chunk.question_type
            
            # ── Type-specific post-processing ──
            q_type = q['question_type']
            
            # --- MCQ (Single Correct) ---
            if q_type == 'single_mcq':
                q = self._post_process_mcq(q, single=True)
            
            # --- MCQ (Multiple Correct) ---
            elif q_type == 'multiple_mcq':
                q = self._post_process_mcq(q, single=False)
            
            # --- Numerical ---
            elif q_type == 'numerical':
                q['options'] = []  # Numerical should never have options
            
            # --- True/False ---
            elif q_type == 'true_false':
                q = self._post_process_true_false(q)
            
            # --- Fill in the Blank ---
            elif q_type == 'fill_blank':
                q = self._post_process_fill_blank(q)
            
            # --- Subjective ---
            elif q_type == 'subjective':
                q['options'] = []  # Subjective should never have options
                # Ensure structure is clean
                if not q.get('structure'):
                    q['structure'] = {}
            
            # Detect LaTeX if not already flagged
            if not q.get('has_latex'):
                q['has_latex'] = bool(re.search(r'[\$\\]', q['question_text']))
            
            processed.append(q)
        
        return processed
    
    def _post_process_mcq(self, q: Dict, single: bool = True) -> Dict:
        """Post-process MCQ questions (both single and multiple correct)"""
        options = q.get('options', [])
        
        # Clean option text — remove letter prefix if present
        if isinstance(options, list) and len(options) >= 2:
            cleaned_options = []
            for opt in options:
                if isinstance(opt, str):
                    opt = re.sub(r'^[A-Ea-e][\.)\:]?\s*', '', str(opt or '').strip())
                    cleaned_options.append(opt)
            q['options'] = cleaned_options
        
        # Normalize correct_answer
        answer = str(q.get('correct_answer', '')).strip()
        
        if single:
            # single_mcq: should be exactly one letter
            if len(answer) == 1:
                answer = answer.upper()
            elif ',' in answer:
                # AI returned multiple answers for single_mcq
                # Upgrade to multiple_mcq
                q['question_type'] = 'multiple_mcq'
                answer = ','.join(sorted(set(
                    c.strip().upper() for c in answer.split(',')
                    if c.strip().upper() in 'ABCDE'
                )))
        else:
            # multiple_mcq: normalize to comma-separated uppercase letters
            # Handle various formats: "AC", "A,C", "A, C", ["A","C"], "(A)(C)"
            if isinstance(q.get('correct_answer'), list):
                # Already a list: ["A", "C"]
                answer = ','.join(sorted(set(
                    str(a).strip().upper() for a in q['correct_answer']
                    if str(a).strip().upper() in 'ABCDE'
                )))
            else:
                # String format: extract all valid letters
                letters = re.findall(r'[A-Ea-e]', answer)
                if letters:
                    answer = ','.join(sorted(set(l.upper() for l in letters)))
        
        q['correct_answer'] = answer
        return q
    
    def _post_process_true_false(self, q: Dict) -> Dict:
        """Post-process True/False questions"""
        # Always set options to ["True", "False"]
        q['options'] = ['True', 'False']
        
        # Normalize the answer
        answer = str(q.get('correct_answer', '')).strip().lower()
        
        # Map various formats to True/False
        true_values = {'true', 't', 'yes', 'correct', '1', 'right'}
        false_values = {'false', 'f', 'no', 'incorrect', '0', 'wrong'}
        
        if answer in true_values:
            q['correct_answer'] = 'True'
        elif answer in false_values:
            q['correct_answer'] = 'False'
        else:
            # Can't determine — leave as-is but flag for review
            q['requires_review'] = True
        
        return q
    
    def _post_process_fill_blank(self, q: Dict) -> Dict:
        """Post-process Fill-in-the-Blank questions"""
        # If options are provided (word bank), keep them
        # Otherwise set to empty
        if not q.get('options'):
            q['options'] = []
        
        # Ensure blank markers are preserved in question_text
        # Normalize various blank markers
        text = q.get('question_text', '')
        # Keep existing blank markers as-is (_____, ........, [blank], etc.)
        
        # Clean up the answer — trim whitespace
        answer = str(q.get('correct_answer', '')).strip()
        q['correct_answer'] = answer
        
        return q
    
    def _regex_fallback(self, chunk) -> List[Dict]:
        """Last-resort regex extraction when AI fails"""
        logger.info("[Stage 4] Attempting regex fallback extraction...")
        
        text = chunk.text
        questions = []
        
        # Pattern: Q1. or 1. or (1) followed by question text
        q_pattern = r'(?:^|\n)\s*(?:Q\.?\s*)?(\d+)[\.\)\:]?\s*(.*?)(?=(?:\n\s*(?:Q\.?\s*)?\d+[\.\)\:])|$)'
        matches = re.findall(q_pattern, text, re.DOTALL | re.MULTILINE)
        
        for q_num, q_text in matches:
            q_text = q_text.strip()
            if not q_text or len(q_text) < 10:
                continue
            
            # Try to find options
            options = []
            option_match = re.findall(
                r'[(\[]?([A-Da-d])[)\]\.]\s*([^\n]+)',
                q_text
            )
            if len(option_match) >= 2:
                options = [opt[1].strip() for opt in option_match]
                # Remove options from question text
                for opt in option_match:
                    q_text = q_text.replace(opt[1], '').strip()
            
            # Try to find answer
            answer = ''
            ans_match = re.search(r'(?:Answer|Ans)[:\s]*([A-Da-d\d]+)', q_text, re.IGNORECASE)
            if ans_match:
                answer = ans_match.group(1).upper()
            
            questions.append({
                'question_number': int(q_num),
                'question_text': q_text,
                'question_type': chunk.question_type,
                'options': options,
                'correct_answer': answer,
                'solution': '',
                'difficulty': 'medium',
                'has_latex': bool(re.search(r'[\$\\]', q_text)),
            })
        
        logger.info(f"[Stage 4] Regex fallback extracted {len(questions)} questions")
        return questions
