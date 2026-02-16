"""
AI Evaluation Service for Subjective Questions
Uses Gemini API to extract answers from handwritten PDFs and grade them.
Based on the Aveti New notebook logic.
"""
import os
import json
import time
import tempfile
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
import PIL.Image

# Use new google.genai package
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# Azure OpenAI
try:
    from openai import AzureOpenAI
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False


def get_genai_client():
    """Configure and return genai client"""
    if not GENAI_AVAILABLE:
        raise ImportError("google-generativeai package not installed. Run: pip install google-generativeai")
    
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured in settings")
    
    genai.configure(api_key=api_key)
    return genai


def get_azure_client():
    """Configure and return Azure OpenAI client"""
    if not AZURE_AVAILABLE:
        return None
    
    api_key = getattr(settings, 'AZURE_OPENAI_API_KEY', '')
    endpoint = getattr(settings, 'AZURE_OPENAI_ENDPOINT', '')
    version = getattr(settings, 'AZURE_OPENAI_VERSION', '2024-02-15-preview')
    
    if not api_key or not endpoint:
        return None
        
    return AzureOpenAI(
        api_key=api_key,
        api_version=version,
        azure_endpoint=endpoint
    )


def convert_pdf_to_images(pdf_path: str, output_folder: str, dpi: int = 300) -> List[str]:
    """
    Convert PDF pages to images for processing.
    
    Args:
        pdf_path: Path to the student's PDF file
        output_folder: Directory where images will be saved
        dpi: Resolution for extraction (300 recommended for handwriting)
    
    Returns:
        List of paths to saved images
    """
    from pdf2image import convert_from_path
    
    # Create output directory if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)
    
    # Convert PDF pages to PIL images
    images = convert_from_path(pdf_path, dpi=dpi, thread_count=4)
    
    image_paths = []
    for i, image in enumerate(images):
        page_num = i + 1
        image_name = f"page_{page_num}.png"
        path = os.path.join(output_folder, image_name)
        image.save(path, "PNG")
        image_paths.append(path)
    
    return image_paths


