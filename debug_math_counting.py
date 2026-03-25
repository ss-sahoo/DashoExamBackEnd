#!/usr/bin/env python3
"""
Debug script to analyze Mathematics question counting issue
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
from questions.services.document_pre_analyzer import DocumentPreAnalyzer

def debug_math_counting():
    """Debug why Mathematics questions are being miscounted"""
    print("🔍 Debugging Mathematics question counting...")
    
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
                print(f"📚 Found Mathematics content: {len(math_content)} characters")
                break
        
        if not math_content:
            print("❌ No Mathematics content found")
            return
        
        # Show content preview
        print(f"\n📝 Mathematics content preview (first 1000 chars):")
        print(math_content[:1000])
        print("...")
        
        # Test the question splitting logic
        analyzer = DocumentPreAnalyzer()
        questions = analyzer._split_into_questions(math_content)
        
        print(f"\n🔢 Question splitting results:")
        print(f"   Total questions found: {len(questions)}")
        
        # Show first 10 questions
        print(f"\n📋 First 10 questions found:")
        for i, (q_num, q_text) in enumerate(questions[:10]):
            preview = q_text[:100].replace('\n', ' ')
            print(f"   {i+1}. Q{q_num}: {preview}...")
        
        # Check for specific question numbers we expect
        expected_math_questions = list(range(51, 76))  # Mathematics should be Q51-Q75
        found_numbers = [int(q_num) for q_num, _ in questions if q_num.isdigit()]
        
        print(f"\n🎯 Expected Mathematics questions: {expected_math_questions}")
        print(f"🔍 Found question numbers: {sorted(found_numbers)}")
        
        missing = set(expected_math_questions) - set(found_numbers)
        extra = set(found_numbers) - set(expected_math_questions)
        
        if missing:
            print(f"❌ Missing questions: {sorted(missing)}")
        if extra:
            print(f"⚠️  Extra questions: {sorted(extra)}")
        
        # Check if the content actually contains the expected questions
        print(f"\n🔍 Checking if content contains expected questions...")
        for q_num in [51, 52, 53, 70, 71, 72, 73, 74, 75]:
            if f"{q_num}." in math_content or f"Q{q_num}" in math_content:
                print(f"   ✓ Q{q_num} found in content")
            else:
                print(f"   ❌ Q{q_num} NOT found in content")
        
        # Check the actual question count using SectionQuestionExtractor
        from questions.services.section_question_extractor import SectionQuestionExtractor
        extractor = SectionQuestionExtractor()
        actual_count = extractor._count_questions_in_content(math_content)
        print(f"\n📊 SectionQuestionExtractor count: {actual_count}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_math_counting()