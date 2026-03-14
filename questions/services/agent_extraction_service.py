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
            "include_images": True,
            "include_table_markdown": True,
            "include_line_data": True,
            "preserve_display_math": True,
            "preserve_inline_math": True,
            "enable_tables_fallback": True,
            "table_output_format": "html"
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

    def run_full_pipeline(self, pdf_path: str, subjects_to_process: Optional[List[str]] = None, separated_content: Optional[Dict[str, str]] = None, exam_mode: Optional[str] = None) -> List[Dict]:
        """
        The 'Subject-Agnostic' Strategy.
        If subjects are not provided, it will first detect them automatically.
        If separated_content is provided, it uses that instead of full markdown for each subject.
        exam_mode: 'online', 'offline_omr', 'offline_subjective' — controls post-processing.
        """
        self._exam_mode = exam_mode
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
        SYSTEM: You are a high-precision Exam Extractor for the subject '{subject}' ONLY.
        TASK: Extract ALL questions that specifically belong to '{subject}' from the provided content.
        
        **CRITICAL SUBJECT FILTERING:**
        - If subject is 'Chemistry': Extract questions about chemical reactions, electrochemistry, galvanic cells, salt bridges, reduction potentials, chemical equations, molecular structures, EMF, electrodes, half-cells, oxidation-reduction, chemical equilibrium
        - If subject is 'Physics': Extract questions about electric charges, forces, magnetic fields, mechanics, optics, waves, but NOT electrochemistry or galvanic cells
        - If subject is 'Mathematics': Extract questions about calculus, algebra, geometry, trigonometry, statistics
        - IGNORE questions that belong to other subjects
        
        **QUESTION NUMBER GUIDANCE:**
        - Chemistry questions include: electrochemistry questions (typically 46-50), galvanic cell questions, salt bridge questions, reduction potential questions
        - Physics questions are typically about forces, charges, mechanics (typically 1-45)
        - IMPORTANT: Questions about galvanic cells, salt bridges, EMF, electrodes, reduction potentials are CHEMISTRY, not physics
        - Use question content and context to determine subject, not just question numbers
        
        SOURCE TEXT/CONTEXT:
        {text_content}
        
        STRICT RULES:
        1. Extract ONLY questions that belong to '{subject}' based on their content and context.
        2. CRITICAL: Include question numbers in the output. Look for patterns like "46.", "47.", "48." at the start of questions.
        3. Preserve ALL LaTeX formulas ($...$) but ensure they are properly escaped in JSON strings.
        4. For MCQs, 'correct_answer' MUST be the option letter(s) only (e.g., "A", "B", "A,C").
           - DO NOT include the full text of the answer in 'correct_answer'.
        5. Capture 'solution' step-by-step if available.
        6. If the SOURCE TEXT contains image tags like ![image_id](image_id), INCLUDE them EXACTLY in 'question_text'.
        7. CRITICAL: Return ONLY valid JSON. All property names must be in double quotes. All string values must be properly escaped.
        8. **SUBPART HANDLING**: If a question has subparts (1., 2., 3., 4., 5.) followed by "How many are correct?", treat it as ONE question.
        
        **SPECIAL INSTRUCTIONS FOR CHEMISTRY:**
        If extracting Chemistry questions, pay special attention to:
        - Questions about galvanic cells, electrochemistry, salt bridges (typically questions 46-50)
        - Questions with chemical formulas, molecular structures, reaction equations
        - Questions about reduction potentials, EMF, electrodes, half-cells
        - Questions about oxidation-reduction reactions, chemical equilibrium
        - Include ALL mathematical formulas, tables, and chemical equations
        - CRITICAL: Questions 46-50 are usually numerical chemistry questions about electrochemistry
        
        **SPECIAL INSTRUCTIONS FOR PHYSICS:**
        If extracting Physics questions, pay special attention to:
        - Questions about electric charges, forces, fields (typically questions 1-45)
        - Questions with physical formulas, diagrams, calculations
        - Questions about mechanics, electricity, magnetism, optics
        - EXCLUDE electrochemistry, galvanic cells, salt bridges (these are chemistry)
        
        Return ONLY a valid JSON array of objects (no markdown, no extra text):
        [
            {{
                "question_number": 46,
                "question_text": "...",
                "question_type": "single_mcq",
                "options": ["A) ...", "B) ..."],
                "correct_answer": "A", 
                "solution": "...",
                "subject": "Chemistry"
            }}
        ]
        
        IMPORTANT: 
        - Ensure all backslashes in LaTeX are properly escaped (use \\\\ instead of \\).
        - Extract question numbers from patterns like "46.", "47.", "48." at the beginning of questions.
        - For "How many" questions with subparts, include ALL subparts in the question_text as ONE question.
        - ONLY extract questions that clearly belong to '{subject}' based on their content.
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
                
                questions = self._clean_json_response(response.text, subject)
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
                        
                        # Extract question number if not present
                        if not q.get('question_number'):
                            text = q.get('question_text', '')
                            patterns = [
                                r'^(\d+)\.?\s',  # "46. " or "46 "
                                r'^\s*(\d+)\.?\s',  # " 46. " or " 46 "
                                r'Question\s*(\d+)',  # "Question 46"
                                r'Q\.?\s*(\d+)',  # "Q. 46" or "Q 46"
                                r'(\d+)\.\s*[A-Z]',  # "46. For" or "46. Consider"
                            ]
                            
                            for pattern in patterns:
                                match = re.search(pattern, text.strip())
                                if match:
                                    q['question_number'] = int(match.group(1))
                                    break
                            
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

                        # Fix LaTeX double backslashes in math delimiters
                        q = self._fix_latex_in_question(q)
                        
                        cleaned_questions.append(q)

                    # Check for missing questions in expected ranges
                    if subject.lower() == 'mathematics':
                        expected_range = set(range(51, 76))  # Q51-Q75
                        extracted_nums = {q.get('question_number') for q in cleaned_questions if q.get('question_number')}
                        missing_nums = expected_range - extracted_nums
                        
                        if missing_nums and len(missing_nums) <= 10:  # Only try if reasonable number missing
                            logger.info(f"Mathematics missing questions {sorted(missing_nums)}, attempting targeted extraction...")
                            missing_questions = self._extract_specific_questions(text_content, subject, sorted(missing_nums))
                            if missing_questions:
                                cleaned_questions.extend(missing_questions)
                                logger.info(f"Added {len(missing_questions)} missing Mathematics questions")
                    
                    elif subject.lower() == 'physics':
                        expected_range = set(range(1, 26))  # Q1-Q25
                        extracted_nums = {q.get('question_number') for q in cleaned_questions if q.get('question_number')}
                        missing_nums = expected_range - extracted_nums
                        
                        if missing_nums and len(missing_nums) <= 10:
                            logger.info(f"Physics missing questions {sorted(missing_nums)}, attempting targeted extraction...")
                            missing_questions = self._extract_specific_questions(text_content, subject, sorted(missing_nums))
                            if missing_questions:
                                cleaned_questions.extend(missing_questions)
                                logger.info(f"Added {len(missing_questions)} missing Physics questions")
                    
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
        
        # First, try to detect subjects from section headers using regex
        import re
        
        # Look for subject headers in the text
        subject_patterns = [
            r'##\s*(PHYSICS|CHEMISTRY|MATHEMATICS|BIOLOGY|HISTORY|ENGLISH|COMPUTER\s*SCIENCE)',
            r'#\s*(PHYSICS|CHEMISTRY|MATHEMATICS|BIOLOGY|HISTORY|ENGLISH|COMPUTER\s*SCIENCE)',
            r'^\s*(PHYSICS|CHEMISTRY|MATHEMATICS|BIOLOGY|HISTORY|ENGLISH|COMPUTER\s*SCIENCE)\s*$',
            r'Subject:\s*(Physics|Chemistry|Mathematics|Biology|History|English|Computer\s*Science)',
        ]
        
        detected_subjects = set()
        for pattern in subject_patterns:
            matches = re.findall(pattern, markdown_text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                subject = match.strip().title()
                if 'Computer' in subject:
                    subject = 'Computer Science'
                detected_subjects.add(subject)
        
        if detected_subjects:
            subjects_list = sorted(list(detected_subjects))
            logger.info(f"Detected subjects from headers: {subjects_list}")
            return subjects_list
        
        # Fallback to AI detection with larger text sample
        # Use first 5000, middle 5000, and last 5000 chars to cover the whole document
        text_length = len(markdown_text)
        sample_text = ""
        
        if text_length <= 15000:
            sample_text = markdown_text
        else:
            # Take samples from beginning, middle, and end
            sample_text = (
                markdown_text[:5000] + 
                "\n\n[...MIDDLE SECTION...]\n\n" +
                markdown_text[text_length//2-2500:text_length//2+2500] +
                "\n\n[...END SECTION...]\n\n" +
                markdown_text[-5000:]
            )
        
        prompt = f"""
        Analyze this exam paper and list all subjects present (e.g., Physics, Chemistry, Mathematics, Biology, History).
        Look for subject headers, question content, and topic indicators.
        Return ONLY a JSON list of strings.
        
        COMMON SUBJECTS TO LOOK FOR:
        - Physics (mechanics, electricity, magnetism, optics, waves)
        - Chemistry (organic, inorganic, physical chemistry, electrochemistry)
        - Mathematics (algebra, calculus, geometry, trigonometry, functions)
        - Biology (botany, zoology, genetics, ecology)
        
        TEXT SAMPLE:
        {sample_text}
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


    def _fix_latex_in_question(self, question: Dict) -> Dict:
        """
        Apply all formatting fixes to a question dictionary.

        Fixes applied:
        1. Fix double backslashes in LaTeX commands inside math delimiters
           (e.g. $ \\\\mu $ → $ \\mu $)
        2. Convert Markdown images to HTML <img> tags (only for online mode)
        3. Replace newlines outside math with <br> tags
           (\\n\\n → ' <br> <br> ', \\n → ' <br> ')
        4. Replace stray \\\\ outside math with <br>
        """
        if not question:
            return question

        exam_mode = getattr(self, '_exam_mode', None)

        # ---------- helpers ----------

        math_pattern = re.compile(
            r'(\$\$.+?\$\$)'      # $$...$$
            r'|(\\\[.+?\\\])'     # \[...\]
            r'|(\$[^$]+?\$)',     # $...$
            re.DOTALL
        )

        img_pattern = re.compile(r'!\[([^\]]*)\]\(([^)\n]+)\)')

        def fix_latex_commands(text: str) -> str:
            """Reduce \\\\cmd to \\cmd inside math regions"""
            return re.sub(r'\\\\(?=\S)', r'\\', text)

        def convert_images(text: str) -> str:
            """Markdown image → HTML <img>"""
            return img_pattern.sub(r'<img src=\2 alt=\1>', text)

        def process_non_math(text: str) -> str:
            """Replace newlines and stray \\\\ with <br> outside math"""
            # Replace newlines first (longer pattern first)
            text = text.replace('\n\n', ' <br> <br> ')
            text = text.replace('\n', ' <br> ')
            # Replace stray \\ (not part of a LaTeX command) with <br>
            # \\  followed by space/end → <br>, but \alpha etc. are preserved
            text = re.sub(r'\\\\(?![A-Za-z])', ' <br> ', text)
            return text

        def process_text(text: str) -> str:
            """Main processing pipeline"""
            if not text:
                return text

            # Step 1: Convert markdown images to HTML (before newline processing,
            # so \\n around images also gets converted to <br>)
            if exam_mode == 'online':
                text = convert_images(text)

            # Step 2: Split into math / non-math regions
            parts = []
            last = 0

            for m in math_pattern.finditer(text):
                # Non-math segment: replace newlines and stray \\ with <br>
                non_math = text[last:m.start()]
                parts.append(process_non_math(non_math))

                # Math segment: fix double backslashes in commands
                math_region = m.group(0)
                math_region = fix_latex_commands(math_region)
                parts.append(math_region)

                last = m.end()

            # Trailing non-math segment
            trailing = text[last:]
            parts.append(process_non_math(trailing))

            return ''.join(parts)

        # ---------- apply to question fields ----------

        for key in ('question_text', 'solution'):
            if key in question and isinstance(question[key], str):
                question[key] = process_text(question[key])

        if 'options' in question and isinstance(question['options'], list):
            question['options'] = [
                process_text(opt) if isinstance(opt, str) else opt
                for opt in question['options']
            ]

        return question

    def _clean_json_response(self, text: str, subject: str = "Unknown") -> Any:
        """Extracts and parses JSON from a string that might contain other text."""
        if not text:
            return []
        
        # Helper to clean common JSON issues from AI
        def sanitize_json(s: str) -> str:
            # 1. Remove comments
            s = re.sub(r'//.*?\n', '\n', s)
            # 2. Remove trailing commas in arrays/objects
            s = re.sub(r',\s*([\]\}])', r'\1', s)
            # 3. Fix control characters (ASCII 0-31 except \t, \n, \r)
            # These often appear in LaTeX formulas and break JSON parsing
            s = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', s)
            
            # 4. More aggressive LaTeX fixing - handle common LaTeX commands
            # Replace problematic LaTeX sequences with escaped versions
            latex_replacements = {
                r'\\mathrm': r'\\\\mathrm',
                r'\\left': r'\\\\left', 
                r'\\right': r'\\\\right',
                r'\\circ': r'\\\\circ',
                r'\\quad': r'\\\\quad',
                r'\\rightarrow': r'\\\\rightarrow',
                r'\\leftarrow': r'\\\\leftarrow',
                r'\\operatorname': r'\\\\operatorname',
                r'\\begin': r'\\\\begin',
                r'\\end': r'\\\\end',
                r'\\aligned': r'\\\\aligned',
                r'\\xrightarrow': r'\\\\xrightarrow',
                r'\\rightleftharpoons': r'\\\\rightleftharpoons',
                r'\\times': r'\\\\times',
                r'\\frac': r'\\\\frac',
                r'\\ln': r'\\\\ln',
            }
            
            for pattern, replacement in latex_replacements.items():
                s = re.sub(pattern, replacement, s)
            
            # 5. Fix any remaining unescaped backslashes
            s = re.sub(r'(?<!\\)\\(?![bfnrtu"\\/])', r'\\\\', s)
            
            # 6. Specifically for \u, ensure it's followed by 4 hex digits or escape it
            s = re.sub(r'(?<!\\)\\u(?![0-9a-fA-F]{4})', r'\\\\u', s)
            
            # 7. Fix unescaped quotes in strings (common in LaTeX)
            # This is tricky - we need to escape quotes that are inside string values
            # but not the structural quotes. We'll do a simple fix for obvious cases.
            s = re.sub(r'(?<=[^\\])"(?=[^,\]\}:\s])', r'\\"', s)
            return s.strip()

        # 1. Try to find JSON block in markdown
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                content = sanitize_json(json_match.group(1))
                return json.loads(content)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error in code block: {e}")
                # Try to save the problematic JSON for debugging
                logger.debug(f"Problematic JSON content: {content[:500]}...")
        
        # 2. Try to find the first '[' or '{' and last matching bracket
        try:
            # Look for an array first
            array_match = re.search(r'\[.*\]', text, re.DOTALL)
            if array_match:
                try:
                    content = sanitize_json(array_match.group(0))
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parse error in array search: {e}")
                    logger.debug(f"Problematic array content: {content[:500]}...")
            
            # Look for an object
            object_match = re.search(r'\{.*\}', text, re.DOTALL)
            if object_match:
                try:
                    content = sanitize_json(object_match.group(0))
                    return [json.loads(content)]
                except json.JSONDecodeError as e:
                    logger.warning(f"JSON parse error in object search: {e}")
                    logger.debug(f"Problematic object content: {content[:500]}...")
        except Exception as e:
            logger.error(f"Error during JSON extraction regex: {e}")
            
        # 3. Last resort: try to manually fix common LaTeX issues
        try:
            # Save the raw response for debugging
            logger.debug(f"Raw AI response that failed JSON parsing: {text[:1000]}...")
            
            # Try a more aggressive cleaning approach
            cleaned_text = text
            # Remove all control characters
            cleaned_text = ''.join(char for char in cleaned_text if ord(char) >= 32 or char in '\t\n\r')
            
            # Try parsing again
            json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
            if json_match:
                content = json_match.group(1)
                # More aggressive LaTeX fixing
                content = re.sub(r'\\(?![bfnrtu"\\/])', r'\\\\', content)
                return json.loads(content)
                
        except Exception as e:
            logger.error(f"Final JSON parsing attempt failed: {e}")
            
        # 4. Ultimate fallback: try to extract questions manually using regex
        try:
            logger.info("Attempting manual question extraction from AI response...")
            questions = []
            
            # Look for question patterns in the text - include question_number
            # This is a fallback when JSON parsing completely fails
            # More robust pattern that handles complex multiline text including newlines, numbered lists, etc.
            question_pattern = r'"question_number":\s*(\d+).*?"question_text":\s*"((?:[^"\\]|\\[\\"/bfnrt]|\\u[0-9a-fA-F]{4})*?)"\s*,.*?"question_type":\s*"([^"]+)"'
            
            matches = re.findall(question_pattern, text, re.DOTALL)
            for match in matches:
                question_number, question_text, question_type = match
                
                # Try to find options and correct_answer for this question
                # Look for the options array after this question_number
                options_pattern = rf'"question_number":\s*{question_number}.*?"options":\s*\[(.*?)\]'
                options_match = re.search(options_pattern, text, re.DOTALL)
                
                options = []
                if options_match and options_match.group(1).strip():
                    options_str = options_match.group(1)
                    # Handle both simple strings and complex strings with escapes
                    option_matches = re.findall(r'"((?:[^"\\]|\\.)*)"', options_str)
                    options = option_matches if option_matches else []
                
                # Try to find correct_answer for this question
                answer_pattern = rf'"question_number":\s*{question_number}.*?"correct_answer":\s*([^,\}}]*)'
                answer_match = re.search(answer_pattern, text, re.DOTALL)
                
                correct_answer = None
                if answer_match:
                    answer_str = answer_match.group(1).strip().strip('"').strip(',').strip()
                    if answer_str and answer_str.lower() not in ['null', 'none']:
                        correct_answer = answer_str
                
                questions.append({
                    "question_number": int(question_number),
                    "question_text": question_text,
                    "question_type": question_type,
                    "options": options,
                    "correct_answer": correct_answer,
                    "solution": "",
                    "subject": subject
                })
            
            if questions:
                logger.info(f"Manual extraction found {len(questions)} questions")
                
                # Special handling for questions 46-50 if they're missing
                question_numbers = [q.get('question_number') for q in questions]
                missing_questions = []
                for q_num in [46, 47, 48, 49, 50]:
                    if q_num not in question_numbers and f'"question_number": {q_num}' in text:
                        missing_questions.append(q_num)
                
                if missing_questions:
                    logger.info(f"Questions {missing_questions} found in text but not extracted, attempting special extraction...")
                    
                    for q_num in missing_questions:
                        # Look for this question specifically
                        q_pattern = rf'"question_number":\s*{q_num}.*?"question_text":\s*"([^"]*(?:\\.[^"]*)*)".*?"question_type":\s*"([^"]+)"'
                        q_match = re.search(q_pattern, text, re.DOTALL)
                        
                        if q_match:
                            question_text = q_match.group(1)
                            question_type = q_match.group(2)
                            
                            # Find options and correct_answer for this question
                            options_pattern = rf'"question_number":\s*{q_num}.*?"options":\s*\[(.*?)\]'
                            options_match = re.search(options_pattern, text, re.DOTALL)
                            
                            options = []
                            if options_match and options_match.group(1).strip():
                                options_str = options_match.group(1)
                                option_matches = re.findall(r'"((?:[^"\\]|\\.)*)"', options_str)
                                options = option_matches if option_matches else []
                            
                            answer_pattern = rf'"question_number":\s*{q_num}.*?"correct_answer":\s*([^,\}}]*)'
                            answer_match = re.search(answer_pattern, text, re.DOTALL)
                            
                            correct_answer = None
                            if answer_match:
                                answer_str = answer_match.group(1).strip().strip('"').strip(',').strip()
                                if answer_str and answer_str.lower() not in ['null', 'none']:
                                    correct_answer = answer_str
                            
                            questions.append({
                                "question_number": q_num,
                                "question_text": question_text,
                                "question_type": question_type,
                                "options": options,
                                "correct_answer": correct_answer,
                                "solution": "",
                                "subject": subject
                            })
                            
                            logger.info(f"Successfully added question {q_num} via special extraction")
                
                return questions
                
        except Exception as e:
            logger.error(f"Manual extraction failed: {e}")
            
        return []

    def _extract_specific_questions(self, text_content: str, subject: str, question_numbers: List[int]) -> List[Dict]:
        """Extract specific question numbers that were missed in the main extraction."""
        if not question_numbers:
            return []
        
        logger.info(f"Attempting targeted extraction for {subject} questions: {question_numbers}")
        
        # Build a focused prompt for specific question numbers
        numbers_str = ", ".join(map(str, question_numbers))
        
        prompt = f"""
        TASK: Extract ONLY the specific question numbers listed below from the {subject} section.
        
        TARGET QUESTIONS: {numbers_str}
        
        INSTRUCTIONS:
        1. Look for questions that start with these exact numbers: {numbers_str}
        2. Extract ONLY questions that belong to {subject}
        3. Include complete question text, options, and answers
        4. Preserve all mathematical formulas and LaTeX exactly
        5. For numerical questions, the answer should be a number
        6. For MCQ questions, the answer should be the option letter (A, B, C, D)
        
        CONTENT:
        {text_content}
        
        Return ONLY valid JSON array:
        [
            {{"question_number": 52, "question_text": "...", "question_type": "single_mcq", "options": ["A) ...", "B) ..."], "correct_answer": "A", "solution": "", "subject": "Chemistry"}}
        ]
        """
        
        try:
            response = self.model.generate_content(prompt)
            if not response.text:
                logger.warning(f"Empty response for targeted extraction of {subject} questions {question_numbers}")
                return []
            
            questions = self._clean_json_response(response.text, subject)
            if not questions:
                logger.warning(f"No questions parsed from targeted extraction response")
                return []
            
            # Filter to only the requested question numbers
            filtered_questions = []
            for q in questions:
                q_num = q.get('question_number')
                if q_num in question_numbers:
                    q['subject'] = subject
                    
                    # Extract question number if not present
                    if not q.get('question_number'):
                        text = q.get('question_text', '')
                        for pattern in [r'^(\d+)\.?\s', r'^\s*(\d+)\.?\s', r'Question\s*(\d+)', r'Q\.?\s*(\d+)']:
                            match = re.search(pattern, text.strip())
                            if match:
                                q['question_number'] = int(match.group(1))
                                break
                    
                    filtered_questions.append(q)
            
            logger.info(f"Targeted extraction found {len(filtered_questions)} specific questions")
            return filtered_questions
            
        except Exception as e:
            logger.error(f"Targeted extraction failed for {subject} questions {question_numbers}: {e}")
            return []
