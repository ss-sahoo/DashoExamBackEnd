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
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
        
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

**YOUR TASK:**
Parse the question and identify if it has multiple parts (a), (b), (c) or sub-parts (i), (ii).

**FOR MULTI-PART QUESTIONS:**
If you detect parts like (a), (b), (c) or (A), (B), OR choice:
- Set is_nested = true
- Put each part's text in structure.nested_parts array
- Each part needs: label, text, and optional sub_parts array

**EXAMPLE:**
Input: "23. (a) State the following: (i) Kohlrausch law (ii) Faraday's law (b) Using E values..."

Correct Output:
{{
  "question_text": "",
  "is_nested": true,
  "question_type": "subjective",
  "structure": {{
    "nested_parts": [
      {{
        "label": "a", 
        "text": "State the following:",
        "sub_parts": [
          {{"label": "i", "text": "Kohlrausch law of independent migration of ions"}},
          {{"label": "ii", "text": "Faraday's first law of electrolysis"}}
        ]
      }},
      {{
        "label": "b", 
        "text": "Using E values of X and Y given below, predict which is better for coating the surface of iron to prevent corrosion and why?"
      }}
    ]
  }},
  "confidence": 0.9
}}

**RULES:**
1. Remove question numbers (23., 30., Q1.) from all text
2. Remove marks (2, 3, [2 marks]) from all text  
3. For parts, don't include the label (a), (b) in the text field

**TASK:**
Parse the question and detect its structure type:

**TYPE 1: Simple Question (MCQ or single answer)**
- Has options A, B, C, D or similar
- Output as regular MCQ with options array

**TYPE 2: Multi-part Question (a), (b), (c)**
- Has parts labeled (a), (b), (c) that are ALL required
- May have sub-parts (i), (ii) within each part
- question_text should be EMPTY unless there's a context paragraph
- Output with is_nested=true and structure.nested_parts array

**TYPE 3: OR/Choice Question (A) OR (B)**
- Has "OR" keyword separating choices
- Student can choose between options
- question_text should be EMPTY
- Output with type="choice_group" for the OR choices

**TYPE 4: Mixed (parts + OR)**
- Combination of required parts AND OR choices
- Example: (a), (b) required, then (c) OR (c) choice

**INPUT TEXT:**
{text}

**OUTPUT FORMAT:**
Return ONLY valid JSON. Choose the appropriate structure:

For TYPE 1 (MCQ):
{{
    "question_text": "Question without number or marks",
    "options": ["option A", "option B", "option C", "option D"],
    "correct_answer": "",
    "solution": "",
    "question_type": "single_mcq",
    "is_nested": false,
    "confidence": 0.9
}}

For TYPE 2 (Multi-part - question_text is EMPTY):
{{
    "question_text": "",
    "options": [],
    "correct_answer": "",
    "solution": "",
    "question_type": "subjective",
    "is_nested": true,
    "structure": {{
        "nested_parts": [
            {{
                "label": "a",
                "text": "Part a question text",
                "sub_parts": [
                    {{ "label": "i", "text": "Sub-part i text" }},
                    {{ "label": "ii", "text": "Sub-part ii text" }}
                ]
            }},
            {{
                "label": "b", 
                "text": "Part b question text",
                "sub_parts": []
            }},
            {{
                "label": "c",
                "text": "Part c question text",
                "sub_parts": []
            }}
        ]
    }},
    "confidence": 0.9
}}

For TYPE 3 (Pure OR choice like image shows (A) OR (B)):
{{
    "question_text": "",
    "options": [],
    "correct_answer": "",
    "solution": "",
    "question_type": "subjective",
    "is_nested": true,
    "structure": {{
        "nested_parts": [
            {{
                "type": "choice_group",
                "label": "OR",
                "options": [
                    {{
                        "label": "A",
                        "text": "First choice main text",
                        "sub_parts": [
                            {{ "label": "a", "text": "Sub-part a of choice A" }},
                            {{ "label": "b", "text": "Sub-part b of choice A" }}
                        ]
                    }},
                    {{
                        "label": "B",
                        "text": "Second choice text (the OR alternative)"
                    }}
                ]
            }}
        ]
    }},
    "confidence": 0.9
}}

For TYPE 4 (Mixed - parts + OR):
{{
    "question_text": "Context passage if any",
    "options": [],
    "correct_answer": "",
    "solution": "",
    "question_type": "subjective",
    "is_nested": true,
    "structure": {{
        "nested_parts": [
            {{
                "label": "a",
                "text": "Required part a text",
                "sub_parts": []
            }},
            {{
                "label": "b",
                "text": "Required part b text", 
                "sub_parts": []
            }},
            {{
                "type": "choice_group",
                "label": "c",
                "options": [
                    {{ "label": "c", "text": "First option for c" }},
                    {{ "label": "c", "text": "Second option for c (after OR)" }}
                ]
            }}
        ]
    }},
    "confidence": 0.9
}}

**REMEMBER:**
1. NEVER include question numbers (17., 30., Q1., etc.)
2. NEVER include marks numbers (2, 1, (1+1=2), etc.) 
3. Put context/passage in question_text (clean, no numbers)
4. Put each part's actual question in its "text" field
5. Detect "OR" keyword to identify choice_group
6. Return ONLY JSON, no markdown code blocks"""
    
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
        
        # IMPORTANT: Preserve is_nested and structure fields for multi-part questions
        if structure.get('is_nested'):
            result['is_nested'] = True
            if structure.get('structure'):
                result['structure'] = structure['structure']
        
        # Validate options is a list
        if not isinstance(result['options'], list):
            result['options'] = []
        
        # Clean options (remove empty strings)
        result['options'] = [opt.strip() for opt in result['options'] if opt and opt.strip()]
        
        # If no question text extracted, use original text as fallback
        if not result['question_text'] and not result.get('is_nested'):
            logger.warning("No question text extracted, using original text")
            result['question_text'] = original_text[:500]  # Limit length
        
        # Normalize question type
        q_type = result['question_type'].lower()
        valid_types = ['single_mcq', 'multiple_mcq', 'numerical', 'true_false', 'subjective', 'fill_blank']
        if q_type not in valid_types:
            # Infer from structure
            if result.get('is_nested'):
                result['question_type'] = 'subjective'
            elif len(result['options']) >= 2:
                result['question_type'] = 'single_mcq'
            elif result['correct_answer'] and result['correct_answer'].replace('.', '').replace('-', '').isdigit():
                result['question_type'] = 'numerical'
            else:
                result['question_type'] = 'single_mcq'  # Default
        
        # Ensure confidence is between 0 and 1
        result['confidence'] = max(0.0, min(1.0, result['confidence']))
        
        return result

