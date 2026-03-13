#!/usr/bin/env python3
"""
Debug script to check the format of missing questions
"""
import os
import sys
import django

# Add the project directory to Python path
sys.path.append('/Users/shradha/Exam_app/Exam_backendDjango')

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')

# Setup Django
django.setup()

from questions.models import PreAnalysisJob

def debug_question_format():
    """Debug the format of missing questions"""
    print("🔍 Debugging question format...")
    
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
        
        # Check the format of specific missing questions
        missing_questions = [64, 65, 66, 67, 68, 69, 70, 72, 73]
        
        print(f"🔍 Checking format of missing questions...")
        
        for q_num in missing_questions:
            # Find the question in the content
            patterns_to_try = [
                f"{q_num}.",
                f"Q{q_num}",
                f"## {q_num}",
                f"#{q_num}",
            ]
            
            found = False
            for pattern in patterns_to_try:
                pos = math_content.find(pattern)
                if pos != -1:
                    # Show context around the question
                    start = max(0, pos - 100)
                    end = min(len(math_content), pos + 300)
                    context = math_content[start:end]
                    
                    print(f"\n📝 Q{q_num} found with pattern '{pattern}':")
                    print(f"   Context: {repr(context)}")
                    
                    # Check what character comes after the number
                    after_pos = pos + len(pattern)
                    if after_pos < len(math_content):
                        next_chars = math_content[after_pos:after_pos+10]
                        print(f"   Next chars: {repr(next_chars)}")
                    
                    found = True
                    break
            
            if not found:
                print(f"   ❌ Q{q_num} not found with any pattern")
        
        # Test the regex pattern on these specific areas
        import re
        pattern = r'(?:^|\n)\s*(\d+)[\.\)]\s+[A-Za-z0-9\\\$]'
        
        print(f"\n🔍 Testing regex pattern on specific question areas...")
        
        for q_num in missing_questions:
            # Find the question area
            q_pos = math_content.find(f"{q_num}.")
            if q_pos != -1:
                # Extract a small area around the question
                start = max(0, q_pos - 50)
                end = min(len(math_content), q_pos + 200)
                area = math_content[start:end]
                
                # Test the regex on this area
                matches = list(re.finditer(pattern, area, re.IGNORECASE | re.MULTILINE))
                question_numbers = [m.group(1) for m in matches]
                
                print(f"   Q{q_num} area: {len(matches)} matches, numbers: {question_numbers}")
                if not any(m.group(1) == str(q_num) for m in matches):
                    print(f"   ❌ Q{q_num} not matched by regex in its area")
                    print(f"   Area preview: {repr(area[:100])}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_question_format()