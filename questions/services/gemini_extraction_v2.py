"""
Gemini AI Extraction Service V2
Enhanced extraction with complete question detection, accurate type classification,
and LaTeX preservation for files with 100-500+ questions
"""
import json
import re
import logging
import time
from typing import List, Dict, Optional, Tuple
from django.conf import settings

from .pre_analyzer import PreAnalyzer
from .question_type_classifier import QuestionTypeClassifier
from .latex_processor import LaTeXProcessor

logger = logging.getLogger('extraction')


class GeminiExtractionError(Exception):
    """Raised when Gemini API extraction fails"""
    pass


class GeminiExtractionServiceV2:
    """
    Enhanced AI-powered question extraction with:
    - Complete extraction (100% of questions)
    - Accurate type classification for all 6 types
    - LaTeX preservation
    - Large file support (500+ questions)
    - Chunked processing with validation
    """
    
    # Chunk configuration
    DEFAULT_CHUNK_SIZE = 25  # Questions per chunk (increased for better throughput with large documents)
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the enhanced extraction service"""
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
        
        if not self.api_key:
            raise GeminiExtractionError("Gemini API key not configured")
        
        # Initialize Gemini client
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
            self.genai = genai
        except ImportError:
            raise GeminiExtractionError(
                "google-generativeai library not installed. "
                "Run: pip install google-generativeai"
            )
        except Exception as e:
            raise GeminiExtractionError(f"Failed to initialize Gemini client: {str(e)}")
        
        # Initialize helper services
        self.pre_analyzer = PreAnalyzer()
        self.type_classifier = QuestionTypeClassifier()
        self.latex_processor = LaTeXProcessor()
    
    def extract_questions(
        self,
        text_content: str,
        context: dict,
        is_image: bool = False,
        image_path: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        Extract all questions from text with complete coverage
        
        Args:
            text_content: Raw text from document
            context: Extraction context (subjects, pattern, etc.)
            is_image: Whether content is from image
            image_path: Path to image file
            progress_callback: Optional callback for progress updates
            
        Returns:
            {
                'questions': List of extracted questions,
                'metadata': {
                    'total_extracted': int,
                    'expected_count': int,
                    'completeness': float,
                    'type_distribution': dict,
                    'has_latex': bool,
                    'processing_time': float
                }
            }
        """
        start_time = time.time()
        
        try:
            # Step 1: Get expected question count
            # CRITICAL: Use count from context if provided (from pre-analysis)
            # This avoids re-analyzing and getting wrong counts
            expected_count = context.get('expected_question_count', 0)
            
            if expected_count > 0:
                # Use provided count from pre-analysis (most accurate)
                logger.info(f"Step 1: Using pre-analysis question count: {expected_count}")
                # Still analyze for LaTeX detection
                analysis = self.pre_analyzer.analyze_file(text_content)
                has_latex = analysis['has_latex']
            else:
                # Fallback: analyze content to estimate (less accurate)
                logger.info("Step 1: Pre-analyzing content (no count provided)...")
                analysis = self.pre_analyzer.analyze_file(text_content)
                expected_count = analysis['estimated_question_count']
                has_latex = analysis['has_latex']
            
            logger.info(
                f"Pre-analysis: ~{expected_count} questions expected, "
                f"LaTeX: {has_latex}"
            )
            
            if progress_callback:
                progress_callback(10, f"Found ~{expected_count} questions")
            
            # Step 2: Determine chunking strategy
            if is_image:
                # Process image as single request
                chunks = [(text_content, 0, expected_count)]
            else:
                chunks = self._create_smart_chunks(
                    text_content, 
                    expected_count,
                    analysis
                )
            
            logger.info(f"Step 2: Processing {len(chunks)} chunks")
            
            # Step 3: Extract from each chunk
            all_questions = []
            chunk_results = []
            
            for i, (chunk_text, start_q, end_q) in enumerate(chunks):
                if progress_callback:
                    progress = 10 + int((i / len(chunks)) * 60)
                    progress_callback(progress, f"Processing chunk {i+1}/{len(chunks)}")
                
                logger.info(f"Processing chunk {i+1}/{len(chunks)} (Q{start_q}-{end_q})")
                
                # Extract with retries
                chunk_questions = self._extract_chunk_with_retry(
                    chunk_text,
                    context,
                    start_q,
                    end_q,
                    is_image and i == 0,
                    image_path if is_image and i == 0 else None
                )
                
                chunk_results.append({
                    'chunk': i + 1,
                    'expected': end_q - start_q,
                    'extracted': len(chunk_questions)
                })
                
                all_questions.extend(chunk_questions)
            
            if progress_callback:
                progress_callback(75, "Post-processing questions...")
            
            # Step 4: Post-process all questions
            logger.info(f"Step 4: Post-processing {len(all_questions)} questions")
            processed_questions = self._post_process_questions(
                all_questions, 
                context,
                has_latex
            )
            
            # SANITY CHECK: Warn if extracted > expected (possible AI hallucination)
            if expected_count > 0 and len(processed_questions) > expected_count:
                overage = len(processed_questions) - expected_count
                logger.warning(
                    f"SANITY CHECK FAILED: Extracted {len(processed_questions)} questions "
                    f"but expected only {expected_count}. {overage} extra questions may be hallucinated!"
                )
                # If significantly over (more than 10% overage), this is a red flag
                if overage > max(3, expected_count * 0.1):
                    logger.error(
                        f"CRITICAL: Extracted {overage} extra questions ({(overage/expected_count)*100:.1f}% overage). "
                        f"Possible AI hallucination or duplicate detection."
                    )
            
            # Step 5: Validate completeness
            if progress_callback:
                progress_callback(85, "Validating extraction...")
            
            validation = self.pre_analyzer.validate_extraction_completeness(
                expected_count,
                len(processed_questions)
            )
            
            # Step 6: Build result
            processing_time = time.time() - start_time
            
            type_distribution = {}
            for q in processed_questions:
                q_type = q.get('question_type', 'unknown')
                type_distribution[q_type] = type_distribution.get(q_type, 0) + 1
            
            result = {
                'questions': processed_questions,
                'metadata': {
                    'total_extracted': len(processed_questions),
                    'expected_count': expected_count,
                    'completeness': validation['completeness_percentage'],
                    'completeness_status': validation['status'],
                    'type_distribution': type_distribution,
                    'has_latex': has_latex,
                    'latex_count': analysis.get('latex_count', 0),
                    'processing_time': processing_time,
                    'chunks_processed': len(chunks),
                    'chunk_results': chunk_results,
                    'detected_subjects': analysis.get('detected_subjects', []),
                }
            }
            
            if progress_callback:
                progress_callback(100, f"Extracted {len(processed_questions)} questions")
            
            logger.info(
                f"Extraction complete: {len(processed_questions)}/{expected_count} questions "
                f"({validation['completeness_percentage']:.1f}%) in {processing_time:.2f}s"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Extraction failed: {str(e)}", exc_info=True)
            raise GeminiExtractionError(f"Failed to extract questions: {str(e)}")
    
    def _create_smart_chunks(
        self,
        text: str,
        expected_count: int,
        analysis: dict
    ) -> List[Tuple[str, int, int]]:
        """
        Create intelligent chunks based on question boundaries
        
        Returns:
            List of (chunk_text, start_question_num, end_question_num)
        """
        if expected_count <= self.DEFAULT_CHUNK_SIZE:
            return [(text, 1, expected_count + 1)]
        
        chunks = []
        
        # Find ALL question boundaries with multiple patterns
        question_patterns = [
            r'(?:^|\n)\s*Q\.?\s*(\d+)[\.\)\:]?\s',           # Q.1 or Q1. or Q 1:
            r'(?:^|\n)\s*Question\s+(\d+)[\.\)\:]?\s',       # Question 1
            r'(?:^|\n)\s*#{1,4}\s*(\d+)[\.\)]\s',            # ### 1. markdown heading
            r'(?:^|\n)\s*\*\*(\d+)[\.\)]\s',                 # **1. bold numbered
            r'(?:^|\n)\s*(\d+)\.\s+(?=[A-Z])',               # 1. followed by capital
            r'(?:^|\n)\s*(\d+)\)\s+(?=[A-Z])',               # 1) followed by capital
            r'(?:^|\n)\s*\((\d+)\)\s+(?=[A-Z])',             # (1) followed by capital
        ]
        
        # Collect all matches with their positions
        all_matches = []
        for pattern in question_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
                try:
                    q_num = int(match.group(1))
                    all_matches.append({
                        'position': match.start(),
                        'end_position': match.end(),
                        'question_number': q_num,
                        'match_text': match.group(0)[:50]
                    })
                except (ValueError, IndexError):
                    continue
        
        if len(all_matches) < 2:
            # No clear question number boundaries, try splitting by Answer: patterns
            logger.warning("No clear question boundaries found, trying Answer pattern split")
            answer_chunks = self._split_by_answer_pattern(text, expected_count)
            if answer_chunks:
                return answer_chunks
            # Fall back to size-based splitting
            return self._split_by_size(text, expected_count)
        
        # Sort by position and deduplicate (same position = same question)
        all_matches.sort(key=lambda x: x['position'])
        
        # Remove duplicates at same position
        unique_matches = []
        last_pos = -100
        for m in all_matches:
            if m['position'] - last_pos > 20:  # At least 20 chars apart
                unique_matches.append(m)
                last_pos = m['position']
        
        # Re-number questions sequentially (in case they restart per section/subject)
        for i, m in enumerate(unique_matches):
            m['sequential_number'] = i + 1
        
        logger.info(f"Found {len(unique_matches)} unique question boundaries across entire document")
        
        # Log distribution to help debug
        if unique_matches:
            text_len = len(text)
            first_third = sum(1 for m in unique_matches if m['position'] < text_len // 3)
            second_third = sum(1 for m in unique_matches if text_len // 3 <= m['position'] < 2 * text_len // 3)
            last_third = sum(1 for m in unique_matches if m['position'] >= 2 * text_len // 3)
            logger.info(f"Question distribution: first third={first_third}, middle={second_third}, last third={last_third}")
        
        # Group questions into chunks using sequential numbering
        chunk_size = min(
            analysis.get('recommended_chunk_size', self.DEFAULT_CHUNK_SIZE),
            25  # Smaller chunks for better extraction
        )
        
        current_chunk_start_pos = 0
        current_chunk_q_start = 1  # Use sequential numbering
        questions_in_chunk = 0
        
        for i, match_info in enumerate(unique_matches):
            questions_in_chunk += 1
            seq_num = match_info['sequential_number']
            
            # Check if we should start a new chunk
            if questions_in_chunk >= chunk_size:
                # Find end of current question (start of next)
                if i + 1 < len(unique_matches):
                    chunk_end_pos = unique_matches[i + 1]['position']
                else:
                    chunk_end_pos = len(text)
                
                chunk_text = text[current_chunk_start_pos:chunk_end_pos].strip()
                if chunk_text:
                    chunks.append((chunk_text, current_chunk_q_start, seq_num + 1))
                    logger.debug(f"Created chunk: Q{current_chunk_q_start}-{seq_num}, {len(chunk_text)} chars")
                
                current_chunk_start_pos = chunk_end_pos
                current_chunk_q_start = seq_num + 1
                questions_in_chunk = 0
        
        # Add remaining content as final chunk
        remaining = text[current_chunk_start_pos:].strip()
        if remaining and unique_matches:
            last_seq = unique_matches[-1]['sequential_number']
            chunks.append((remaining, current_chunk_q_start, last_seq + 1))
            logger.debug(f"Created final chunk: Q{current_chunk_q_start}-{last_seq}, {len(remaining)} chars")
        
        logger.info(f"Created {len(chunks)} chunks for {expected_count} expected questions")
        return chunks if chunks else [(text, 1, expected_count + 1)]
    
    def _split_by_answer_pattern(
        self,
        text: str,
        expected_count: int
    ) -> List[Tuple[str, int, int]]:
        """
        Split text by Answer: patterns for documents without clear question numbers
        This is useful for documents where questions are separated by Answer: lines
        """
        # Find all Answer: positions
        answer_pattern = r'(?:Answer|Ans)[\s:]+[A-Da-d]'
        answer_positions = [m.start() for m in re.finditer(answer_pattern, text, re.IGNORECASE)]
        
        if len(answer_positions) < 2:
            return []
        
        logger.info(f"Found {len(answer_positions)} Answer patterns for chunking")
        
        chunk_size = self.DEFAULT_CHUNK_SIZE
        chunks = []
        
        # Group answers into chunks
        for i in range(0, len(answer_positions), chunk_size):
            chunk_answers = answer_positions[i:i + chunk_size]
            
            # Find start of this chunk (after previous chunk's last answer + solution)
            if i == 0:
                start_pos = 0
            else:
                # Start after the previous answer's solution
                prev_answer_pos = answer_positions[i - 1]
                # Look for next question start (after solution)
                solution_end = text.find('\n\n', prev_answer_pos + 50)
                if solution_end == -1:
                    solution_end = prev_answer_pos + 200
                start_pos = solution_end
            
            # Find end of this chunk (after last answer's solution)
            last_answer_pos = chunk_answers[-1]
            if i + chunk_size < len(answer_positions):
                # End before next chunk's first question
                next_answer_pos = answer_positions[i + chunk_size]
                # Go back to find the question start
                end_pos = text.rfind('\n\n', last_answer_pos, next_answer_pos)
                if end_pos == -1:
                    end_pos = next_answer_pos
            else:
                end_pos = len(text)
            
            chunk_text = text[start_pos:end_pos].strip()
            if chunk_text:
                start_q = i + 1
                end_q = min(i + chunk_size + 1, expected_count + 1)
                chunks.append((chunk_text, start_q, end_q))
                logger.debug(f"Created answer-based chunk: Q{start_q}-{end_q-1}, {len(chunk_text)} chars")
        
        return chunks
    
    def _split_by_size(
        self,
        text: str,
        expected_count: int
    ) -> List[Tuple[str, int, int]]:
        """Split text by size when no question markers found"""
        chunk_size = self.DEFAULT_CHUNK_SIZE
        total_chunks = max(1, (expected_count + chunk_size - 1) // chunk_size)
        
        # Split by paragraphs
        paragraphs = text.split('\n\n')
        paras_per_chunk = max(1, len(paragraphs) // total_chunks)
        
        chunks = []
        for i in range(0, len(paragraphs), paras_per_chunk):
            chunk_paras = paragraphs[i:i + paras_per_chunk]
            chunk_text = '\n\n'.join(chunk_paras)
            
            start_q = (i // paras_per_chunk) * chunk_size + 1
            end_q = min(start_q + chunk_size, expected_count + 1)
            
            chunks.append((chunk_text, start_q, end_q))
        
        return chunks
    
    def _extract_chunk_with_retry(
        self,
        chunk_text: str,
        context: dict,
        start_q: int,
        end_q: int,
        is_image: bool,
        image_path: Optional[str]
    ) -> List[Dict]:
        """Extract questions from chunk with retry logic"""
        last_error = None
        best_questions = []
        expected_in_chunk = end_q - start_q
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # Use aggressive prompt on retry attempts
                use_aggressive = attempt > 0
                questions = self._extract_chunk(
                    chunk_text, context, start_q, end_q, is_image, image_path,
                    aggressive=use_aggressive
                )
                
                # Keep the best result
                if len(questions) > len(best_questions):
                    best_questions = questions
                
                # Check if we got enough questions
                if len(questions) >= expected_in_chunk * 0.8:  # 80% is good
                    return questions
                elif len(questions) >= expected_in_chunk * 0.5:  # 50% is acceptable
                    logger.info(f"Got {len(questions)}/{expected_in_chunk} questions, trying to get more...")
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    return best_questions
                else:
                    logger.warning(
                        f"Low extraction: got {len(questions)}/{expected_in_chunk} questions, retrying..."
                    )
                    if attempt < self.MAX_RETRIES - 1:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Chunk extraction attempt {attempt + 1} failed: {e}"
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
        
        # Return best result if we have any
        if best_questions:
            return best_questions
        
        # All retries failed - try fallback extraction
        logger.warning(f"Main extraction failed, trying fallback for chunk Q{start_q}-{end_q}")
        fallback_questions = self._fallback_extract(chunk_text, start_q, end_q)
        
        if fallback_questions:
            logger.info(f"Fallback extraction recovered {len(fallback_questions)} questions")
            return fallback_questions
        
        logger.error(f"All extraction attempts failed for chunk: {last_error}")
        return []
    
    def _fallback_extract(
        self,
        chunk_text: str,
        start_q: int,
        end_q: int
    ) -> List[Dict]:
        """
        Fallback extraction using regex patterns when AI extraction fails
        This is a simpler but more reliable extraction method
        """
        questions = []
        
        # Strategy 1: Try numbered question patterns first
        # Matches: Q.1, Q1., Question 1, 1., 1), (1), ### 1., **1.
        q_pattern = r'(?:^|\n)\s*(?:Q\.?\s*(\d+)|Question\s+(\d+)|#{1,4}\s*(\d+)[\.\)]|\*\*(\d+)[\.\)]|(\d+)[\.\)])\s*(.+?)(?=(?:\n\s*(?:Q\.?\s*\d+|Question\s+\d+|#{1,4}\s*\d+|\*\*\d+|\d+[\.\)]))|$)'
        
        matches = list(re.finditer(q_pattern, chunk_text, re.IGNORECASE | re.DOTALL))
        
        if matches:
            for match in matches:
                try:
                    q_num = int(match.group(1) or match.group(2) or match.group(3) or match.group(4) or match.group(5))
                    q_content = match.group(6).strip()
                    
                    if not q_content or len(q_content) < 10:
                        continue
                    
                    question = self._parse_question_block(q_content, q_num)
                    if question:
                        questions.append(question)
                        
                except Exception as e:
                    logger.debug(f"Fallback extraction error for question: {e}")
                    continue
        
        # Strategy 2: If no numbered questions found, split by "Answer:" pattern
        if len(questions) < 5:
            logger.info("Trying alternative fallback: splitting by Answer pattern")
            alt_questions = self._fallback_by_answer_pattern(chunk_text)
            if len(alt_questions) > len(questions):
                questions = alt_questions
        
        return questions
    
    def _fallback_by_answer_pattern(self, text: str) -> List[Dict]:
        """
        Alternative fallback that splits text by Answer: patterns
        Useful for documents without clear question numbers
        """
        questions = []
        
        # Split by "Answer:" to find question blocks
        # Each block should contain: question text, options A) B) C) D), Answer: X, Solution:
        blocks = re.split(r'(?=\n[A-Z][^\n]*\?\n)', text)
        
        # Alternative: split by looking for option patterns followed by Answer
        answer_pattern = r'(?:Answer|Ans)[\s:]+([A-Da-d])'
        answer_positions = [(m.start(), m.group(1)) for m in re.finditer(answer_pattern, text, re.IGNORECASE)]
        
        if not answer_positions:
            return questions
        
        q_num = 1
        for i, (ans_pos, answer_letter) in enumerate(answer_positions):
            try:
                # Find the start of this question (after previous answer/solution or start)
                if i == 0:
                    start_pos = 0
                else:
                    # Look for end of previous solution
                    prev_ans_pos = answer_positions[i-1][0]
                    solution_end = text.find('\n\n', prev_ans_pos + 20)
                    if solution_end == -1 or solution_end > ans_pos:
                        solution_end = prev_ans_pos + 200
                    start_pos = solution_end
                
                # Extract the block
                end_pos = ans_pos + 100  # Include some solution text
                solution_match = re.search(r'Solution[\s:]+(.+?)(?=\n\n|\Z)', text[ans_pos:ans_pos+500], re.IGNORECASE | re.DOTALL)
                if solution_match:
                    end_pos = ans_pos + solution_match.end()
                
                block = text[start_pos:end_pos].strip()
                
                # Extract question text (before options)
                q_text_match = re.search(r'^(.+?)(?=\n\s*[A-Da-d]\))', block, re.DOTALL)
                if not q_text_match:
                    continue
                q_text = q_text_match.group(1).strip()
                
                # Clean up question text
                q_text = re.sub(r'^[\d\.\)\s]+', '', q_text)  # Remove leading numbers
                q_text = q_text.strip()
                
                if len(q_text) < 10:
                    continue
                
                # Extract options
                options = []
                option_pattern = r'([A-Da-d])\)\s*(.+?)(?=\n\s*[A-Da-d]\)|\nAnswer|\nSolution|\Z)'
                option_matches = re.findall(option_pattern, block, re.IGNORECASE | re.DOTALL)
                for letter, opt_text in option_matches:
                    opt_text = opt_text.strip()
                    if opt_text:
                        options.append(opt_text)
                
                # Extract solution
                solution = ''
                if solution_match:
                    solution = solution_match.group(1).strip()
                
                questions.append({
                    'question_number': q_num,
                    'question_text': q_text,
                    'question_type': 'single_mcq',
                    'options': options,
                    'correct_answer': answer_letter.upper(),
                    'solution': solution,
                    'confidence': 0.5,
                    'extraction_method': 'fallback_answer_pattern'
                })
                q_num += 1
                
            except Exception as e:
                logger.debug(f"Answer pattern fallback error: {e}")
                continue
        
        return questions
    
    def _parse_question_block(self, q_content: str, q_num: int) -> Optional[Dict]:
        """Parse a single question block into structured data"""
        try:
            # Extract options if present
            options = []
            option_pattern = r'\n\s*\(?([A-Ea-e])\)?[\.\)]\s*(.+?)(?=\n\s*\(?[A-Ea-e]\)?[\.\)]|\n\s*(?:Answer|Solution|Ans)|$)'
            option_matches = re.findall(option_pattern, q_content, re.IGNORECASE | re.DOTALL)
            
            for letter, opt_text in option_matches:
                options.append(opt_text.strip())
            
            # Extract answer
            answer = ''
            answer_match = re.search(r'(?:Answer|Ans)[\s:]+(.+?)(?:\n|$)', q_content, re.IGNORECASE)
            if answer_match:
                answer = answer_match.group(1).strip()
            
            # Extract solution
            solution = ''
            solution_match = re.search(r'(?:Solution|Explanation)[\s:]+(.+?)(?=\n\s*(?:Q\.?\s*\d+|$))', q_content, re.IGNORECASE | re.DOTALL)
            if solution_match:
                solution = solution_match.group(1).strip()
            
            # Clean question text (remove options, answer, solution)
            q_text = q_content
            for pattern in [r'\n\s*\(?[A-Ea-e]\)?[\.\)].*', r'(?:Answer|Ans)[\s:].*', r'(?:Solution|Explanation)[\s:].*']:
                q_text = re.sub(pattern, '', q_text, flags=re.IGNORECASE | re.DOTALL)
            q_text = q_text.strip()
            
            if not q_text or len(q_text) < 10:
                return None
            
            # Determine question type
            q_type = 'single_mcq'
            if len(options) >= 2:
                if re.search(r'select\s+all|choose\s+all|more\s+than\s+one', q_text, re.IGNORECASE):
                    q_type = 'multiple_mcq'
                elif len(options) == 2 and any(opt.lower() in ['true', 'false', 't', 'f'] for opt in options):
                    q_type = 'true_false'
            elif re.search(r'_{3,}|\[blank\]', q_text):
                q_type = 'fill_blank'
            elif re.search(r'calculate|find\s+the\s+value|compute', q_text, re.IGNORECASE):
                q_type = 'numerical'
            elif re.search(r'explain|describe|discuss|write', q_text, re.IGNORECASE):
                q_type = 'subjective'
            
            return {
                'question_number': q_num,
                'question_text': q_text,
                'question_type': q_type,
                'options': options,
                'correct_answer': answer,
                'solution': solution,
                'confidence': 0.6,
                'extraction_method': 'fallback_regex'
            }
            
        except Exception as e:
            logger.debug(f"Parse question block error: {e}")
            return None
    
    def _extract_chunk(
        self,
        chunk_text: str,
        context: dict,
        start_q: int,
        end_q: int,
        is_image: bool,
        image_path: Optional[str],
        aggressive: bool = False
    ) -> List[Dict]:
        """Extract questions from a single chunk"""
        if aggressive:
            prompt = self._build_aggressive_prompt(chunk_text, context, start_q, end_q)
        else:
            prompt = self._build_extraction_prompt(chunk_text, context, start_q, end_q)
        
        try:
            if is_image and image_path:
                response = self._call_gemini_vision(image_path, prompt)
            else:
                response = self._call_gemini_text(prompt)
            
            questions = self._parse_response(response)
            return questions
            
        except Exception as e:
            logger.error(f"Chunk extraction failed: {e}")
            raise
    
    def _build_extraction_prompt(
        self,
        text: str,
        context: dict,
        start_q: int,
        end_q: int
    ) -> str:
        """
        Build extraction prompt optimized for complete question extraction.
        ENHANCED: Uses document structure (sections, instructions) to guide extraction.
        """
        expected_count = end_q - start_q
        
        # Get document structure from context if available
        document_structure = context.get('document_structure', {})
        sections = document_structure.get('sections', [])
        instructions = context.get('instructions', '')
        marking_scheme = context.get('marking_scheme', {})
        
        # Build section information for the prompt
        section_info = ""
        if sections:
            section_info = "\n## DETECTED DOCUMENT SECTIONS\n"
            section_info += "Use this information to identify the question TYPE for each question:\n"
            for section in sections:
                section_name = section.get('name', 'Unknown')
                section_type = section.get('type_hint', 'mixed')
                question_range = section.get('question_range', 'Unknown')
                marks = section.get('marks_per_question')
                negative = section.get('negative_marking')
                
                section_info += f"\n- **{section_name}** (Questions {question_range}):\n"
                section_info += f"  - Question Type: {section_type}\n"
                if marks:
                    section_info += f"  - Marks per question: {marks}\n"
                if negative:
                    section_info += f"  - Negative marking: {negative}\n"
                section_info += f"  - Format: {section.get('format_description', 'Standard format')}\n"
        
        # Build marking scheme info
        marking_info = ""
        if marking_scheme:
            correct = marking_scheme.get('correct_marks')
            negative = marking_scheme.get('negative_marks')
            if correct or negative:
                marking_info = f"\n## MARKING SCHEME\n"
                if correct:
                    marking_info += f"- Correct answer: +{correct} marks\n"
                if negative:
                    marking_info += f"- Wrong answer: {negative} marks\n"
        
        # Build instructions info
        instructions_info = ""
        if instructions:
            instructions_info = f"\n## DOCUMENT INSTRUCTIONS (from source)\n{instructions[:500]}\n"
        
        prompt = f"""You are a question extraction expert. Your task is to extract EVERY question from this document.

## CRITICAL INSTRUCTION
This document contains approximately {expected_count} questions. You MUST find and extract ALL of them.
DO NOT skip any question. Count your output to verify you have extracted all questions.
{section_info}{marking_info}{instructions_info}
## HOW TO IDENTIFY QUESTIONS
A question block typically consists of:
1. Question text (may end with ":" or "?")
2. Options labeled A), B), C), D) or (A), (B), (C), (D) or a), b), c), d)
3. Answer line: "Answer: X" or "Ans: X" where X is A, B, C, or D
4. Solution line: "Solution: ..." (explanation) - optional

## QUESTION TYPE CLASSIFICATION
Based on the document structure detected above, classify each question:
- **single_mcq**: 4 options (A-D), exactly ONE correct answer
- **multiple_mcq**: 4 options, MORE THAN ONE correct answer (look for "one or more correct")
- **numerical**: Answer is a number/value (no options, needs calculation)
- **true_false**: True/False or T/F options only
- **fill_blank**: Has blank spaces ___ to fill
- **subjective**: Requires explanation/description (no options)
- **match_following**: Has two columns to match
- **assertion_reason**: Assertion and Reason format

## OUTPUT FORMAT
Return a JSON array with all questions found:
```json
[
  {{
    "question_number": 1,
    "question_text": "Full question text here without options",
    "question_type": "single_mcq",
    "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
    "correct_answer": "C",
    "solution": "Solution explanation here",
    "detected_section": "Section A - Single Correct"
  }},
  {{
    "question_number": 2,
    "question_text": "Another question text",
    "question_type": "numerical",
    "options": [],
    "correct_answer": "42",
    "solution": "Solution here",
    "detected_section": "Numerical Type"
  }}
]
```

## EXTRACTION RULES
1. question_number: Sequential starting from 1
2. question_text: Full question text WITHOUT the options
3. question_type: One of the types listed above (use section info to determine)
4. options: Array of option texts (empty array for numerical/subjective)
5. correct_answer: Single letter A/B/C/D, multiple letters "A,C", or actual value
6. solution: Text after "Solution:" or "Explanation:" (can be empty string "")
7. detected_section: Which section this question belongs to (if known)

## IMPORTANT
- Return ONLY the JSON array, no other text
- Ensure valid JSON syntax
- Extract ALL questions you can find
- Use section information to correctly identify question_type

## DOCUMENT TO EXTRACT FROM:

{text}

## YOUR RESPONSE (JSON array with all questions):"""
        
        return prompt
    
    def _build_aggressive_prompt(
        self,
        text: str,
        context: dict,
        start_q: int,
        end_q: int
    ) -> str:
        """
        Build a more aggressive prompt for retry attempts.
        ENHANCED: Uses document structure (sections) to guide extraction.
        """
        expected_count = end_q - start_q
        
        # Get document structure from context if available
        document_structure = context.get('document_structure', {})
        sections = document_structure.get('sections', [])
        
        # Build concise section hints
        section_hints = ""
        if sections:
            section_hints = "\n## QUESTION TYPES IN THIS DOCUMENT:\n"
            for section in sections:
                section_type = section.get('type_hint', 'single_mcq')
                question_range = section.get('question_range', '')
                section_hints += f"- {section.get('name', 'Section')}: {section_type} ({question_range})\n"
        
        prompt = f"""URGENT: Previous extraction missed questions. You MUST extract ALL questions from this document.

## TASK
Extract EVERY question from this document. There are approximately {expected_count} questions.
{section_hints}
## QUESTION PATTERN
Each question follows this pattern:
- Question text (statement or question ending with : or ?)
- A) first option (for MCQ) OR numerical answer OR subjective response
- B) second option  
- C) third option
- D) fourth option
- Answer: [letter or value]
- Solution: [explanation]

## QUESTION TYPES TO DETECT
- single_mcq: 4 options, ONE correct
- multiple_mcq: 4 options, MULTIPLE correct
- numerical: Answer is a number
- true_false: True/False options
- subjective: Requires explanation

## OUTPUT
Return JSON array with all questions:
```json
[{{"question_number":1,"question_text":"...","question_type":"single_mcq","options":["opt1","opt2","opt3","opt4"],"correct_answer":"A","solution":"...","detected_section":"Section A"}}]
```

## RULES
- Extract ALL questions - this is mandatory
- Use question_type field to classify each question
- correct_answer can be letter(s) or actual value
- detected_section: which section this question belongs to

## DOCUMENT:
{text}

## JSON OUTPUT (all questions):"""
        
        return prompt
    def _call_gemini_text(self, prompt: str) -> str:
        """Call Gemini API for text extraction"""
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': getattr(settings, 'GEMINI_TEMPERATURE', 0.2),  # Lower for consistency
                    'top_p': getattr(settings, 'GEMINI_TOP_P', 0.95),
                    'max_output_tokens': getattr(settings, 'GEMINI_MAX_TOKENS', 65536),  # Increased to 64K for large documents (300+ questions)
                }
            )
            
            # Check if response was truncated
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'finish_reason'):
                    if str(candidate.finish_reason) == 'MAX_TOKENS':
                        logger.warning("Response was truncated due to max tokens limit")
            
            return response.text
        except Exception as e:
            raise GeminiExtractionError(f"Gemini API call failed: {str(e)}")
    
    def _call_gemini_vision(self, image_path: str, prompt: str) -> str:
        """Call Gemini Vision API for image extraction"""
        try:
            from PIL import Image
            image = Image.open(image_path)
            
            response = self.client.generate_content(
                [prompt, image],
                generation_config={
                    'temperature': getattr(settings, 'GEMINI_TEMPERATURE', 0.3),
                    'top_p': getattr(settings, 'GEMINI_TOP_P', 0.95),
                    'max_output_tokens': getattr(settings, 'GEMINI_MAX_TOKENS', 65536),  # Increased to 64K for large documents
                }
            )
            return response.text
        except Exception as e:
            raise GeminiExtractionError(f"Gemini Vision API call failed: {str(e)}")
    
    def _parse_response(self, response: str) -> List[Dict]:
        """Parse Gemini response into structured questions"""
        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON array directly
                json_match = re.search(r'\[\s*\{.*\}\s*\]', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            # Parse JSON
            try:
                questions = json.loads(json_str)
            except json.JSONDecodeError:
                # Try to repair truncated JSON
                questions = self._repair_json(json_str)
            
            if not isinstance(questions, list):
                raise GeminiExtractionError("Response is not a JSON array")
            
            return questions
            
        except Exception as e:
            logger.error(f"Failed to parse response: {e}")
            logger.debug(f"Response: {response[:500]}...")
            return []
    
    def _repair_json(self, json_str: str) -> List[Dict]:
        """Attempt to repair truncated or malformed JSON"""
        questions = []
        
        # Strategy 1: Find complete JSON objects with question_text
        obj_pattern = r'\{[^{}]*"question_text"\s*:\s*"[^"]*"[^{}]*\}'
        matches = re.findall(obj_pattern, json_str, re.DOTALL)
        
        for match in matches:
            try:
                obj = json.loads(match)
                if obj.get('question_text'):
                    questions.append(obj)
            except json.JSONDecodeError:
                pass
        
        if questions:
            logger.info(f"Strategy 1: recovered {len(questions)} questions")
            return questions
        
        # Strategy 2: More aggressive pattern matching
        # Find objects that might have nested content
        obj_pattern2 = r'\{\s*"question_number"\s*:\s*\d+[^}]+?"question_text"\s*:\s*"[^"]*"[^}]*\}'
        matches2 = re.findall(obj_pattern2, json_str, re.DOTALL)
        
        for match in matches2:
            try:
                # Try to complete the object
                fixed = match
                # Balance braces
                open_braces = fixed.count('{') - fixed.count('}')
                open_brackets = fixed.count('[') - fixed.count(']')
                fixed += ']' * max(0, open_brackets)
                fixed += '}' * max(0, open_braces)
                
                obj = json.loads(fixed)
                if obj.get('question_text') and obj not in questions:
                    questions.append(obj)
            except json.JSONDecodeError:
                pass
        
        if questions:
            logger.info(f"Strategy 2: recovered {len(questions)} questions")
            return questions
        
        # Strategy 3: Line-by-line extraction for severely malformed JSON
        lines = json_str.split('\n')
        current_obj = {}
        
        for line in lines:
            line = line.strip()
            
            # Extract key-value pairs
            kv_match = re.match(r'"(\w+)"\s*:\s*(.+?)(?:,\s*)?$', line)
            if kv_match:
                key = kv_match.group(1)
                value_str = kv_match.group(2).strip().rstrip(',')
                
                try:
                    value = json.loads(value_str)
                except:
                    value = value_str.strip('"')
                
                current_obj[key] = value
            
            # Check if we have a complete question
            if current_obj.get('question_text'):
                if 'question_number' in current_obj or len(current_obj) >= 3:
                    questions.append(current_obj.copy())
                    current_obj = {}
        
        # Add last object if valid
        if current_obj.get('question_text'):
            questions.append(current_obj)
        
        if questions:
            logger.info(f"Strategy 3: recovered {len(questions)} questions")
        else:
            logger.warning("JSON repair failed - no questions recovered")
        
        return questions
    
    def _post_process_questions(
        self,
        questions: List[Dict],
        context: dict,
        has_latex: bool
    ) -> List[Dict]:
        """Post-process extracted questions - simplified version focused on subject mapping"""
        processed = []
        seen_texts = set()  # For deduplication
        
        for i, q in enumerate(questions):
            # Skip duplicates
            text_key = q.get('question_text', '')[:100].lower()
            if text_key in seen_texts:
                continue
            seen_texts.add(text_key)
            
            # Normalize question
            normalized = self._normalize_question(q, i + 1)
            if not normalized:
                continue
            
            # Simple type detection based on options (skip complex classification for now)
            # Type classification will be done later during import
            options = normalized.get('options', [])
            if len(options) >= 2:
                normalized['question_type'] = 'single_mcq'  # Default MCQ type
            elif not options:
                # Check for fill blank or numerical patterns
                q_text = normalized['question_text'].lower()
                if '___' in q_text or '[blank]' in q_text:
                    normalized['question_type'] = 'fill_blank'
                elif any(kw in q_text for kw in ['calculate', 'find the value', 'compute']):
                    normalized['question_type'] = 'numerical'
                elif any(kw in q_text for kw in ['explain', 'describe', 'discuss']):
                    normalized['question_type'] = 'subjective'
                else:
                    normalized['question_type'] = 'single_mcq'
            
            # Suggest subject mapping
            normalized['suggested_subject'] = self._suggest_subject(
                normalized, 
                context.get('subjects', [])
            )
            
            processed.append(normalized)
        
        return processed
    
    def _normalize_question(self, q: dict, index: int) -> Optional[Dict]:
        """
        Normalize a single question.
        ENHANCED: Preserves detected_section from AI response for section-based tagging.
        """
        try:
            question_text = str(q.get('question_text', '')).strip()
            if not question_text:
                return None
            
            correct_answer = q.get('correct_answer', '')
            if isinstance(correct_answer, list):
                correct_answer = ', '.join(str(a) for a in correct_answer)
            else:
                correct_answer = str(correct_answer).strip() if correct_answer else ''
            
            normalized = {
                'question_number': q.get('question_number', index),
                'question_text': question_text,
                'question_type': self._normalize_type(q.get('question_type', '')),
                'options': q.get('options', []) or [],
                'correct_answer': correct_answer,
                'solution': str(q.get('solution', '')).strip(),
                'explanation': str(q.get('explanation', '')).strip(),
                'subject': str(q.get('subject', '')).strip(),
                'difficulty': self._normalize_difficulty(q.get('difficulty', 'medium')),
                'confidence_score': float(q.get('confidence', 0.8)),
                'has_latex': q.get('has_latex', False),
                # NEW: Preserve detected section from AI response
                'detected_section': str(q.get('detected_section', '')).strip(),
            }
            
            # Validate MCQ options
            if normalized['question_type'] in ['single_mcq', 'multiple_mcq']:
                if not normalized['options'] or len(normalized['options']) < 2:
                    # Try to extract options from question text
                    extracted_options = self._extract_options_from_text(question_text)
                    if extracted_options:
                        normalized['options'] = extracted_options
            
            return normalized
            
        except Exception as e:
            logger.warning(f"Failed to normalize question: {e}")
            return None
    
    def _normalize_type(self, q_type: str) -> str:
        """Normalize question type string"""
        type_mapping = {
            'single mcq': 'single_mcq',
            'single correct mcq': 'single_mcq',
            'single_correct_mcq': 'single_mcq',
            'mcq': 'single_mcq',
            'multiple mcq': 'multiple_mcq',
            'multiple correct mcq': 'multiple_mcq',
            'multiple_correct_mcq': 'multiple_mcq',
            'multi_mcq': 'multiple_mcq',
            'numerical': 'numerical',
            'numeric': 'numerical',
            'integer': 'numerical',
            'subjective': 'subjective',
            'descriptive': 'subjective',
            'essay': 'subjective',
            'true/false': 'true_false',
            'true false': 'true_false',
            'truefalse': 'true_false',
            'tf': 'true_false',
            'fill in the blanks': 'fill_blank',
            'fill blank': 'fill_blank',
            'fill_in_blank': 'fill_blank',
            'fib': 'fill_blank',
            'blanks': 'fill_blank',
        }
        
        normalized = str(q_type).lower().strip()
        return type_mapping.get(normalized, normalized if normalized in type_mapping.values() else 'single_mcq')
    
    def _normalize_difficulty(self, difficulty: str) -> str:
        """Normalize difficulty level"""
        difficulty = str(difficulty).lower().strip()
        if difficulty in ['easy', 'simple', 'basic']:
            return 'easy'
        elif difficulty in ['hard', 'difficult', 'advanced']:
            return 'hard'
        return 'medium'
    
    def _extract_options_from_text(self, text: str) -> List[str]:
        """Extract MCQ options from question text"""
        options = []
        
        # Pattern: A) option or (A) option or A. option
        pattern = r'(?:^|\n)\s*\(?([A-Ea-e])\)?[\.\)]\s*(.+?)(?=(?:\n\s*\(?[A-Ea-e]\)?[\.\)])|$)'
        matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)
        
        for letter, option_text in matches:
            option_text = option_text.strip()
            if option_text:
                options.append(option_text)
        
        return options if len(options) >= 2 else []
    
    def _suggest_subject(self, question: dict, available_subjects: List[str]) -> str:
        """Suggest subject for question"""
        # Use AI-suggested subject if it matches available
        ai_subject = question.get('subject', '').strip()
        
        if ai_subject:
            for subj in available_subjects:
                if subj.lower() == ai_subject.lower():
                    return subj
        
        # Default to first available or empty
        return available_subjects[0] if available_subjects else ''
