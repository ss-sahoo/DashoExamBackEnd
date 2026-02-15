import json
import logging
import os
import requests
import time
from typing import List, Dict, Any, Optional
import google.generativeai as genai

# Setup specialized logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('extraction.agent')

class MathpixOCR:
    def __init__(self, app_id: str, app_key: str):
        self.headers = {"app_id": app_id, "app_key": app_key}
        self.api_url = "https://api.mathpix.com/v3/pdf"

    def process_pdf(self, file_path: str) -> str:
        options = {
            "conversion_formats": {"md": True},
            "math_inline_delimiters": ["$", "$"],
            "math_display_delimiters": ["$$", "$$"]
        }
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'application/pdf')}
            data = {'options_json': json.dumps(options)}
            resp = requests.post(self.api_url, headers=self.headers, files=files, data=data)
        
        if resp.status_code != 200:
            raise Exception(f"Mathpix Error: {resp.text}")
            
        pdf_id = resp.json().get('pdf_id')
        while True:
            status = requests.get(f"{self.api_url}/{pdf_id}", headers=self.headers).json().get('status')
            if status == 'completed': break
            if status == 'error': raise Exception("Mathpix processing failed")
            time.sleep(3)
            
        return requests.get(f"{self.api_url}/{pdf_id}.md", headers=self.headers).text

