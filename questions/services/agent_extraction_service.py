import json
import logging
import os
import requests
import time
import re
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from PIL import Image

# Setup specialized logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('extraction.agent')

class MathpixOCR:
    def __init__(self, app_id: str, app_key: str):
        self.headers = {"app_id": app_id, "app_key": app_key}
        self.api_url = "https://api.mathpix.com/v3/pdf"
        self.image_api_url = "https://api.mathpix.com/v3/images"

    def process_pdf(self, file_path: str) -> str:
        options = {
            "conversion_formats": {"md": True},
            "math_inline_delimiters": ["$", "$"],
            "math_display_delimiters": ["$$", "$$"],
            "include_images": True
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

    def download_image(self, image_id: str, target_path: str) -> bool:
        """Downloads an image from Mathpix by its ID."""
        try:
            url = f"{self.image_api_url}/{image_id}.png"
            resp = requests.get(url, headers=self.headers)
            if resp.status_code == 200:
                with open(target_path, 'wb') as f:
                    f.write(resp.content)
                return True
            logger.warning(f"Failed to download image {image_id}: {resp.status_code}")
            return False
        except Exception as e:
            logger.error(f"Error downloading image {image_id}: {e}")
            return False

class AgentExtractionService:
    def __init__(self, gemini_key: str, mathpix_id: str = None, mathpix_key: str = None):
        genai.configure(api_key=gemini_key)
        # Using 2.0 Flash with a large output limit
        # Using 2.0 Flash as requested/previously working
        self.model = genai.GenerativeModel("gemini-2.0-flash")
        self.mathpix = MathpixOCR(mathpix_id, mathpix_key) if mathpix_id else None
        self.gemini_key = gemini_key

    def run_full_pipeline(self, pdf_path: str, subjects_to_process: Optional[List[str]] = None, separated_content: Optional[Dict[str, str]] = None) -> List[Dict]:
        """
        The 'Subject-Agnostic' Strategy. 
        If subjects are not provided, it will first detect them automatically.
        If separated_content is provided, it uses that instead of full markdown for each subject.
        """
        full_markdown = ""
        is_image = os.path.splitext(pdf_path)[1].lower() in ['.jpg', '.jpeg', '.png']
        
        # ALWAYS ensure full_markdown is available as fallback/reference if not already doing OCR
        if not separated_content or not subjects_to_process or any(self._normalize_subject(s) not in [self._normalize_subject(k) for k in (separated_content or {}).keys()] for s in (subjects_to_process or [])):
            if not full_markdown:
                logger.info("Pipeline: Ensuring full markdown is available...")
                if self.mathpix:
                    try:
                        # Mathpix process_pdf handles images too if they are passed
                        full_markdown = self.mathpix.process_pdf(pdf_path)
                    except Exception as e:
                        logger.warning(f"Mathpix OCR failed: {e}. Falling back to local parser.")
                        full_markdown = self._fallback_local_parsing(pdf_path)
                else:
                    logger.info("Mathpix not configured. Using local parser.")
                    full_markdown = self._fallback_local_parsing(pdf_path)
        
        # Auto-detect subjects if not provided
        if not subjects_to_process:
            if separated_content:
                subjects_to_process = list(separated_content.keys())
                logger.info(f"Using subjects from pre-separated content: {subjects_to_process}")
            elif full_markdown and len(full_markdown.strip()) > 50:
                subjects_to_process = self.detect_subjects(full_markdown)
                logger.info(f"Auto-detected subjects from OCR: {subjects_to_process}")
            elif is_image:
                # If it's an image and OCR gave nothing, we must at least guess the subject or try to detect from image
                # For now, if subjects_to_process is empty and it's an image, let's try a default or detection via vision
                subjects_to_process = ["General"] # Or we could call a vision-based detection
                logger.info("Image detected but no OCR text. Defaulting to 'General' subject for vision extraction.")

        all_questions = []
        for subj in subjects_to_process:
            logger.info(f">>> EXTRACTING ALL QUESTIONS FOR: {subj}")
            
            # Determine which text to use
            subject_text = ""
            if separated_content:
                # Use fuzzy matching for subject keys
                normalized_subj = self._normalize_subject(subj)
                found_key = None
                for key in separated_content.keys():
                    if normalized_subj == self._normalize_subject(key):
                        found_key = key
                        break
                
                if found_key:
                    content_data = separated_content[found_key]
                    if isinstance(content_data, dict):
                        subject_text = content_data.get('content', '')
                    else:
                        subject_text = str(content_data)
                    logger.info(f"Using separated content for {subj} (match: {found_key}, length: {len(subject_text)})")
                else:
                    logger.warning(f"Subject '{subj}' not found in separated content keys: {list(separated_content.keys())}")
            
            if not subject_text:
                # Fallback to full markdown
                logger.info(f"Using full markdown for {subj} (full context extraction)")
                subject_text = full_markdown
            
            logger.info(f"Subject '{subj}' text length: {len(subject_text or '')}")
            
            # For images, we can proceed even with short text if we have the image path
            image_path = pdf_path if is_image else None
            
            if (not subject_text or len(subject_text.strip()) < 10) and not image_path:
                logger.warning(f"No text content found for subject '{subj}' and not an image.")
                continue

            questions = self.extract_subject_questions(subject_text, subj, image_path=image_path)
            all_questions.extend(questions)
            
            time.sleep(2)  # Rate limiting
            
        return all_questions

    def extract_subject_questions(self, text_content: str, subject: str, image_path: Optional[str] = None) -> List[Dict]:
        """Extracts questions for a specific subject from the provided text or image."""
        
        # If text is too short and no image, return empty
        if len(text_content.strip()) < 50 and not image_path:
            logger.warning(f"Text content too short for {subject} and no image provided, skipping extraction.")
            return []

        logger.info(f"Generating Gemini content for {subject} (Vision: {'Yes' if image_path else 'No'})...")

        prompt = f"""
        SYSTEM: You are a high-precision Exam Extractor for ANY subject.
        TASK: Extract ALL questions belonging to the subject '{subject}' or its equivalent variations.
        
        SOURCE TEXT/CONTEXT:
        {text_content}
        
        STRICT RULES:
        1. Extract every question (MCQs, Numerical, Subjective, etc.) found in the source that belongs to this subject.
        2. Preserve ALL LaTeX formulas ($...$).
        3. For MCQs, 'correct_answer' MUST be the option letter(s) only (e.g., "A", "B", "A,C").
           - DO NOT include the full text of the answer in 'correct_answer'.
        4. Capture 'solution' step-by-step if available.
        5. If the SOURCE TEXT contains image tags like ![image_id](image_id), INCLUDE them EXACTLY in 'question_text'.
        
        Return ONLY a valid JSON array of objects:
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
        
        for attempt in range(3):
            try:
                if image_path:
                    img = Image.open(image_path)
                    response = self.model.generate_content([prompt, img])
                else:
                    response = self.model.generate_content(prompt)
                if not response.text:
                    logger.warning(f"Empty response from Gemini for {subject} (attempt {attempt+1})")
                    continue
                
                logger.info(f"Gemini response received for {subject}. Length: {len(response.text)}")
                # logger.debug(f"Raw Gemini response: {response.text}")
                
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
                                # No else, preserve original if it's long and no specific letter found
                            
                            # 2. If answer is text (e.g. "Both A and C"), try to match with options text
                            # We check if 'ans' is a substring of any option
                            found_opt = None
                            for i, opt in enumerate(opts):
                                opt_clean = re.sub(r'^[A-Ea-e][\)\.]\s*', '', str(opt)).strip()
                                if ans.lower() in opt_clean.lower() or opt_clean.lower() in ans.lower():
                                    found_opt = chr(65 + i)
                                    break
                            
                            if found_opt:
                                q['correct_answer'] = found_opt
                        
                        # Process images for this question
                        if self.mathpix:
                            q['images_data'] = self._process_images(q.get('question_text', ''), q.get('solution', ''))
                            
                        cleaned_questions.append(q)

                    logger.info(f"SUCCESS: Extracted {len(cleaned_questions)} questions for {subject}")
                    return cleaned_questions
                else:
                    logger.warning(f"No questions found for {subject} (attempt {attempt+1}). AI response: {response.text[:200]}...")
                    time.sleep(2)
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error extracting {subject} (attempt {attempt+1}): {error_msg}")
                
                # Exponential backoff for rate limits
                if "429" in error_msg or "Resource exhausted" in error_msg or "quota" in error_msg.lower():
                    wait_time = (attempt + 1) * 5 # 5, 10, 15 seconds
                    logger.info(f"Rate limit hit. Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                else:
                    # For other errors, wait a bit too
                    time.sleep(2)
        
        return []

    def _process_images(self, *texts: str) -> Dict[str, str]:
        """Identifies image tags in text and downloads them."""
        from django.conf import settings
        from django.utils import timezone
        
        found_images = {}
        for text in texts:
            if not text: continue
            # Find ![im_...] or ![im_...](im_...)
            matches = re.findall(r'!\[(im_[a-z0-9]+)\]', text)
            for image_id in matches:
                if image_id not in found_images:
                    # Target path
                    upload_dir = os.path.join(settings.MEDIA_ROOT, 'extraction_images')
                    os.makedirs(upload_dir, exist_ok=True)
                    
                    filename = f"{image_id}_{int(timezone.now().timestamp())}.png"
                    local_path = os.path.join(upload_dir, filename)
                    
                    if self.mathpix.download_image(image_id, local_path):
                        # Store media-relative path
                        found_images[image_id] = os.path.join('extraction_images', filename)
                        logger.info(f"Downloaded image {image_id} to {found_images[image_id]}")
                        
        return found_images

    def detect_subjects(self, markdown_text: str) -> List[str]:
        """Uses AI to identify all subjects present in the exam paper."""
        prompt = f"""
        Analyze this exam paper and list all subjects present (e.g., Physics, Biology, History).
        Return ONLY a JSON list of strings.
        
        TEXT:
        {markdown_text[:10000]}
        """
        for attempt in range(3):
            try:
                response = self.model.generate_content(prompt)
                subjects = self._clean_json_response(response.text)
                return subjects if isinstance(subjects, list) else []
            except Exception as e:
                if "429" in str(e) or "resource exhausted" in str(e).lower():
                    if attempt < 2:
                        time.sleep(5 * (2 ** attempt))
                        continue
                logger.warning(f"Detection attempt {attempt+1} failed: {e}")
                
        return []

    def _fallback_local_parsing(self, file_path: str) -> str:
        """Fallback to local FileParserService for text extraction."""
        try:
            from questions.services.file_parser import FileParserService
            parser = FileParserService()
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext == '.pdf':
                mime_type = 'application/pdf'
            elif ext in ['.jpg', '.jpeg', '.png']:
                mime_type = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png'
            else:
                mime_type = 'text/plain'
                
            return parser.parse_file(file_path, mime_type)
        except Exception as e:
            logger.error(f"Local parsing fallback failed: {e}")
            return ""

    def _normalize_subject(self, subject: str) -> str:
        """Normalize subject name for comparison."""
        if not subject: return ""
        s = subject.strip().lower()
        # Common aliases
        aliases = {
            'math': 'mathematics',
            'maths': 'mathematics',
            'chem': 'chemistry',
            'phy': 'physics',
            'bio': 'biology',
            'comp': 'computer science',
            'cs': 'computer science',
            'eco': 'economics',
            'eng': 'english',
            'hist': 'history',
            'geo': 'geography',
        }
        return aliases.get(s, s)

    def _clean_json_response(self, text: str) -> Any:
        """Extracts and parses JSON from a string that might contain other text."""
        if not text:
            return []
        
        # Helper to clean common JSON issues from AI
        def sanitize_json(s: str) -> str:
            # 1. Remove comments
            s = re.sub(r'//.*?\n', '\n', s)
            # 2. Remove trailing commas in arrays/objects
            s = re.sub(r',\s*([\]\}])', r'\1', s)
            # 3. Fix invalid backslash escapes (LaTeX common issue)
            # Matches backslash NOT preceded by another backslash,
            # and NOT followed by valid escape chars: b, f, n, r, t, u, ", \, /
            s = re.sub(r'(?<!\\)\\(?![bfnrtu"\\/])', r'\\\\', s)
            # 4. Specifically for \u, ensure it's followed by 4 hex digits or escape it
            s = re.sub(r'(?<!\\)\\u(?![0-9a-fA-F]{4})', r'\\\\u', s)
            return s.strip()

        # 1. Try to find JSON block in markdown
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                content = sanitize_json(json_match.group(1))
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error in code block: {e}")
        
        # 2. Try to find the first '[' or '{' and last matching bracket
        try:
            # Look for an array first
            array_match = re.search(r'\[.*\]', text, re.DOTALL)
            if array_match:
                try:
                    return json.loads(sanitize_json(array_match.group(0)))
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parse error in array search: {e}")
            
            # Look for an object
            object_match = re.search(r'\{.*\}', text, re.DOTALL)
            if object_match:
                try:
                    return [json.loads(sanitize_json(object_match.group(0)))]
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parse error in object search: {e}")
        except Exception as e:
            logger.error(f"Error during JSON extraction regex: {e}")
            
        return []
