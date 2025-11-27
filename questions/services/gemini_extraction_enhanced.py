"""
Enhanced Gemini AI Extraction Service with Multi-Subject Detection
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


class EnhancedGeminiExtractionService:
    """
    Enhanced AI-powered question extraction with multi-subject detection
    """
    
    # Subject keyword mappings for intelligent detection
    SUBJECT_KEYWORDS = {
        'physics': ['force', 'velocity', 'acceleration', 'energy', 'momentum', 'mass', 
                   'newton', 'gravity', 'motion', 'wave', 'light', 'electricity', 
                   'magnetism', 'thermodynamics', 'quantum', 'relativity'],
        'chemistry': ['atom', 'molecule', 'reaction', 'element', 'compound', 'acid', 
                     'base', 'ion', 'electron', 'bond', 'oxidation', 'reduction', 
                     'periodic', 'mole', 'catalyst', 'equilibrium'],
        'mathematics': ['equation', 'integral', 'derivative', 'function', 'matrix', 
                       'vector', 'algebra', 'geometry', 'trigonometry', 'calculus', 
                       'probability', 'statistics', 'theorem', 'proof'],
        'biology': ['cell', 'organism', 'gene', 'dna', 'protein', 'evolution', 
                   'ecosystem', 'photosynthesis', 'respiration', 'reproduction', 
                   'anatomy', 'physiology', 'enzyme', 'chromosome'],
        'english': ['grammar', 'comprehension', 'passage', 'vocabulary', 'sentence', 
                   'paragraph', 'essay', 'literature', 'poem', 'prose', 'verb', 'noun'],
        'history': ['war', 'empire', 'civilization', 'revolution', 'dynasty', 'treaty', 
                   'independence', 'colonial', 'ancient', 'medieval', 'modern', 'century'],
        'geography': ['continent', 'ocean', 'climate', 'latitude', 'longitude', 'map', 
                     'terrain', 'population', 'resources', 'region', 'country', 'river']
    }
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize Enhanced Gemini extraction service"""
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        
        if not self.api_key:
            raise GeminiExtractionError("Gemini API key not configured")
        
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
    
    def extract_questions_with_subjects(
        self, 
        text_content: str, 
        context: dict,
        is_image: bool = False,
        image_path: Optional[str] = None
    ) -> Dict:
        """
        Extract questions grouped by subject
        
        Returns:
            {
                'subjects': {
                    'physics': [questions],
                    'mathematics': [questions],
                    'ambiguous': [questions]
                },
                'total_questions': int,
                'subject_distribution': {'physics': 10, 'math': 5}
            }
        """
        try:
            # Build enhanced prompt
            prompt = self.build_multi_subject_prompt(text_content, context, is_image)
            
            # Call Gemini API
            if is_image and image_path:
                response = self._extract_from_image(image_path, prompt)
            else:
                response = self._extract_from_text(text_content, prompt)
            
            # Parse response with subject grouping
            result = self.parse_multi_subject_response(response, context)
            
            # Post-process questions
            for subject, questions in result['subjects'].items():
                for question in questions:
                    question['question_type'] = self.classify_question_type(question)
                    question['confidence_score'] = self.calculate_confidence(question)
                    question['detected_subject'] = subject
            
            logger.info(f"Extracted {result['total_questions']} questions across {len(result['subjects'])} subjects")
            return result
            
        except Exception as e:
            logger.error(f"Enhanced Gemini extraction failed: {str(e)}")
            raise GeminiExtractionError(f"Failed to extract questions: {str(e)}")
    
    def build_multi_subject_prompt(
        self, 
        text_content: str, 
        context: dict,
        is_image: bool = False
    ) -> str:
        """Build prompt with multi-subject detection instructions"""
        
        subjects = context.get('subjects', [])
        subjects_str = ', '.join(subjects) if subjects else 'General'
        
        # Build keyword hints
        keyword_hints = []
        for subject in subjects:
            subject_lower = subject.lower()
            keywords = self.SUBJECT_KEYWORDS.get(subject_lower, [])
            if keywords:
                keyword_hints.append(f"  - **{subject.title()}**: {', '.join(keywords[:12])}")
        
        keyword_section = "\n".join(keyword_hints) if keyword_hints else ""
        
        image_instruction = ""
        if is_image:
            image_instruction = """
**Special Instructions for Image Analysis:**
- Extract all visible text from the image
- Describe any diagrams, charts, or figures in detail
- Convert mathematical equations to LaTeX format
- Preserve the structure and formatting of questions
"""
        
        prompt = f"""You are an AI system that extracts, identifies, classifies, and maps exam questions from raw uploaded files.

The uploaded text may contain questions from multiple subjects mixed in any order. Your job is to separate, classify, and map everything correctly.

**AVAILABLE SUBJECTS:** {subjects_str}

**SUBJECT DETECTION RULES:**
1. Identify which subject each question belongs to using:
   - Explicit headings (e.g., "Physics Section", "Mathematics Questions")
   - Keywords and terminology specific to each subject
   - Context clues (formulas, diagrams, concepts mentioned)
   - Formula types and notation patterns

2. Subject Keywords Reference:
{keyword_section}

3. If subject is unclear or ambiguous:
   - Mark as "ambiguous" for manual review
   - Provide reasoning for why it's ambiguous
   - Never assume a subject without strong evidence

**QUESTION EXTRACTION RULES:**
1. Split questions accurately from the raw text
2. Extract for each question:
   - Question text (preserve formatting)
   - Question type (single_mcq, multiple_mcq, numerical, subjective, true_false, fill_blank)
   - Options (if MCQ)
   - Correct answer/key
   - Solution (if provided)
   - Subject (from available subjects or "ambiguous")
   - Detection reasoning (why you classified it to this subject)

3. Keep original order within each subject group

{image_instruction}

**OUTPUT FORMAT:**
Return ONLY a JSON object with this structure:

```json
{{
  "subjects": {{
    "physics": [
      {{
        "question_text": "What is Newton's second law?",
        "question_type": "single_mcq",
        "options": ["F=ma", "E=mc²", "F=G(m1m2)/r²", "P=mv"],
        "correct_answer": "F=ma",
        "solution": "Newton's second law states...",
        "confidence": 0.95,
        "detection_reasoning": "Contains keywords: Newton, force, mass, acceleration"
      }}
    ],
    "mathematics": [
      {{
        "question_text": "Solve: ∫x² dx",
        "question_type": "subjective",
        "options": [],
        "correct_answer": "x³/3 + C",
        "solution": "Using power rule...",
        "confidence": 0.98,
        "detection_reasoning": "Contains integral symbol and calculus notation"
      }}
    ],
    "ambiguous": [
      {{
        "question_text": "What is the capital of France?",
        "question_type": "single_mcq",
        "options": ["Paris", "London", "Berlin", "Rome"],
        "correct_answer": "Paris",
        "solution": "",
        "confidence": 0.6,
        "detection_reasoning": "General knowledge question, no clear subject match"
      }}
    ]
  }}
}}
```

**IMPORTANT RULES:**
- Return ONLY the JSON object, no additional text
- Group questions by detected subject
- Handle mixed-subject files (Physics → Math → Physics)
- Mark uncertain questions as "ambiguous"
- Provide detection_reasoning for each question
- Keep formatting clean and readable
- Do NOT invent new data structures

**Content to analyze:**

{text_content if not is_image else "[Image content will be analyzed]"}
"""
        
        return prompt
    
    def parse_multi_subject_response(self, response: str, context: dict) -> Dict:
        """Parse response with subject grouping"""
        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\{.*"subjects".*\}', response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response
            
            # Parse JSON
            data = json.loads(json_str)
            
            if 'subjects' not in data:
                raise GeminiExtractionError("Response missing 'subjects' field")
            
            # Normalize questions in each subject
            normalized_subjects = {}
            total_questions = 0
            subject_distribution = {}
            
            for subject, questions in data['subjects'].items():
                normalized_questions = []
                for q in questions:
                    normalized = self._normalize_question(q, subject)
                    if normalized:
                        normalized_questions.append(normalized)
                
                if normalized_questions:
                    normalized_subjects[subject] = normalized_questions
                    subject_distribution[subject] = len(normalized_questions)
                    total_questions += len(normalized_questions)
            
            return {
                'subjects': normalized_subjects,
                'total_questions': total_questions,
                'subject_distribution': subject_distribution
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            raise GeminiExtractionError("AI response was not valid JSON")
        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
            raise GeminiExtractionError(f"Failed to parse AI response: {str(e)}")
    
    def _normalize_question(self, q: dict, subject: str) -> Optional[Dict]:
        """Normalize and validate a single question"""
        try:
            question_text = q.get('question_text') or q.get('text') or ''
            question_type = q.get('question_type') or q.get('type') or 'single_mcq'
            correct_answer = q.get('correct_answer') or q.get('answer') or ''
            solution = q.get('solution') or ''
            detection_reasoning = q.get('detection_reasoning') or ''
            
            normalized = {
                'question_text': str(question_text).strip() if question_text else '',
                'question_type': self._normalize_question_type(str(question_type)),
                'subject': subject,
                'options': q.get('options', []) or [],
                'correct_answer': str(correct_answer).strip() if correct_answer else '',
                'solution': str(solution).strip() if solution else '',
                'detection_reasoning': str(detection_reasoning).strip() if detection_reasoning else '',
                'confidence_score': float(q.get('confidence', 0.8))
            }
            
            # Validate required fields
            if not normalized['question_text'] or not normalized['correct_answer']:
                logger.warning(f"Skipping question with missing required fields")
                return None
            
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
        return type_mapping.get(normalized, 'single_mcq')
    
    def classify_question_type(self, question_data: dict) -> str:
        """Determine question type from extracted data"""
        if question_data.get('question_type'):
            return question_data['question_type']
        
        options = question_data.get('options', [])
        correct_answer = question_data.get('correct_answer', '')
        question_text = question_data.get('question_text', '').lower()
        
        if 'true' in question_text and 'false' in question_text:
            return 'true_false'
        
        if '_____' in question_text or '______' in question_text:
            return 'fill_blank'
        
        if options and len(options) >= 2:
            if isinstance(correct_answer, list) and len(correct_answer) > 1:
                return 'multiple_mcq'
            return 'single_mcq'
        
        try:
            float(correct_answer)
            return 'numerical'
        except (ValueError, TypeError):
            pass
        
        return 'subjective'
    
    def calculate_confidence(self, question_data: dict) -> float:
        """Calculate confidence score for extracted question"""
        confidence = question_data.get('confidence_score', 0.8)
        
        if not question_data.get('question_text'):
            confidence *= 0.5
        
        if not question_data.get('correct_answer'):
            confidence *= 0.5
        
        if question_data.get('solution'):
            confidence = min(1.0, confidence * 1.1)
        
        # Lower confidence for ambiguous subjects
        if question_data.get('subject') == 'ambiguous':
            confidence *= 0.7
        
        question_type = question_data.get('question_type', '')
        if question_type in ['single_mcq', 'multiple_mcq']:
            options = question_data.get('options', [])
            correct_answer = question_data.get('correct_answer', '')
            
            if not options or len(options) < 2:
                confidence *= 0.6
            elif correct_answer not in options:
                confidence *= 0.7
        
        return max(0.0, min(1.0, confidence))
    
    def _extract_from_text(self, text_content: str, prompt: str) -> str:
        """Extract questions from text content"""
        try:
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
            from PIL import Image
            image = Image.open(image_path)
            
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