class AgentExtractionService:
    def __init__(self, gemini_key: str, mathpix_id: str = None, mathpix_key: str = None):
        genai.configure(api_key=gemini_key)
        # Using 2.0 Flash with a large output limit
        self.model = genai.GenerativeModel("gemini-2.0-flash")
        self.mathpix = MathpixOCR(mathpix_id, mathpix_key) if mathpix_id else None

    def run_full_pipeline(self, pdf_path: str, subjects_to_process: Optional[List[str]] = None, separated_content: Optional[Dict[str, str]] = None) -> List[Dict]:
        """
        The 'Subject-Agnostic' Strategy. 
        If subjects are not provided, it will first detect them automatically.
        If separated_content is provided, it uses that instead of full markdown for each subject.
        """
        full_markdown = ""
        
        # If we don't have separated content, we need OCR
        if not separated_content:
            logger.info("Stage 0: Running Mathpix OCR...")
            full_markdown = self.mathpix.process_pdf(pdf_path) if self.mathpix else ""
        
            # Auto-detect subjects if not provided
            if not subjects_to_process:
                subjects_to_process = self.detect_subjects(full_markdown)
                logger.info(f"Auto-detected subjects: {subjects_to_process}")
        elif not subjects_to_process:
            # If we have separated content, subjects are just the keys
            subjects_to_process = list(separated_content.keys())
            logger.info(f"Using subjects from pre-separated content: {subjects_to_process}")
        
        all_questions = []
        for subj in subjects_to_process:
            logger.info(f">>> EXTRACTING ALL QUESTIONS FOR: {subj}")
            
            # Determine which text to use
            if separated_content and subj in separated_content:
                # Use the specific content for this subject
                # Handle both string and dict format (from PreAnalysisJob)
                content_data = separated_content[subj]
                if isinstance(content_data, dict):
                    subject_text = content_data.get('content', '')
                else:
                    subject_text = str(content_data)
                
                logger.info(f"Using separated content for {subj} (length: {len(subject_text)})")
            else:
                # Fallback to full markdown
                logger.info(f"Using full markdown for {subj} (full context extraction)")
                subject_text = full_markdown

            questions = self.extract_subject_questions(subject_text, subj)
            all_questions.extend(questions)
            
            time.sleep(2)  # Rate limiting
            
        return all_questions

    def extract_subject_questions(self, text_content: str, subject: str) -> List[Dict]:
        """Extracts questions for a specific subject from the provided text."""
        
        # If text is too short, return empty
        if len(text_content.strip()) < 50:
            logger.warning(f"Text content too short for {subject}, skipping extraction.")
            return []

        prompt = f"""
        SYSTEM: You are a high-precision Exam Extractor for ANY subject.
        TASK: Extract ALL questions belonging to the subject '{subject}'.
        
        SOURCE TEXT:
        {text_content}
        
        STRICT RULES:
        1. Extract every question (MCQs, Numerical, Subjective, etc.) found in the text.
        2. Preserve ALL LaTeX formulas ($...$).
        3. For MCQs, 'correct_answer' MUST be the option letter(s) only (e.g., "A", "B", "A,C").
           - DO NOT include the full text of the answer in 'correct_answer'.
        4. Capture 'solution' step-by-step.
        
        Return ONLY a valid JSON array of objects with this structure:
        [
            {{
                "question_text": "...",
                "question_type": "single_mcq|multiple_mcq|numerical|subjective|true_false|fill_blank",
                "options": ["A) ...", "B) ..."],
                "correct_answer": "A", 
                "solution": "...",
                "subject": "{subject}"
            }}
        ]
        """
        
        import re
        
        for attempt in range(2):
            try:
                response = self.model.generate_content(prompt)
                questions = self._clean_json_response(response.text)
                if len(questions) > 0:
                    # Enforce cleaning and subject tag
                    cleaned_questions = []
                    for q in questions: 
                        q['subject'] = subject
                        
                        # Normalize keys
                        if 'question' in q and 'question_text' not in q:
                            q['question_text'] = q.pop('question')
                        if 'answer' in q and 'correct_answer' not in q:
                            q['correct_answer'] = q.pop('answer')
                            
                        # Clean MCQ Answers
                        q_type = q.get('question_type', 'single_mcq')
                        ans = str(q.get('correct_answer', '')).strip()
                        opts = q.get('options', [])
                        
                        if q_type in ['single_mcq', 'multiple_mcq'] and ans:
                            # 1. Try to find direct option letter match (A, B, C, D)
                            # Matches: "A", "(A)", "Option A", "Ans: A"
                            letter_match = re.search(r'(?:^|\s|\(|:)([A-E])(?:\)|\.|:|\s|$)', ans, re.IGNORECASE)
                            
                            if letter_match:
                                # Check if the answer was actually the TEXT of the option which happened to have a letter
                                # If the answer is very long, it's probably text.
                                if len(ans) < 10:
                                    q['correct_answer'] = letter_match.group(1).upper()
                                else:
                                    # Fallback: Validation against options text
                                    pass
                            
                            # 2. If answer is text (e.g. "Both A and C"), try to match with options text
                            # or if the model returned "Values of x" and option A is "Values of x"
                            # We check if 'ans' is a substring of any option (ignoring the "A)" part)
                            found_opt = None
                            for i, opt in enumerate(opts):
                                # Clean option text: remove "A) " prefix
                                opt_clean = re.sub(r'^[A-Ea-e][\)\.]\s*', '', str(opt)).strip()
                                # Check partial match
                                if ans.lower() in opt_clean.lower() or opt_clean.lower() in ans.lower():
                                    # If strict equality or very high overlap
                                    found_opt = chr(65 + i) # A, B, C...
                                    break
                            
                            if found_opt:
                                q['correct_answer'] = found_opt
                        
                        cleaned_questions.append(q)

                    logger.info(f"SUCCESS: Extracted {len(cleaned_questions)} questions for {subject}")
                    return cleaned_questions
                else:
                    logger.warning(f"No questions found for {subject}. Retrying...")
                    time.sleep(2)
            except Exception as e:
                logger.error(f"Error extracting {subject}: {e}")
        
        return []

    def detect_subjects(self, markdown_text: str) -> List[str]:
        """Uses AI to identify all subjects present in the exam paper."""
        prompt = f"""
        Analyze this exam paper and list all subjects present (e.g., Physics, Biology, History).
        Return ONLY a JSON list of strings.
        
        TEXT:
        {markdown_text[:10000]}
        """
        try:
            response = self.model.generate_content(prompt)
            subjects = self._clean_json_response(response.text)
            return subjects if isinstance(subjects, list) else []
        except:
            return []

    def _clean_json_response(self, text: str) -> Any:
        clean = text.replace("```json", "").replace("```", "").strip()
        try: return json.loads(clean)
        except:
            try:
                start = clean.find("[")
                end = clean.rfind("]") + 1
                return json.loads(clean[start:end])
            except: return []
