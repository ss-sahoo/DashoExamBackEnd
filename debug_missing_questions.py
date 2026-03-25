#!/usr/bin/env python3
"""
Debug script to find why specific Mathematics questions are being missed
"""
import os
import sys
import django
import re

# Add the project directory to Python path
sys.path.append('/Users/shradha/Exam_app/Exam_backendDjango')

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')

# Setup Django
django.setup()

from questions.models import PreAnalysisJob

def debug_missing_questions():
    """Debug why specific Mathematics questions are being missed"""
    print("🔍 Debugging missing Mathematics questions...")
    
    try:
        # Get the latest pre-analysis job
        latest_job = PreAnalysisJob.objects.order_by('-created_at').first()
        
        if not latest_job or not latest_job.subject_separated_content:
            print("❌ No pre-analysis job with separated content found")
            return
            
        # Get Mathematics content
        math_content = ""
        for subject, data in latest_job.subject_separated_content.items():
            if 'math' in subject.lower():
                if isinstance(data, dict):
                    math_content = data.get('content', '')
                else:
                    math_content = str(data)
                break
        
        if not math_content:
            print("❌ No Mathematics content found")
            return
        
        # Check for specific missing questions
        missing_questions = [56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 72, 73]
        
        print(f"🔍 Searching for missing questions in content...")
        
        for q_num in missing_questions:
            # Search for different patterns
            patterns = [
                f"{q_num}.",
                f"Q{q_num}",
                f"Q.{q_num}",
                f"Question {q_num}",
                f"## {q_num}",
                f"#{q_num}",
            ]
            
            found = False
            for pattern in patterns:
                if pattern in math_content:
                    # Find the context around this question
                    pos = math_content.find(pattern)
                    start = max(0, pos - 50)
                    end = min(len(math_content), pos + 200)
                    context = math_content[start:end].replace('\n', ' ')
                    print(f"   ✓ Q{q_num} found with pattern '{pattern}': ...{context}...")
                    found = True
                    break
            
            if not found:
                print(f"   ❌ Q{q_num} NOT found with any pattern")
        
        # Test the regex patterns used in _split_into_questions
        print(f"\n🔍 Testing regex patterns on Mathematics content...")
        
        patterns = [
            (r'(?:^|\n)\s*Q\.?\s*(\d+)[\.:\)\s]+', 'q_prefix'),
            (r'(?:^|\n)\s*Question[\s:]*(\d+)[\.:\)\s]+', 'question_word'),
            (r'(?:^|\n)\s*#{1,4}\s*(?:Q\.?\s*)?(\d+)[\.:\)\s]+', 'markdown_heading'),
            (r'(?:^|\n)\s*(\d+)[\.\)]\s+[A-Za-z0-9\\\$]', 'numbered'),
            (r'(?:^|\n|\|)\s*(\d+)\s*\|\s*[A-Za-z0-9\\\$]', 'table_row'),
        ]
        
        for pattern, name in patterns:
            matches = list(re.finditer(pattern, math_content, re.IGNORECASE | re.MULTILINE))
            question_numbers = [int(m.group(1)) for m in matches if m.group(1).isdigit()]
            print(f"   Pattern '{name}': Found {len(matches)} matches, Q numbers: {sorted(set(question_numbers))}")
        
        # Show a larger sample of the content to see the structure
        print(f"\n📝 Mathematics content structure analysis:")
        lines = math_content.split('\n')
        for i, line in enumerate(lines[:50]):  # First 50 lines
            if any(str(q) in line for q in [56, 57, 58, 59, 60]):
                print(f"   Line {i+1}: {line}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_missing_questions()