class AIEvaluationService:
    """
    Service for AI-powered grading of subjective answers.
    """
    
    SAFETY_SETTINGS = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
    
    MARKING_STRICTNESS_MAP = {
        'lenient': 'Lenient - Give benefit of doubt to students',
        'moderate': 'Moderate - Balance between strictness and leniency',
        'strict': 'Strict - Mark exactly according to rubric',
    }
    
    def __init__(self, exam, marking_strictness: str = 'moderate'):
        """
        Initialize AI evaluation service for an exam.
        
        Args:
            exam: Exam model instance
            marking_strictness: 'lenient', 'moderate', or 'strict'
        """
        self.exam = exam
        self.marking_strictness = marking_strictness
        
        # Prefer Azure if configured, fallback to Gemini
        self.azure_client = get_azure_client()
        if self.azure_client:
            self.llm_provider = 'azure'
            self.model_name = getattr(settings, 'AZURE_OPENAI_MODEL_NAME', 'gpt-4o')
        else:
            self.llm_provider = 'gemini'
            self.genai = get_genai_client()
            self.model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
            
            # Check for File API support (added in v0.4.0)
            self.has_file_api = hasattr(self.genai, 'upload_file')
            
            self.model = self.genai.GenerativeModel(
                model_name=self.model_name,
                safety_settings=self.SAFETY_SETTINGS
            )
            
        self.question_bank = self._build_question_bank()

    def _init_model(self):
        """Deprecated: Model initialization moved to __init__"""
        pass
    
    def _build_question_bank(self) -> List[Dict]:
        """Build question bank from exam question mappings"""
        from questions.models import ExamQuestion, Question
    
        question_bank = []
        seen_qids = set()
        
        # 1. Get questions from ExamQuestion mappings
        mappings = ExamQuestion.objects.filter(
            exam=self.exam
        ).select_related('question').order_by('question_number')
        
        for mapping in mappings:
            q = mapping.question
            if q.id in seen_qids:
                continue
                
            q_data = self._format_question_for_bank(q, mapping.question_number, mapping.marks, mapping.negative_marks)
            question_bank.append(q_data)
            seen_qids.add(q.id)
        
        # 2. Add questions linked directly via Question.exam (for newer/different exam structures)
        direct_questions = Question.objects.filter(
            exam=self.exam
        ).order_by('question_number')
        
        for q in direct_questions:
            if q.id in seen_qids:
                continue
                
            q_data = self._format_question_for_bank(q, q.question_number, q.marks, q.negative_marks)
            question_bank.append(q_data)
            seen_qids.add(q.id)
        
        return question_bank

    def _format_question_for_bank(self, q, q_no, marks, negative_marks) -> Dict:
        """Helper to format a Question object into the bank format"""
        q_data = {
            'Q.No.': q_no,
            'Question': q.question_text,
            'is_multi_part_question': bool(q.options and len(q.options) > 1 and q.question_type == 'subjective_multipart'),
            'mark': float(marks or 1),
            'negative_marks': float(negative_marks or 0),
            'Answer': q.correct_answer if q.correct_answer else q.explanation,
            'Diagram_is_required_for_answer': 1 if getattr(q, 'requires_diagram', False) else 0,
            'Diagram_file_names': [],
        }
        
        # Handle multipart questions
        if q_data['is_multi_part_question'] and q.options:
            parts = []
            for idx, opt in enumerate(q.options):
                if not isinstance(opt, dict):
                    continue
                parts.append({
                    'part.No.': chr(97 + idx),  # a, b, c, d...
                    'Question': opt.get('text', ''),
                    'mark': opt.get('marks', float(marks or 1) / len(q.options)),
                    'Answer': opt.get('answer', ''),
                    'Diagram_is_required_for_answer': 1 if opt.get('requires_diagram', False) else 0,
                })
            q_data['parts'] = parts
        
        return q_data
    
    def _encode_image(self, image_path: str) -> str:
        """Encode image to base64 for Azure OpenAI"""
        import base64
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _call_azure_openai_with_image(self, image_path: str, prompt: str) -> Optional[str]:
        """Call Azure OpenAI with an image and a prompt"""
        if not self.azure_client:
            return None
            
        base64_image = self._encode_image(image_path)
        
        try:
            response = self.azure_client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2048,
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[AZURE AI] Error: {e}")
            return None

    def _upload_file(self, file_path: str):
        """Upload file to Gemini and wait for processing"""
        if not self.has_file_api:
            # Fallback: return PIL Image instead of a File object
            return PIL.Image.open(file_path)
            
        uploaded_file = self.genai.upload_file(path=file_path)
        
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = self.genai.get_file(uploaded_file.name)
        
        return uploaded_file
    
    def _delete_file(self, file_obj):
        """Delete file from Gemini if File API is supported"""
        if self.has_file_api and file_obj and hasattr(file_obj, 'name'):
            try:
                self.genai.delete_file(file_obj.name)
            except:
                pass
    
    def _parse_json_response(self, text: str) -> Optional[Dict]:
        """Parse JSON response from AI, handling markdown wrappers"""
        if not text:
            return None
            
        # Robustly remove markdown backticks and language identifiers
        import re
        cleaned_text = text.strip()
        # Look for content between triple backticks
        match = re.search(r'```(?:json|JSON)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
        if match:
            cleaned_text = match.group(1)
        else:
            # Fallback: remove backticks manually if regex didn't match perfectly
            if cleaned_text.startswith("```"):
                cleaned_text = re.sub(r'^```[a-zA-Z]*\s*', '', cleaned_text)
            if cleaned_text.endswith("```"):
                cleaned_text = re.sub(r'\s*```$', '', cleaned_text)
        
        cleaned_text = cleaned_text.strip()
        
        try:
            return json.loads(cleaned_text)
        except json.JSONDecodeError:
            # Attempt to fix unescaped double quotes within string values
            # Heuristic: Find double quotes that are not preceded by { [ : , or followed by } ] : ,
            try:
                # Replace " inside reasoning or other text fields
                # This regex looks for double quotes that aren't structural
                fixed_text = re.sub(r'(?<![:{\[,])\s*"\s*(?![:}\],])', r'\\"', cleaned_text)
                return json.loads(fixed_text)
            except:
                print(f"JSON Parse Error (even after repair attempt). Raw: {text}")
                return None

    def _extract_first_page_answers(self, image_path: str) -> Dict:
        """Extract student answers from the first page"""
        prompt = f"""
        You are an expert academic grader. Evaluate student responses accurately based on the provided rubric.
        You are an expert grading assistant specialized in visual document analysis. 
        Using the attached handwritten document and the provided Question Bank JSON:
        You are analyzing the first page of the answer sheet.
        
        Question Bank JSON: {json.dumps(self.question_bank)}
        
        Task:
        1. Identify the student's name if visible.
        2. Extract the answer written by student.
        3. Each question number in the answer sheet must match with the question number of Question Bank.
        4. If a question has sub-parts (e.g., 10(a), 10(b)), extract them clearly with Q.No. as '10' and Part.No. as 'a', 'b', etc.
        5. Keep an eye for questions that might have started on previous page and are continuing here.
        6. Check if diagrams are available in the answer sheet.
        
        Output strictly as a JSON object:
        {{
          "Name": "Student Name or null",
          "Answers": [
            {{
              "Q.No.": <integer>,
              "Is_multipart": <boolean>,
              "Part.No.": "<string or null>",
              "Answer_text_written": "<extracted text>",
              "diagram_available": <1 if drawing exists, else 0>
            }}
          ]
        }}
        
        Do not include any conversational text or markdown code blocks.
        """

        if self.llm_provider == 'azure':
            response_text = self._call_azure_openai_with_image(image_path, prompt)
            return self._parse_json_response(response_text) or {"error": "Azure OpenAI parse error"}
        else:
            uploaded_file = self._upload_file(image_path)
            try:
                response = self.model.generate_content(
                    [uploaded_file, prompt],
                    generation_config={
                        "temperature": 0.1
                    }
                )
                
                if response.text:
                    return self._parse_json_response(response.text) or {"error": "Invalid JSON response", "raw_text": response.text}
                return None
            finally:
                self._delete_file(uploaded_file)
    
    def _extract_other_page_answers(
        self, 
        image_path: str, 
        page_no: int, 
        total_pages: int, 
        last_page_answers: List[Dict]
    ) -> List[Dict]:
        """Extract student answers from subsequent pages"""
        last_question = last_page_answers[-1] if last_page_answers else {}
        last_q_no = last_question.get("Q.No.", 1)
        is_multipart = last_question.get("Is_multipart", False)
        part_no = last_question.get("Part.No.")
        
        prompt = f"""
        You are an expert academic grader. Evaluate student responses accurately based on the provided rubric.
        You are an expert grading assistant specialized in visual document analysis.
        You are analyzing page number {page_no} out of {total_pages} total pages.
        
        On the previous page, the student was attempting question number {last_q_no}.
        If no question number is mentioned at the beginning of this page, treat it as a continuation.
        
        Question Bank JSON: {json.dumps(self.question_bank)}
        
        Previous Page Context:
        - Last question number: {last_q_no}
        - Is last question multipart: {is_multipart}
        - Part number: {part_no}
        
        Task:
        1. Extract the answer written by student.
        2. Each question number must match with the Question Bank.
        3. Check if diagrams are available.
        
        Output strictly as a JSON array:
        [
          {{
            "Q.No.": <integer>,
            "Is_multipart": <boolean>,
            "Part.No.": "<string or null>",
            "Answer_text_written": "<extracted text>",
            "diagram_available": <1 if drawing exists, else 0>
          }}
        ]
        
        Do not include any conversational text or markdown code blocks.
        """

        if self.llm_provider == 'azure':
            response_text = self._call_azure_openai_with_image(image_path, prompt)
            if response_text:
                try:
                    return json.loads(response_text)
                except json.JSONDecodeError:
                    return [{"error": "Invalid JSON", "raw_text": response_text}]
            return []
        else:
            uploaded_file = self._upload_file(image_path)
            try:
                response = self.model.generate_content(
                    [uploaded_file, prompt],
                    generation_config={
                        "temperature": 0.1
                    }
                )
                
                if response.text:
                    return self._parse_json_response(response.text) or [{"error": "Invalid JSON response", "raw_text": response.text}]
                return []
            finally:
                self._delete_file(uploaded_file)
    
    def extract_all_answers(self, image_paths: List[str]) -> Tuple[List[Dict], str]:
        """
        Extract all student answers from multiple page images.
        
        Returns:
            Tuple of (answers_list, student_name)
        """
        total_pages = len(image_paths)
        all_answers = []
        student_name = "Unknown"
        
        for i, img_path in enumerate(image_paths):
            page_no = i + 1
            
            if i == 0:
                # First page extraction
                data = self._extract_first_page_answers(img_path)
                if data:
                    student_name = data.get("Name", "Unknown")
                    answers = data.get("Answers", [])
                    if isinstance(answers, list):
                        for ans in answers:
                            if ans:
                                ans["page_no"] = [page_no]
                        # Filter out any None values that might have slipped through
                        all_answers.extend([ans for ans in answers if ans])
            else:
                # Subsequent pages
                page_answers = self._extract_other_page_answers(
                    img_path, page_no, total_pages, all_answers
                )
                
                if isinstance(page_answers, list):
                    for ans in page_answers:
                        if ans:
                            ans["page_no"] = [page_no]
                    page_answers = [ans for ans in page_answers if ans]
                else:
                    page_answers = []
                
                # Merge continuation answers
                if page_answers and all_answers:
                    p0 = page_answers[0]
                    an = all_answers[-1]
                    if (p0 and an and 
                        p0.get("Q.No.") == an.get("Q.No.") and
                        p0.get("Part.No.") == an.get("Part.No.")):
                        # Merge the first answer with the last one from previous page
                        last_ans = all_answers.pop()
                        first_new = page_answers[0]
                        
                        merged = {
                            "Q.No.": last_ans["Q.No."],
                            "Is_multipart": last_ans.get("Is_multipart", False),
                            "Part.No.": last_ans.get("Part.No."),
                            "Answer_text_written": (
                                (last_ans.get("Answer_text_written") or "") + " " +
                                (first_new.get("Answer_text_written") or "")
                            ),
                            "diagram_available": max(
                                last_ans.get("diagram_available", 0),
                                first_new.get("diagram_available", 0)
                            ),
                            "page_no": last_ans.get("page_no", []) + first_new.get("page_no", [])
                        }
                        all_answers.append(merged)
                        all_answers.extend(page_answers[1:])
                    else:
                        all_answers.extend(page_answers)
                else:
                    all_answers.extend(page_answers)
        
        return all_answers, student_name
    
    def grade_answer(
        self,
        question_data: Dict,
        student_response: Dict,
        student_image_paths: Optional[List[str]] = None,
        reference_diagram_paths: Optional[List[str]] = None
    ) -> Dict:
        """
        Grade a single student answer using AI.
        
        Returns:
            Dict with 'mark' and 'reasoning'
        """
        # Build grading prompt
        q_no = question_data.get("Q.No.")
        part_no = student_response.get("Part.No.")
        is_multipart = question_data.get("is_multi_part_question", False)
        question_text = question_data.get("Question", "")
        max_mark = question_data.get("mark", 1)
        correct_answer = question_data.get("Answer", "")
        diagram_required = question_data.get("Diagram_is_required_for_answer", 0)
        
        # For multipart questions, get part-specific data
        if is_multipart and part_no and "parts" in question_data:
            # Normalization map for common sub-part labels
            normalization = {
                'i': 'a', 'ii': 'b', 'iii': 'c', 'iv': 'd', 'v': 'e', 'vi': 'f',
                '1': 'a', '2': 'b', '3': 'c', '4': 'd', '5': 'e', '6': 'f'
            }
            norm_part_no = str(part_no).lower().strip('.')
            norm_part_no = normalization.get(norm_part_no, norm_part_no)
            
            for part in question_data["parts"]:
                if not isinstance(part, dict):
                    continue
                bank_part_no = str(part.get("part.No.", "")).lower().strip('.')
                bank_part_no = normalization.get(bank_part_no, bank_part_no)
                
                if bank_part_no == norm_part_no:
                    max_mark = part.get("mark", max_mark)
                    correct_answer = part.get("Answer", correct_answer)
                    diagram_required = part.get("Diagram_is_required_for_answer", diagram_required)
                    break
        
        student_text = student_response.get("Answer_text_written", "")
        diagram_available = student_response.get("diagram_available", 0)
        
        marking_instruction = self.MARKING_STRICTNESS_MAP.get(
            self.marking_strictness, 
            self.MARKING_STRICTNESS_MAP['moderate']
        )
        
        prompt = f"""
        You are an expert academic grader. Evaluate student responses accurately based on the provided rubric.
        TASK: Grade the student's response for Question {q_no}.
        
        QUESTION DETAILS:
        - Question: {question_text}
        - Is multipart: {is_multipart}
        - Part number: {part_no or 'N/A'}
        - Correct Answer: {correct_answer}
        - Diagram required for full marks: {'Yes' if diagram_required else 'No'}
        - Maximum Marks: {max_mark}
        
        STUDENT DATA:
        - Written text: "{student_text}"
        - Diagram provided: {'Yes' if diagram_available else 'No'}
        
        MARKING INSTRUCTIONS:
        - Marking style: {marking_instruction}
        - Compare student's text to the correct answer
        - If diagram is required but missing, deduct marks accordingly
        - Assign marks based on correctness of text and diagram
        - Use single quotes (') for any text identifiers inside the reasoning (e.g., 'd X' instead of "d X").
        - DO NOT use unescaped double quotes inside the reasoning string.
        
        Output strictly as JSON:
        {{"mark": <number between 0 and {max_mark}>, "reasoning": "<short explanation>"}}
        """

        if self.llm_provider == 'azure':
            # Note: For grading, we use the first relevant image if diagram exists
            img_path = student_image_paths[0] if student_image_paths else None
            if diagram_available and img_path:
                response_text = self._call_azure_openai_with_image(img_path, prompt)
            else:
                # Text-only call for Azure
                try:
                    response = self.azure_client.chat.completions.create(
                        model=self.model_name,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.1,
                        response_format={"type": "json_object"}
                    )
                    response_text = response.choices[0].message.content
                except Exception as e:
                    print(f"[AZURE AI] Grade Error: {e}")
                    response_text = None
            
            if response_text:
                try:
                    result = json.loads(response_text)
                    if isinstance(result, dict):
                        result['mark'] = max(0, min(result.get('mark', 0), max_mark))
                        return result
                    else:
                        return {"error": "Invalid JSON structure", "raw_text": response_text}
                except json.JSONDecodeError:
                    return {"error": "Invalid JSON", "raw_text": response_text}
            return {"error": "AI returned no content"}
            
        else:
            uploaded_files = []
            try:
                content_payload = []
                # Upload reference diagrams if provided
                if reference_diagram_paths:
                    content_payload.append("REFERENCE MATERIAL: These are the correct model diagrams:")
                    for path in reference_diagram_paths:
                        ref_file = self._upload_file(path)
                        uploaded_files.append(ref_file)
                        content_payload.append(ref_file)
                
                # Upload student answer images if provided
                if student_image_paths:
                    content_payload.append("STUDENT SUBMISSION: These are pages from the student's answer:")
                    for path in student_image_paths:
                        student_file = self._upload_file(path)
                        uploaded_files.append(student_file)
                        content_payload.append(student_file)
                
                content_payload.insert(0, prompt)
                
                response = self.model.generate_content(
                    content_payload,
                    generation_config={
                        "temperature": 0.1
                    }
                )
                
                if response.text:
                    result = self._parse_json_response(response.text)
                    if result:
                        result['mark'] = max(0, min(result.get('mark', 0), max_mark))
                        return result
                    else:
                        return {"error": "Invalid JSON response", "raw_text": response.text}
                return {"error": "Empty response"}
            finally:
                for f in uploaded_files:
                    self._delete_file(f)
    
    def grade_all_answers(
        self,
        answers: List[Dict],
        image_paths: List[str]
    ) -> List[Dict]:
        """
        Grade all extracted student answers.
        
        Returns:
            List of grading results
        """
        grades = []
        
        for answer in answers:
            if not isinstance(answer, dict):
                continue
            q_no = answer.get("Q.No.")
            part_no = answer.get("Part.No.")
            
            # Find matching question in bank
            question_data = None
            for q in self.question_bank:
                if isinstance(q, dict) and q.get("Q.No.") == q_no:
                    question_data = q
                    break
            
            if not question_data:
                grades.append({
                    "Q.No.": q_no,
                    "Part.No.": part_no,
                    "mark": 0,
                    "reasoning": f"Question {q_no} not found in question bank"
                })
                continue
            
            # Get relevant page images
            page_numbers = answer.get("page_no", [])
            student_images = [image_paths[p - 1] for p in page_numbers if p <= len(image_paths)]
            
            # Determine if diagrams need comparison
            diagram_required = question_data.get("Diagram_is_required_for_answer", 0)
            diagram_available = answer.get("diagram_available", 0)
            
            reference_diagrams = None
            if diagram_required and diagram_available:
                reference_diagrams = question_data.get("Diagram_file_names", [])
            
            # Grade the answer
            result = self.grade_answer(
                question_data=question_data,
                student_response=answer,
                student_image_paths=student_images if diagram_available else None,
                reference_diagram_paths=reference_diagrams
            )
            
            grade = {
                "Q.No.": q_no,
                "Part.No.": part_no,
                "Is_multipart": answer.get("Is_multipart", False),
                "Answer_text_written": answer.get("Answer_text_written", ""),
                **result
            }
            grades.append(grade)
        
        return grades
    
    def generate_report(
        self,
        grades: List[Dict],
        student_name: str
    ) -> str:
        """Generate a text report of grading results"""
        total_marks = sum(g.get("mark", 0) for g in grades if isinstance(g.get("mark"), (int, float)))
        max_possible = sum(
            q.get("mark", 0) for q in self.question_bank
        )
        
        lines = [
            "=" * 50,
            "STUDENT GRADING REPORT",
            "=" * 50,
            f"Student Name: {student_name}",
            f"Exam: {self.exam.title}",
            f"Total Marks Obtained: {total_marks:.1f} / {max_possible:.1f}",
            f"Percentage: {(total_marks / max_possible * 100) if max_possible > 0 else 0:.1f}%",
            "-" * 50,
            ""
        ]
        
        for grade in grades:
            if not isinstance(grade, dict):
                continue
            q_no = grade.get("Q.No.")
            part_no = grade.get("Part.No.")
            mark = grade.get("mark", 0)
            reasoning = grade.get("reasoning", "") or ""
            answer_text = (grade.get("Answer_text_written") or "")[:100]  # Truncate long answers
            
            q_label = f"Q{q_no}" + (f"({part_no})" if part_no else "")
            
            lines.extend([
                f"{q_label}",
                f"  Mark: {mark}",
                f"  Answer: {answer_text}{'...' if len(answer_text) >= 100 else ''}",
                f"  Analysis: {reasoning}",
                ""
            ])
        
        lines.extend([
            "-" * 50,
            f"FINAL SCORE: {total_marks:.1f} / {max_possible:.1f}",
            "=" * 50
        ])
        
        return "\n".join(lines)


def evaluate_subjective_submission(
    exam_id: int,
    pdf_path: str,
    marking_strictness: str = 'moderate'
) -> Dict:
    """
    Main entry point for evaluating a subjective exam submission.
    
    Args:
        exam_id: ID of the exam
        pdf_path: Path to the student's PDF answer sheet
        marking_strictness: 'lenient', 'moderate', or 'strict'
    
    Returns:
        Dict with evaluation results
    """
    from exams.models import Exam
    
    # Get exam
    exam = Exam.objects.get(id=exam_id)
    
    # Create service
    service = AIEvaluationService(exam, marking_strictness)
    
    # Create temp directory for images
    temp_dir = tempfile.mkdtemp(prefix='ai_eval_')
    
    try:
        # Convert PDF to images
        image_paths = convert_pdf_to_images(pdf_path, temp_dir)
        
        # Extract answers
        answers, student_name = service.extract_all_answers(image_paths)
        
        # Grade answers
        grades = service.grade_all_answers(answers, image_paths)
        
        # Generate report
        report = service.generate_report(grades, student_name)
        
        # Calculate totals
        total_marks = sum(g.get("mark", 0) for g in grades if isinstance(g.get("mark"), (int, float)))
        max_possible = sum(q.get("mark", 0) for q in service.question_bank)
        
        return {
            "success": True,
            "student_name": student_name,
            "total_marks": total_marks,
            "max_marks": max_possible,
            "percentage": (total_marks / max_possible * 100) if max_possible > 0 else 0,
            "grades": grades,
            "report": report,
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
        }
    
    finally:
        # Cleanup temp images
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except:
                pass
        try:
            os.rmdir(temp_dir)
        except:
            pass
