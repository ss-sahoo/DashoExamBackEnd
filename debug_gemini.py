import google.generativeai as genai
import os
from django.conf import settings
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

def test_gemini():
    api_key = getattr(settings, 'GEMINI_API_KEY', '')
    print(f"API Key start: {api_key[:10]}...")
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    subject = "Mathematics"
    text_content = "Question 1: What is 2+2? A) 3 B) 4 C) 5 D) 6. Answer: B. Solution: 2+2=4."
    
    prompt = f"""
    SYSTEM: You are a high-precision Exam Extractor for ANY subject.
    TASK: Extract ALL questions belonging to the subject '{subject}' or its equivalent variations.
    
    SOURCE TEXT:
    {text_content}
    
    STRICT RULES:
    1. Extract every question found.
    2. Preserve LaTeX formulas.
    3. correct_answer MUST be option letter.
    4. Capture solution.
    5. Preserve image tags ![image_id](image_id) if present.
    
    Return ONLY a valid JSON array of objects with this structure:
    [
        {{
            "question_text": "...",
            "question_type": "single_mcq",
            "options": ["A) ...", "B) ..."],
            "correct_answer": "A", 
            "solution": "...",
            "subject": "{subject}"
        }}
    ]
    """
    
    try:
        response = model.generate_content(prompt)
        print("Response text:")
        print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_gemini()
