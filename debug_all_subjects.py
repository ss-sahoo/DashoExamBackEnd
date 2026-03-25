#!/usr/bin/env python3
"""
Debug script to analyze all subjects' question counting
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

def debug_all_subjects():
    """Debug question counting for all subjects"""
    print("🔍 Debugging all subjects' question counting...")
    
    try:
        # Get the latest pre-analysis job
        latest_job = PreAnalysisJob.objects.order_by('-created_at').first()
        
        if not latest_job or not latest_job.subject_separated_content:
            print("❌ No pre-analysis job with separated content found")
            return
            
        print(f"📋 Using pre-analysis job: {latest_job.id}")
        
        # Analyze each subject
        analyzer = DocumentPreAnalyzer()
        
        for subject, data in latest_job.subject_separated_content.items():
            print(f"\n🧪 Analyzing {subject}...")
            
            if isinstance(data, dict):
                content = data.get('content', '')
            else:
                content = str(data)
            
            print(f"📏 Content length: {len(content)} characters")
            
            # Test question splitting
            questions = analyzer._split_into_questions(content)
            question_numbers = [int(q_num) for q_num, _ in questions if q_num.isdigit()]
            
            print(f"🔢 Questions found: {len(questions)}")
            print(f"📊 Question numbers: {sorted(set(question_numbers))}")
            
            # Expected ranges for each subject
            expected_ranges = {
                'Physics': list(range(1, 26)),      # Q1-Q25
                'Chemistry': list(range(26, 51)),   # Q26-Q50  
                'Mathematics': list(range(51, 76))  # Q51-Q75
            }
            
            expected = expected_ranges.get(subject, [])
            if expected:
                missing = set(expected) - set(question_numbers)
                extra = set(question_numbers) - set(expected)
                
                print(f"🎯 Expected range: Q{expected[0]}-Q{expected[-1]} ({len(expected)} questions)")
                
                if missing:
                    print(f"❌ Missing: {sorted(missing)}")
                if extra:
                    print(f"⚠️  Extra: {sorted(extra)}")
                    
                # Check if extra questions belong to other subjects
                if extra:
                    for other_subject, other_range in expected_ranges.items():
                        if other_subject != subject:
                            overlap = set(extra) & set(other_range)
                            if overlap:
                                print(f"🔄 Questions {sorted(overlap)} belong to {other_subject}")
            
            # Show content preview
            print(f"📝 Content preview (first 200 chars):")
            print(content[:200].replace('\n', ' '))
            print("...")
        
        print(f"\n📊 SUMMARY:")
        print(f"Expected total: 75 questions (25 per subject)")
        print(f"Current total: {sum(latest_job.subject_question_counts.values())} questions")
        print(f"Subject counts: {latest_job.subject_question_counts}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_all_subjects()