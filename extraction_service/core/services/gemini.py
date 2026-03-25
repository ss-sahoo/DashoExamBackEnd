import google.generativeai as genai
import json
import logging
import re
from typing import List, Dict, Optional
from core.config import settings
from core.state import Question

logger = logging.getLogger("extraction-service")

class GeminiService:
    def __init__(self):
        try:
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.model = genai.GenerativeModel("gemini-2.0-flash")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini: {e}")
            self.model = None

    def extract_chunk(self, chunk_text: str, context: Optional[Dict] = None) -> List[Question]:
        """Extract questions from a text chunk using Gemini"""
        
        prompt = f"""
        Extract all questions from the following text based on this context:
        {json.dumps(context or {})}
        
        Return a JSON array of objects with these fields:
        - question_number (integer)
        - question_text (string, include only the question body)
        - question_type (enum: single_mcq, multiple_mcq, integer, subjective, numerical)
        - options (array of strings, if applicable)
        - correct_answer (string, if present)
        - solution (string, if present)
        
        Text to process:
        {chunk_text}
        
        Respond ONLY with valid JSON.
        """
        
        try:
            response = self.model.generate_content(prompt)
            text = response.text
            
            # Extract JSON block
            json_match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = text
                
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # Naive cleanup
                json_str = json_str.replace("```json", "").replace("```", "")
                data = json.loads(json_str)
                
            questions = []
            for item in data:
                try:
                    q = Question(
                        question_number=item.get("question_number", 0),
                        question_text=item.get("question_text", ""),
                        question_type=item.get("question_type", "single_mcq"),
                        options=item.get("options", []),
                        correct_answer=str(item.get("correct_answer", "")),
                        solution=str(item.get("solution", "")),
                        confidence=0.9
                    )
                    questions.append(q)
                except Exception as e:
                    logger.warning(f"Failed to parse question item: {e}")
                    
            return questions
            
        except Exception as e:
            logger.error(f"Gemini extraction error: {e}")
            return []

gemini_service = GeminiService()
