#!/usr/bin/env python3
"""
Debug script to see what the AI is actually returning for chemistry extraction
"""

import os
import sys
import django
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from questions.services.agent_extraction_service import AgentExtractionService
import logging
import re

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def debug_ai_response():
    """Debug what the AI is actually returning"""
    
    print("Debugging AI response for chemistry extraction...")
    
    # Initialize the service
    service = AgentExtractionService(
        gemini_key='AIzaSyDlR87K380gV1uTpenEHufhTOYzjZUr52k'
    )
    
    # Get the OCR content
    pdf_path = '/Users/shradha/Exam_app/Exam_Frontendnextjs/input.pdf'
    text_content = service._fallback_local_parsing(pdf_path)
    
    print(f"Total OCR content length: {len(text_content)}")
    
    # Check if questions 46-50 are in the content
    questions_46_50_in_content = []
    for q_num in [46, 47, 48, 49, 50]:
        pattern = rf'{q_num}\..*?(?={q_num+1}\.|$)'
        match = re.search(pattern, text_content, re.DOTALL)
        if match:
            questions_46_50_in_content.append(q_num)
            print(f"Q{q_num} found in OCR: {match.group(0)[:100]}...")
    
    print(f"Questions 46-50 found in OCR: {questions_46_50_in_content}")
    
    # Now let's see what the AI extracts
    print("\n=== CALLING AI FOR CHEMISTRY EXTRACTION ===")
    
    # Temporarily modify the service to show the raw AI response
    import google.generativeai as genai
    
    # Build the same prompt as the service
    subject = "Chemistry"
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
                "subject": "{subject}"
            }}
        ]
        
        IMPORTANT: 
        - Ensure all backslashes in LaTeX are properly escaped (use \\\\ instead of \\).
        - Extract question numbers from patterns like "46.", "47.", "48." at the beginning of questions.
        - For "How many" questions with subparts, include ALL subparts in the question_text as ONE question.
        - ONLY extract questions that clearly belong to '{subject}' based on their content.
        """
    
    # Call the AI directly
    genai.configure(api_key='AIzaSyDlR87K380gV1uTpenEHufhTOYzjZUr52k')
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    try:
        response = model.generate_content(prompt)
        print(f"AI Response length: {len(response.text)}")
        print("=== RAW AI RESPONSE ===")
        print(response.text)
        print("=== END RAW AI RESPONSE ===")
        
        # Try to parse the response
        questions = service._clean_json_response(response.text, subject)
        print(f"\nParsed questions: {len(questions)}")
        
        # Check which question numbers were extracted
        question_numbers = []
        for q in questions:
            q_num = q.get('question_number')
            if q_num:
                question_numbers.append(q_num)
            else:
                # Try to extract from text
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
                        question_numbers.append(int(match.group(1)))
                        break
        
        print(f"Question numbers extracted: {sorted(question_numbers)}")
        print(f"Questions 46-50 in extracted: {[q for q in question_numbers if q in [46, 47, 48, 49, 50]]}")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_ai_response()