#!/usr/bin/env python3
"""
Debug script to test the pattern filtering logic
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

def debug_pattern_filtering():
    """Debug the pattern filtering logic"""
    print("🔍 Debugging pattern filtering logic...")
    
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
        
        # Test the numbered pattern specifically
        pattern = r'(?:^|\n)\s*(\d+)[\.\)]\s+[A-Za-z0-9\\\$]'
        matches = list(re.finditer(pattern, math_content, re.IGNORECASE | re.MULTILINE))
        
        print(f"🔍 Testing 'numbered' pattern filtering...")
        print(f"   Total matches found: {len(matches)}")
        
        # Test the filtering logic
        filtered_out = []
        kept = []
        
        for match in matches:
            q_num = match.group(1)
            m_start = match.start()
            
            # Test the filtering conditions
            pre_context_start = max(0, m_start - 30)
            pre_context = math_content[pre_context_start:m_start].lower()
            
            # Check filtering conditions
            filtered = False
            reason = ""
            
            if pre_context.rstrip().endswith(('step', 'sol.', 'sol')):
                filtered = True
                reason = "ends with step/sol"
            elif 'step' in pre_context and '\n' not in pre_context:
                filtered = True
                reason = "contains 'step' without newline"
            elif int(q_num) <= 4 and any(marker in pre_context for marker in ['option', '(a)', '(b)', '(c)', '(d)']):
                filtered = True
                reason = "low number with option markers"
            
            if filtered:
                filtered_out.append((q_num, reason, pre_context))
            else:
                kept.append(q_num)
        
        print(f"   Questions kept: {sorted([int(q) for q in kept])}")
        print(f"   Questions filtered out: {len(filtered_out)}")
        
        if filtered_out:
            print(f"\n❌ Filtered out questions:")
            for q_num, reason, context in filtered_out[:10]:  # Show first 10
                print(f"   Q{q_num}: {reason} | Context: '{context}'")
        
        # Check specific missing questions
        missing_questions = [56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 72, 73]
        
        print(f"\n🔍 Checking why specific questions are missing...")
        for q_num in missing_questions:
            q_str = str(q_num)
            if q_str in kept:
                print(f"   ✓ Q{q_num} is kept")
            elif any(q_str == fq[0] for fq in filtered_out):
                reason = next(fq[1] for fq in filtered_out if fq[0] == q_str)
                print(f"   ❌ Q{q_num} filtered out: {reason}")
            else:
                print(f"   ❓ Q{q_num} not found in matches")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_pattern_filtering()