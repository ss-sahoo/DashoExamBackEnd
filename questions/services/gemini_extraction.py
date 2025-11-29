"""
Gemini AI Extraction Service for intelligent question parsing
"""
import json
import re
import logging
from typing import List, Dict, Optional
from django.conf import settings

logger = logging.getLogger('extraction')


class GeminiExtractionError(Exception):
    """Raised when Gemini API extraction fails"""
    pass


class GeminiExtractionService:
    """AI-powered question extraction using Google Gemini"""
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize Gemini extraction service
        
        Args:
            api_key: Gemini API key (defaults to settings.GEMINI_API_KEY)
            model: Model to use (defaults to settings.GEMINI_MODEL)
        """
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        
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
    
    def extract_questions(
        self, 
        text_content: str, 
        context: dict,
        is_image: bool = False,
        image_path: Optional[str] = None
    ) -> List[Dict]:
        """
        Extract structured questions from text using Gemini AI
        
        Args:
            text_content: Raw text from document or image marker
            context: Additional context (exam pattern, subjects, etc.)
            is_image: Whether the content is from an image
            image_path: Path to image file if is_image is True
            
        Returns:
            List of extracted questions with metadata
            
        Raises:
            GeminiExtractionError: If extraction fails
        """
        try:
            # Build extraction prompt
            prompt = self.build_extraction_prompt(text_content, context, is_image)
            
            # Call Gemini API
            if is_image and image_path:
                response = self._extract_from_image(image_path, prompt)
            else:
                response = self._extract_from_text(text_content, prompt)
            
            # Parse AI response
            questions = self.parse_ai_response(response)
            
            # Post-process questions
            for question in questions:
                question['question_type'] = self.classify_question_type(question)
                question['confidence_score'] = self.calculate_confidence(question)
            
            logger.info(f"Successfully extracted {len(questions)} questions")
            return questions
            
        except Exception as e:
            logger.error(f"Gemini extraction failed: {str(e)}")
            raise GeminiExtractionError(f"Failed to extract questions: {str(e)}")
    
    def build_extraction_prompt(
        self, 
        text_content: str, 
        context: dict,
        is_image: bool = False
    ) -> str:
        """
        Build optimized prompt for Gemini AI
        
        Args:
            text_content: Content to analyze
            context: Exam context
            is_image: Whether analyzing an image
            
        Returns:
            Formatted prompt string
        """
        allowed_types = context.get('allowed_question_types', [])
        type_descriptions = {
            'single_mcq': 'Single Correct MCQ (one correct answer)',
            'multiple_mcq': 'Multiple Correct MCQ (multiple correct answers)',
            'numerical': 'Numerical Questions (numeric answer)',
            'subjective': 'Subjective Questions (descriptive answer)',
            'true_false': 'True/False Questions',
            'fill_blank': 'Fill in the Blanks'
        }
        
        allowed_types_str = ', '.join([type_descriptions.get(t, t) for t in allowed_types]) if allowed_types else 'all types'
        
        image_instruction = ""
        if is_image:
            image_instruction = """
**Special Instructions for Image Analysis:**
- Extract all visible text from the image
- Describe any diagrams, charts, or figures in detail
- Convert mathematical equations to LaTeX format (use $ for inline, $$ for display)
- Preserve the structure and formatting of questions
- If image quality is poor, note it in the confidence score
"""
        
        # Build subject context
        subjects = context.get('subjects', [])
        if subjects:
            subjects_str = ', '.join(subjects)
            subject_instruction = f"- Available Subjects: {subjects_str}\n- For each question, identify which subject it belongs to from the available subjects"
        else:
            subject = context.get('subject', 'General')
            subjects_str = subject
            subject_instruction = f"- Subject: {subject}"
        
        prompt = f"""You are an expert educational content analyzer. Extract all questions from the following content and structure them in JSON format.

**Context:**
- Exam Pattern: {context.get('pattern_name', 'General')}
{subject_instruction}
- Expected Question Types: {allowed_types_str}

{image_instruction}

**Instructions:**
1. Identify each distinct question in the content
2. For each question, extract:
   - Question text (preserve formatting, equations, and special characters)
   - Question type (single_mcq, multiple_mcq, numerical, subjective, true_false, fill_blank)
   - Options (for MCQ questions, extract all options)
   - Correct answer (identify the correct option or answer)
   - Solution/Explanation (if provided)
   - Difficulty level (easy, medium, hard) based on complexity

3. For mathematical equations:
   - Convert to LaTeX format using $ for inline and $$ for display equations
   - Preserve all mathematical symbols and notation
   - Example: "Find the value of $x^2 + 2x + 1 = 0$"

4. For MCQ questions:
   - Extract all options (A, B, C, D, etc.)
   - Identify which option(s) are correct
   - For multiple correct MCQ, list all correct options

5. For numerical questions:
   - Extract the numerical answer
   - If tolerance is mentioned (e.g., ±0.1), extract it
   - Note the units if specified

6. For diagrams and images:
   - Describe the diagram in detail
   - Include relevant labels and annotations
   - Note if the diagram is essential for understanding the question

