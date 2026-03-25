#!/usr/bin/env python3
"""
Debug script to check why question 48 is missing
"""

import os
import sys
import django
from pathlib import Path
import re

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from questions.services.agent_extraction_service import AgentExtractionService
import google.generativeai as genai

def debug_q48():
    """Debug why question 48 is missing"""
    
    print("Debugging question 48 extraction...")
    
    # Initialize the service
    service = AgentExtractionService(
        gemini_key='AIzaSyDlR87K380gV1uTpenEHufhTOYzjZUr52k'
    )
    
    # Get the OCR content
    pdf_path = '/Users/shradha/Exam_app/Exam_Frontendnextjs/input.pdf'
    text_content = service._fallback_local_parsing(pdf_path)
    
    # Call AI for chemistry
    genai.configure(api_key='AIzaSyDlR87K380gV1uTpenEHufhTOYzjZUr52k')
    model = genai.GenerativeModel('gemini-2.0-flash')
    
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
    
    try:
        response = model.generate_content(prompt)
        print(f"AI Response length: {len(response.text)}")
        
        # Check if question 48 is in the raw response
        if '"question_number": 48' in response.text:
            print("✓ Question 48 found in AI response")
            
            # Extract the question 48 block
            q48_match = re.search(r'"question_number":\s*48.*?(?="question_number":\s*49|$)', response.text, re.DOTALL)
            if q48_match:
                print("Question 48 block:")
                print(q48_match.group(0)[:500] + "...")
            
        else:
            print("✗ Question 48 NOT found in AI response")
        
        # Test manual extraction on this response
        questions = service._clean_json_response(response.text, subject)
        print(f"\nParsed questions: {len(questions)}")
        
        # Check which question numbers were extracted
        question_numbers = [q.get('question_number') for q in questions if q.get('question_number')]
        print(f"Question numbers extracted: {sorted(question_numbers)}")
        
        if 48 in question_numbers:
            print("✓ Question 48 successfully extracted")
            q48 = next(q for q in questions if q.get('question_number') == 48)
            print(f"Q48 type: {q48.get('question_type')}")
            print(f"Q48 text: {q48.get('question_text')[:200]}...")
        else:
            print("✗ Question 48 NOT extracted by manual parsing")
            
            # Test the manual extraction regex directly
            question_pattern = r'"question_number":\s*(\d+).*?"question_text":\s*"([^"]*(?:\\.[^"]*)*)".*?"question_type":\s*"([^"]+)"'
            matches = re.findall(question_pattern, response.text, re.DOTALL)
            
            manual_numbers = [int(match[0]) for match in matches]
            print(f"Manual regex found question numbers: {sorted(manual_numbers)}")
            
            if 48 in manual_numbers:
                print("✓ Question 48 found by manual regex")
                q48_match = next(match for match in matches if int(match[0]) == 48)
                print(f"Q48 manual: {q48_match[0]}, {q48_match[2]}, {q48_match[1][:100]}...")
            else:
                print("✗ Question 48 NOT found by manual regex")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_q48()