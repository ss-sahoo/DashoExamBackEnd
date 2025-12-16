"""
Question Structure Parser Service
Uses Gemini AI to intelligently parse question structure from OCR-extracted text.
Extracts question text, options, correct answer, and solution.
"""
import json
import re
import logging
from typing import Dict, Optional
from django.conf import settings

logger = logging.getLogger('extraction')


class QuestionStructureParseError(Exception):
    """Raised when question structure parsing fails"""
    pass


class QuestionStructureParser:
    """
    Uses Gemini AI to parse question structure from raw OCR-extracted text.
    Intelligently extracts:
    - Question text
    - Options (for MCQ questions)
    - Correct answer
    - Solution/Explanation
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the parser"""
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
        
        if not self.api_key:
            raise QuestionStructureParseError("Gemini API key not configured")
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
        except ImportError:
            raise QuestionStructureParseError("google-generativeai not installed")
        except Exception as e:
            raise QuestionStructureParseError(f"Failed to initialize Gemini: {str(e)}")
    
    def parse_question_structure(self, text: str) -> Dict:
        """
        Parse question structure from OCR-extracted text using Gemini AI.
        
        Args:
            text: Raw text extracted from image via Mathpix OCR
            
        Returns:
            Dictionary with parsed structure:
            {
                "question_text": str,
                "options": List[str] (optional),
                "correct_answer": str (optional),
                "solution": str (optional),
                "question_type": str,
                "confidence": float
            }
        """
        if not text or not text.strip():
            raise QuestionStructureParseError("Empty text provided")
        
        logger.info(f"Parsing question structure from text ({len(text)} chars)")
        
        try:
            # Build prompt for Gemini
            prompt = self._build_parsing_prompt(text)
            
            # Call Gemini API
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,  # Low temperature for consistent parsing
                    'top_p': 0.95,
                    'max_output_tokens': 8192,
                }
            )
            
            response_text = response.text if hasattr(response, 'text') else str(response)
            logger.debug(f"Gemini response received: {response_text[:200]}...")
            
            # Parse the response
            parsed_structure = self._parse_ai_response(response_text)
            
            # Validate and normalize
            parsed_structure = self._validate_structure(parsed_structure, text)
            
            logger.info(
                f"Successfully parsed question structure: "
                f"type={parsed_structure.get('question_type')}, "
                f"options={len(parsed_structure.get('options', []))}, "
                f"has_answer={bool(parsed_structure.get('correct_answer'))}, "
                f"has_solution={bool(parsed_structure.get('solution'))}"
            )
            
            return parsed_structure
            
        except QuestionStructureParseError:
            raise
        except Exception as e:
            logger.error(f"Failed to parse question structure: {e}", exc_info=True)
            raise QuestionStructureParseError(f"Parsing failed: {str(e)}")
    
    def _build_parsing_prompt(self, text: str) -> str:
        """Build prompt for Gemini to parse question structure"""
        return f"""You are an expert at parsing exam questions from OCR-extracted text.

Analyze the following text extracted from an image and extract the question structure intelligently.

**TASK:**
Parse the text and identify:
1. Question text - The main question statement/problem
2. Options - Multiple choice options (if present, typically labeled A, B, C, D or 1, 2, 3, 4)
3. Correct answer - The correct option letter/number or answer value
4. Solution/Explanation - Step-by-step solution or explanation (if present)

**IMPORTANT INSTRUCTIONS:**

1. **Preserve LaTeX formatting**: Keep all mathematical equations in LaTeX format (with $ delimiters)
   - Example: "$x^2 + y^2 = z^2$" or "$$\\int_0^1 x dx$$"

2. **Handle various formats**:
   - Options may be labeled: (A), A), A., a), 1), (1), etc.
   - Answer may be: "Answer: A", "Ans: (B)", "Correct Answer: C", "Answer (1)", etc.
   - Solution may start with: "Solution:", "Explanation:", "Sol:", "Hint:", etc.

3. **Question types**:
   - If options are present, it's likely MCQ (multiple choice question)
   - If no options but answer is a number, it's numerical
   - If answer is True/False, it's true_false type

4. **Extraction rules**:
   - Question text should be the main problem statement (everything before options)
   - Options should be extracted as an array of strings (remove labels like A), B), etc.)
   - Correct answer should be the option letter/number OR the actual answer value
   - Solution should include all explanation text after "Solution:" or similar markers

5. **Edge cases**:
   - If no options found, return empty array for options
   - If no answer found, leave correct_answer empty
   - If no solution found, leave solution empty
   - If text is just question without structure, extract what you can

**INPUT TEXT:**
{text}

**OUTPUT FORMAT:**
Return ONLY a valid JSON object (no markdown, no code blocks, just pure JSON) with this structure:

{{
    "question_text": "The main question statement with LaTeX preserved",
    "options": ["Option 1 text", "Option 2 text", "Option 3 text", "Option 4 text"],
    "correct_answer": "A" or "Option text" or "42" or "True" depending on question type,
    "solution": "Step-by-step solution if present, empty string otherwise",
    "question_type": "single_mcq" or "numerical" or "true_false" or "subjective",
    "confidence": 0.0 to 1.0 (your confidence in the parsing)
}}

**CRITICAL JSON FORMATTING RULES:**
1. ALL backslashes in LaTeX must be escaped as double backslashes in JSON strings
   - LaTeX command like \\lambda must become \\\\lambda in the JSON string value
   - Example: "$x^2$" is fine (no backslashes), but "$\\frac{{a}}{{b}}$" must be "$\\\\frac{{a}}{{b}}$" in JSON
2. All string values must be properly escaped for JSON (quotes, backslashes, etc.)
3. Return ONLY the JSON object, no other text before or after it
4. Ensure all special characters are properly escaped

Example of correct JSON with LaTeX (showing proper escaping):
{{"question_text": "Find $\\\\lambda$ such that $\\\\lambda x = y$", "options": ["Option 1", "Option 2"], "correct_answer": "A", "solution": "", "question_type": "single_mcq", "confidence": 0.9}}"""
    
    def _parse_ai_response(self, response_text: str) -> Dict:
        """Parse Gemini's JSON response"""
        try:
            # Try to extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON object directly
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response_text
            
            # Try parsing JSON - handle escape sequence issues
            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError as json_error:
                # If parsing fails due to invalid escape sequences (common with LaTeX), try to fix them
                if 'Invalid \\escape' in str(json_error) or 'Invalid escape' in str(json_error):
                    logger.warning(f"JSON parsing failed due to escape sequence issue. Attempting to fix...")
                    try:
                        # Fix unescaped backslashes in string values
                        # Strategy: Escape backslashes that aren't part of valid JSON escape sequences
                        # Valid JSON escapes: \\, \", \/, \b, \f, \n, \r, \t, \uXXXX
                        # We'll escape backslashes that appear before letters (likely LaTeX commands)
                        import re as regex_module
                        
                        # More robust fix: escape backslashes before letters/digits that aren't valid escapes
                        # Pattern explanation: (?<!\\) = not preceded by backslash
                        #                    \\ = literal backslash
                        #                    (?![\\"/bfnrtu]) = not followed by valid escape char
                        fixed_json = regex_module.sub(
                            r'(?<!\\)\\(?![\\"/bfnrtu0-9])',
                            r'\\\\',
                            json_str
                        )
                        
                        # Try parsing the fixed JSON
                        parsed = json.loads(fixed_json)
                        logger.info("Successfully parsed JSON after fixing escape sequences")
                    except (json.JSONDecodeError, Exception) as fix_error:
                        logger.error(f"Failed to fix JSON escape sequences: {fix_error}")
                        # Re-raise original error with context
                        raise json_error
                else:
                    # For other JSON errors, just re-raise
                    raise
            
            if not isinstance(parsed, dict):
                raise ValueError("Response is not a dictionary")
            
            return parsed
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from response: {e}")
            logger.debug(f"Response text (first 1000 chars): {response_text[:1000]}")
            raise QuestionStructureParseError(f"Invalid JSON response from AI: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            raise QuestionStructureParseError(f"Parsing error: {str(e)}")
    
    def _validate_structure(self, structure: Dict, original_text: str) -> Dict:
        """Validate and normalize the parsed structure"""
        # Ensure required fields exist
        result = {
            'question_text': structure.get('question_text', '').strip(),
            'options': structure.get('options', []),
            'correct_answer': structure.get('correct_answer', '').strip(),
            'solution': structure.get('solution', '').strip(),
            'question_type': structure.get('question_type', 'single_mcq'),
            'confidence': float(structure.get('confidence', 0.8))
        }
        
        # Validate options is a list
        if not isinstance(result['options'], list):
            result['options'] = []
        
        # Clean options (remove empty strings)
        result['options'] = [opt.strip() for opt in result['options'] if opt and opt.strip()]
        
        # If no question text extracted, use original text as fallback
        if not result['question_text']:
            logger.warning("No question text extracted, using original text")
            result['question_text'] = original_text[:500]  # Limit length
        
        # Normalize question type
        q_type = result['question_type'].lower()
        valid_types = ['single_mcq', 'multiple_mcq', 'numerical', 'true_false', 'subjective', 'fill_blank']
        if q_type not in valid_types:
            # Infer from structure
            if len(result['options']) >= 2:
                result['question_type'] = 'single_mcq'
            elif result['correct_answer'] and result['correct_answer'].replace('.', '').replace('-', '').isdigit():
                result['question_type'] = 'numerical'
            else:
                result['question_type'] = 'single_mcq'  # Default
        
        # Ensure confidence is between 0 and 1
        result['confidence'] = max(0.0, min(1.0, result['confidence']))
        
        return result

