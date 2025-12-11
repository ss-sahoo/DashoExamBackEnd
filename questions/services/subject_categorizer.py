"""
Subject Categorization Service
AI-powered categorization of extracted questions into pattern subjects
This runs AFTER question extraction to categorize questions by subject
"""
import json
import re
import logging
from typing import List, Dict, Optional
from django.conf import settings

logger = logging.getLogger('extraction')


class SubjectCategorizationError(Exception):
    """Raised when subject categorization fails"""
    pass


class SubjectCategorizer:
    """
    AI-powered subject categorization service.
    Takes extracted questions and categorizes them into the pattern's subjects.
    
    Flow:
    1. Receive list of extracted questions (without subjects)
    2. Receive list of available subjects from pattern
    3. Use AI to categorize each question into appropriate subject
    4. Return questions with subject assignments
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """Initialize the subject categorizer"""
        self.api_key = api_key or getattr(settings, 'GEMINI_API_KEY', None)
        self.model = model or getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
        
        if not self.api_key:
            raise SubjectCategorizationError("Gemini API key not configured")
        
        # Initialize Gemini client
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.client = genai.GenerativeModel(self.model)
        except ImportError:
            raise SubjectCategorizationError(
                "google-generativeai library not installed. "
                "Run: pip install google-generativeai"
            )
        except Exception as e:
            raise SubjectCategorizationError(f"Failed to initialize Gemini client: {str(e)}")
    
    def categorize_questions(
        self,
        questions: List[Dict],
        available_subjects: List[str],
        batch_size: int = 20
    ) -> Dict:
        """
        Categorize questions into available subjects
        
        Args:
            questions: List of extracted questions (without subjects)
            available_subjects: List of subjects from the exam pattern
            batch_size: Number of questions to process per API call
            
        Returns:
            {
                'questions': List of questions with subject assignments,
                'subject_counts': Dict mapping subject to question count,
                'uncategorized_count': Number of questions that couldn't be categorized
            }
        """
        if not questions:
            return {
                'questions': [],
                'subject_counts': {},
                'uncategorized_count': 0
            }
        
        if not available_subjects:
            # No subjects defined - mark all as uncategorized
            for q in questions:
                q['suggested_subject'] = 'Uncategorized'
            return {
                'questions': questions,
                'subject_counts': {'Uncategorized': len(questions)},
                'uncategorized_count': len(questions)
            }
        
        logger.info(f"Categorizing {len(questions)} questions into subjects: {available_subjects}")
        
        categorized_questions = []
        subject_counts = {subj: 0 for subj in available_subjects}
        subject_counts['Uncategorized'] = 0
        
        # Process in batches
        for i in range(0, len(questions), batch_size):
            batch = questions[i:i + batch_size]
            
            try:
                batch_results = self._categorize_batch(batch, available_subjects)
                
                for q, result in zip(batch, batch_results):
                    subject = result.get('subject', 'Uncategorized')
                    
                    # Validate subject is in available list
                    if subject not in available_subjects:
                        # Try case-insensitive match
                        matched = False
                        for avail_subj in available_subjects:
                            if avail_subj.lower() == subject.lower():
                                subject = avail_subj
                                matched = True
                                break
                        if not matched:
                            subject = 'Uncategorized'
                    
                    q['suggested_subject'] = subject
                    q['subject_confidence'] = result.get('confidence', 0.5)
                    q['subject_reasoning'] = result.get('reasoning', '')
                    
                    if subject in subject_counts:
                        subject_counts[subject] += 1
                    else:
                        subject_counts['Uncategorized'] += 1
                    
                    categorized_questions.append(q)
                    
            except Exception as e:
                logger.error(f"Batch categorization failed: {e}")
                # Mark batch as uncategorized
                for q in batch:
                    q['suggested_subject'] = 'Uncategorized'
                    q['subject_confidence'] = 0.0
                    q['subject_reasoning'] = f'Categorization failed: {str(e)}'
                    subject_counts['Uncategorized'] += 1
                    categorized_questions.append(q)
        
        logger.info(f"Categorization complete. Distribution: {subject_counts}")
        
        return {
            'questions': categorized_questions,
            'subject_counts': subject_counts,
            'uncategorized_count': subject_counts.get('Uncategorized', 0)
        }
    
    def _categorize_batch(
        self,
        questions: List[Dict],
        available_subjects: List[str]
    ) -> List[Dict]:
        """Categorize a batch of questions using AI"""
        
        prompt = self._build_categorization_prompt(questions, available_subjects)
        
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={
                    'temperature': 0.1,  # Very low for consistency
                    'top_p': 0.95,
                    'max_output_tokens': 4096,
                }
            )
            
            return self._parse_categorization_response(response.text, len(questions))
            
        except Exception as e:
            logger.error(f"AI categorization failed: {e}")
            raise SubjectCategorizationError(f"Failed to categorize questions: {str(e)}")
    
    def _build_categorization_prompt(
        self,
        questions: List[Dict],
        available_subjects: List[str]
    ) -> str:
        """Build prompt for subject categorization"""
        
        subjects_str = ', '.join(available_subjects)
        
        # Build questions list for prompt
        questions_text = ""
        for i, q in enumerate(questions):
            q_text = q.get('question_text', '')[:300]  # Limit text length
            questions_text += f"\nQ{i+1}: {q_text}\n"
        
        prompt = f"""You are an expert at categorizing exam questions by subject.

## TASK
Categorize each question into ONE of these subjects: {subjects_str}

## AVAILABLE SUBJECTS
{subjects_str}

## QUESTIONS TO CATEGORIZE
{questions_text}

## OUTPUT FORMAT
Return a JSON array with one object per question:
```json
[
  {{"question_index": 1, "subject": "Physics", "confidence": 0.95, "reasoning": "Question about kinetic energy"}},
  {{"question_index": 2, "subject": "Chemistry", "confidence": 0.90, "reasoning": "Question about chemical reactions"}}
]
```

## RULES
1. Each question MUST be assigned to exactly ONE subject from: {subjects_str}
2. If unsure, choose the most likely subject based on keywords and concepts
3. confidence should be 0.0 to 1.0
4. reasoning should be brief (under 50 chars)

## YOUR RESPONSE (JSON array):"""
        
        return prompt
    
    def _parse_categorization_response(
        self,
        response: str,
        expected_count: int
    ) -> List[Dict]:
        """Parse AI response for categorization"""
        
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
            
            results = json.loads(json_str)
            
            if not isinstance(results, list):
                raise ValueError("Response is not a list")
            
            # Ensure we have results for all questions
            while len(results) < expected_count:
                results.append({
                    'subject': 'Uncategorized',
                    'confidence': 0.0,
                    'reasoning': 'No categorization returned'
                })
            
            return results[:expected_count]
            
        except Exception as e:
            logger.error(f"Failed to parse categorization response: {e}")
            # Return default uncategorized for all
            return [
                {'subject': 'Uncategorized', 'confidence': 0.0, 'reasoning': 'Parse error'}
                for _ in range(expected_count)
            ]
    
    def categorize_single_question(
        self,
        question: Dict,
        available_subjects: List[str]
    ) -> Dict:
        """
        Categorize a single question (for real-time categorization)
        
        Args:
            question: Single question dict
            available_subjects: List of available subjects
            
        Returns:
            Question dict with subject assignment
        """
        result = self.categorize_questions([question], available_subjects)
        return result['questions'][0] if result['questions'] else question
