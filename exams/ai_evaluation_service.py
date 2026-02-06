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

# Use new google.genai package
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


def get_genai_client():
    """Configure and return genai client"""
    if not GENAI_AVAILABLE:
        raise ImportError("google-generativeai package not installed. Run: pip install google-generativeai")
    
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured in settings")
    
    genai.configure(api_key=api_key)
    return genai


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
        self.genai = get_genai_client()
        self.model = self._init_model()
        self.question_bank = self._build_question_bank()
    
    def _init_model(self):
        """Initialize the Gemini model"""
        model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')
        return self.genai.GenerativeModel(
            model_name=model_name,
            safety_settings=self.SAFETY_SETTINGS,
            system_instruction="You are an expert academic grader. Evaluate student responses accurately based on the provided rubric."
        )
    
    def _build_question_bank(self) -> List[Dict]:
        """Build question bank from exam question mappings"""
        from questions.models import ExamQuestion
        
        question_bank = []
        mappings = ExamQuestion.objects.filter(
            exam=self.exam
        ).select_related('question').order_by('question_number')
        
        for i, mapping in enumerate(mappings, start=1):
            q = mapping.question
            
            q_data = {
                'Q.No.': i,
                'Question': q.question_text,
                'is_multi_part_question': bool(q.options and len(q.options) > 1 and q.question_type == 'subjective_multipart'),
                'mark': float(mapping.marks),
                'negative_marks': float(mapping.negative_marks),
                'Answer': q.correct_answer if q.correct_answer else q.explanation,
                'Diagram_is_required_for_answer': 1 if getattr(q, 'requires_diagram', False) else 0,
                'Diagram_file_names': [],
            }
            
            # Handle multipart questions
            if q_data['is_multi_part_question'] and q.options:
                parts = []
                for idx, opt in enumerate(q.options):
                    parts.append({
                        'part.No.': chr(97 + idx),  # a, b, c, d...
                        'Question': opt.get('text', ''),
                        'mark': opt.get('marks', mapping.marks / len(q.options)),
                        'Answer': opt.get('answer', ''),
                        'Diagram_is_required_for_answer': 1 if opt.get('requires_diagram', False) else 0,
                    })
                q_data['parts'] = parts
            
            question_bank.append(q_data)
        
        return question_bank
    
    def _upload_file(self, file_path: str):
        """Upload file to Gemini and wait for processing"""
        uploaded_file = self.genai.upload_file(path=file_path)
        
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = self.genai.get_file(uploaded_file.name)
        
        return uploaded_file
    
    def _extract_first_page_answers(self, image_path: str) -> Dict:
        """Extract student answers from the first page"""
        uploaded_file = self._upload_file(image_path)
        
        try:
            prompt = f"""
            You are an expert grading assistant specialized in visual document analysis. 
            Using the attached handwritten document and the provided Question Bank JSON:
            You are analyzing the first page of the answer sheet.
            
            Question Bank JSON: {json.dumps(self.question_bank)}
            
            Task:
            1. Identify the student's name if visible.
            2. Extract the answer written by student.
            3. Each question number in the answer sheet must match with the question number of Question Bank.
            4. Check if diagrams are available in the answer sheet.
            
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
            
            response = self.model.generate_content(
                [uploaded_file, prompt],
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1
                }
            )
            
            if response.text:
                try:
                    return json.loads(response.text)
                except json.JSONDecodeError:
                    return {"error": "Invalid JSON response", "raw_text": response.text}
            return None
            
        finally:
            self.genai.delete_file(uploaded_file.name)
    
    def _extract_other_page_answers(
        self, 
        image_path: str, 
        page_no: int, 
        total_pages: int, 
        last_page_answers: List[Dict]
    ) -> List[Dict]:
        """Extract student answers from subsequent pages"""
        uploaded_file = self._upload_file(image_path)
        
        try:
            last_question = last_page_answers[-1] if last_page_answers else {}
            last_q_no = last_question.get("Q.No.", 1)
            is_multipart = last_question.get("Is_multipart", False)
            part_no = last_question.get("Part.No.")
            
            prompt = f"""
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
            
            response = self.model.generate_content(
                [uploaded_file, prompt],
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1
                }
            )
            
            if response.text:
                try:
                    return json.loads(response.text)
                except json.JSONDecodeError:
                    return [{"error": "Invalid JSON", "raw_text": response.text}]
            return []
            
        finally:
            self.genai.delete_file(uploaded_file.name)
    
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
                    for ans in answers:
                        ans["page_no"] = [page_no]
                    all_answers.extend(answers)
            else:
                # Subsequent pages
                page_answers = self._extract_other_page_answers(
                    img_path, page_no, total_pages, all_answers
                )
                
                for ans in page_answers:
                    ans["page_no"] = [page_no]
                
                # Merge continuation answers
                if page_answers and all_answers:
                    if (page_answers[0].get("Q.No.") == all_answers[-1].get("Q.No.") and
                        page_answers[0].get("Part.No.") == all_answers[-1].get("Part.No.")):
                        # Merge the first answer with the last one from previous page
                        last_ans = all_answers.pop()
                        first_new = page_answers[0]
                        
                        merged = {
                            "Q.No.": last_ans["Q.No."],
                            "Is_multipart": last_ans.get("Is_multipart", False),
                            "Part.No.": last_ans.get("Part.No."),
                            "Answer_text_written": (
                                last_ans.get("Answer_text_written", "") + " " +
                                first_new.get("Answer_text_written", "")
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
                for part in question_data["parts"]:
                    if part.get("part.No.") == part_no:
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
            - Locate Question {q_no} on student sheets if images provided
            - Compare student's drawing to reference if provided
            - Assign marks based on correctness of text and diagram
            
            Output strictly as JSON:
            {{"mark": <number between 0 and {max_mark}>, "reasoning": "<short explanation>"}}
            """
            
            content_payload.insert(0, prompt)
            
            response = self.model.generate_content(
                content_payload,
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1
                }
            )
            
            if response.text:
                try:
                    result = json.loads(response.text)
                    # Ensure mark is within bounds
                    result['mark'] = max(0, min(result.get('mark', 0), max_mark))
                    return result
                except json.JSONDecodeError:
                    return {"error": "Invalid JSON", "raw_text": response.text}
            
            return {"error": "Empty response"}
            
        except Exception as e:
            return {"error": str(e)}
            
        finally:
            # Cleanup uploaded files
            for f in uploaded_files:
                try:
                    self.genai.delete_file(f.name)
                except:
                    pass
    
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
            q_no = answer.get("Q.No.")
            part_no = answer.get("Part.No.")
            
            # Find matching question in bank
            question_data = None
            for q in self.question_bank:
                if q["Q.No."] == q_no:
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
            q_no = grade.get("Q.No.")
            part_no = grade.get("Part.No.")
            mark = grade.get("mark", 0)
            reasoning = grade.get("reasoning", "")
            answer_text = grade.get("Answer_text_written", "")[:100]  # Truncate long answers
            
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