**Output Format:**
Return ONLY a JSON array where each element represents one question. Do not include any other text.

Example format:
```json
[
  {{
    "question_text": "What is the speed of light in vacuum?",
    "question_type": "single_mcq",
    "subject": "Physics",
    "options": ["$3 \\times 10^8$ m/s", "$3 \\times 10^6$ m/s", "$3 \\times 10^{{10}}$ m/s", "$3 \\times 10^4$ m/s"],
    "correct_answer": "$3 \\times 10^8$ m/s",
    "solution": "The speed of light in vacuum is a fundamental constant approximately equal to $3 \\times 10^8$ m/s.",
    "difficulty": "easy",
    "confidence": 0.95
  }}
]
```

**Note:** The "subject" field should match one of the available subjects: {subjects_str}

**Important:**
- Return ONLY the JSON array, no additional text or markdown
- Ensure all JSON is properly formatted and escaped
- If you're uncertain about any field, set "confidence" lower (0.0-1.0)
- If a question is incomplete or unclear, still include it but set confidence < 0.7
- For questions with diagrams, include "[DIAGRAM]" in the question text with description

**Content to analyze:**

{text_content if not is_image else "[Image content will be analyzed from the uploaded image]"}
"""
        
        return prompt
    
    def _extract_from_text(self, text_content: str, prompt: str) -> str:
        """Extract questions from text content"""
        try:
            # Generate content with Gemini
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': settings.GEMINI_TEMPERATURE,
                    'top_p': settings.GEMINI_TOP_P,
                    'max_output_tokens': settings.GEMINI_MAX_TOKENS,
                }
            )
            
            return response.text
            
        except Exception as e:
            raise GeminiExtractionError(f"Gemini API call failed: {str(e)}")
    
    def _extract_from_image(self, image_path: str, prompt: str) -> str:
        """Extract questions from image using Gemini Vision"""
        try:
            # Upload image to Gemini
            from PIL import Image
            
            image = Image.open(image_path)
            
            # Generate content with image
            response = self.client.generate_content(
                [prompt, image],
                generation_config={
                    'temperature': settings.GEMINI_TEMPERATURE,
                    'top_p': settings.GEMINI_TOP_P,
                    'max_output_tokens': settings.GEMINI_MAX_TOKENS,
                }
            )
            
            return response.text
            
        except Exception as e:
            raise GeminiExtractionError(f"Gemini Vision API call failed: {str(e)}")
    
    def parse_ai_response(self, response: str) -> List[Dict]:
        """
        Parse Gemini response into structured format
        
        Args:
            response: Raw response from Gemini
            
        Returns:
            List of parsed questions
            
        Raises:
            GeminiExtractionError: If parsing fails
        """
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON array directly
                json_match = re.search(r'\[\s*\{.*?\}\s*\]', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            # Try to parse JSON
            try:
                questions = json.loads(json_str)
            except json.JSONDecodeError as e:
                # Try to repair truncated JSON
                logger.warning(f"JSON parse failed, attempting repair: {e}")
                questions = self._repair_truncated_json(json_str)
            
            if not isinstance(questions, list):
                raise GeminiExtractionError("Response is not a JSON array")
            
            # Validate and normalize each question
            normalized_questions = []
            for q in questions:
                normalized = self._normalize_question(q)
                if normalized:
                    normalized_questions.append(normalized)
            
            if not normalized_questions:
                raise GeminiExtractionError("No valid questions could be extracted")
            
            logger.info(f"Successfully parsed {len(normalized_questions)} questions from AI response")
            return normalized_questions
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Response: {response[:500]}...")
            raise GeminiExtractionError("AI response was not valid JSON")
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
            raise GeminiExtractionError(f"Failed to parse AI response: {str(e)}")
    
    def _repair_truncated_json(self, json_str: str) -> List[Dict]:
        """
        Attempt to repair truncated JSON response from AI
        
        Args:
            json_str: Potentially truncated JSON string
            
        Returns:
            List of parsed questions (may be partial)
        """
        # Find all complete question objects using regex
        # Match complete JSON objects within the array
        question_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
        matches = re.findall(question_pattern, json_str)
        
        questions = []
        for match in matches:
            try:
                q = json.loads(match)
                if isinstance(q, dict) and q.get('question_text'):
                    questions.append(q)
            except json.JSONDecodeError:
                # Try to fix common issues
                fixed = self._fix_json_object(match)
                if fixed:
                    questions.append(fixed)
        
        if questions:
            logger.info(f"Repaired JSON: recovered {len(questions)} questions from truncated response")
            return questions
        
        # Last resort: try to close the array and parse
        json_str = json_str.strip()
        if json_str.startswith('['):
            # Find the last complete object
            last_complete = json_str.rfind('},')
            if last_complete > 0:
                json_str = json_str[:last_complete + 1] + ']'
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
            
            # Try closing with just }]
            last_brace = json_str.rfind('}')
            if last_brace > 0:
                json_str = json_str[:last_brace + 1] + ']'
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
        
        raise json.JSONDecodeError("Could not repair truncated JSON", json_str, 0)
    
    def _fix_json_object(self, obj_str: str) -> Optional[Dict]:
        """Try to fix a single JSON object"""
        try:
            # Remove trailing comma if present
            obj_str = obj_str.rstrip(',')
            
            # Try parsing as-is
            return json.loads(obj_str)
        except json.JSONDecodeError:
            try:
                # Try adding missing closing brace
                if obj_str.count('{') > obj_str.count('}'):
                    obj_str += '}'
                return json.loads(obj_str)
            except json.JSONDecodeError:
                return None
    
    def _normalize_question(self, q: dict) -> Optional[Dict]:
        """Normalize and validate a single question"""
        try:
            # Safely get and strip string values
            question_text = q.get('question_text') or q.get('text') or ''
            question_type = q.get('question_type') or q.get('type') or 'single_mcq'
            subject = q.get('subject') or ''
            correct_answer = q.get('correct_answer') or q.get('answer') or ''
            solution = q.get('solution') or ''
            explanation = q.get('explanation') or ''
            difficulty = q.get('difficulty') or 'medium'
            
            normalized = {
                'question_text': str(question_text).strip() if question_text else '',
                'question_type': self._normalize_question_type(str(question_type)),
                'subject': str(subject).strip() if subject else '',
                'options': q.get('options', []) or [],
                'correct_answer': str(correct_answer).strip() if correct_answer else '',
                'solution': str(solution).strip() if solution else '',
                'explanation': str(explanation).strip() if explanation else '',
                'difficulty': str(difficulty).lower() if difficulty else 'medium',
                'confidence_score': float(q.get('confidence', 0.8))
            }
            
            # Validate required fields
            if not normalized['question_text'] or not normalized['correct_answer']:
                logger.warning(f"Skipping question with missing required fields")
                return None
            
            # Ensure difficulty is valid
            if normalized['difficulty'] not in ['easy', 'medium', 'hard']:
                normalized['difficulty'] = 'medium'
            
            # Ensure confidence is in valid range
            normalized['confidence_score'] = max(0.0, min(1.0, normalized['confidence_score']))
            
            return normalized
            
        except Exception as e:
            logger.warning(f"Failed to normalize question: {e}")
            return None
    
    def _normalize_question_type(self, question_type: str) -> str:
        """Normalize question type to match model choices"""
        type_mapping = {
            'single mcq': 'single_mcq',
            'single correct mcq': 'single_mcq',
            'mcq': 'single_mcq',
            'multiple mcq': 'multiple_mcq',
            'multiple correct mcq': 'multiple_mcq',
            'numerical': 'numerical',
            'numeric': 'numerical',
            'subjective': 'subjective',
            'descriptive': 'subjective',
            'true/false': 'true_false',
            'true false': 'true_false',
            'fill in the blanks': 'fill_blank',
            'fill blank': 'fill_blank',
        }
        
        normalized = question_type.lower().strip()
        return type_mapping.get(normalized, 'single_mcq')  # Default to single_mcq
    
    def classify_question_type(self, question_data: dict) -> str:
        """
        Determine question type from extracted data
        
        Args:
            question_data: Extracted question data
            
        Returns:
            Question type string
        """
        # If type is already set, return it
        if question_data.get('question_type'):
            return question_data['question_type']
        
        # Infer from data
        options = question_data.get('options', [])
        correct_answer = question_data.get('correct_answer', '')
        question_text = question_data.get('question_text', '').lower()
        
        # Check for true/false
        if 'true' in question_text and 'false' in question_text:
            return 'true_false'
        
        # Check for fill in the blank
        if '_____' in question_text or '______' in question_text:
            return 'fill_blank'
        
        # Check for MCQ
        if options and len(options) >= 2:
            # Check if multiple answers are correct
            if isinstance(correct_answer, list) and len(correct_answer) > 1:
                return 'multiple_mcq'
            return 'single_mcq'
        
        # Check for numerical
        try:
            float(correct_answer)
            return 'numerical'
        except (ValueError, TypeError):
            pass
        
        # Default to subjective
        return 'subjective'
    
    def calculate_confidence(self, question_data: dict) -> float:
        """
        Calculate confidence score for extracted question
        
        Args:
            question_data: Extracted question data
            
        Returns:
            Confidence score (0.0 to 1.0)
        """
        # Start with AI-provided confidence or default
        confidence = question_data.get('confidence_score', 0.8)
        
        # Adjust based on data completeness
        if not question_data.get('question_text'):
            confidence *= 0.5
        
        if not question_data.get('correct_answer'):
            confidence *= 0.5
        
        # Boost confidence if solution is provided
        if question_data.get('solution'):
            confidence = min(1.0, confidence * 1.1)
        
        # Check MCQ consistency
        question_type = question_data.get('question_type', '')
        if question_type in ['single_mcq', 'multiple_mcq']:
            options = question_data.get('options', [])
            correct_answer = question_data.get('correct_answer', '')
            
            if not options or len(options) < 2:
                confidence *= 0.6
            elif correct_answer not in options:
                confidence *= 0.7
        
        # Ensure confidence is in valid range
        return max(0.0, min(1.0, confidence))
