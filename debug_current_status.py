#!/usr/bin/env python3
"""
Debug script to check the current extraction status
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

from questions.models import PreAnalysisJob, ExtractionJob, ExtractedQuestion

def debug_current_status():
    """Debug the current extraction status"""
    print("🔍 Debugging current extraction status...")
    
    try:
        # Get the latest pre-analysis job
        latest_pre_job = PreAnalysisJob.objects.order_by('-created_at').first()
        
        if latest_pre_job:
            print(f"📋 Latest pre-analysis job: {latest_pre_job.id}")
            print(f"   File: {latest_pre_job.file_name}")
            print(f"   Status: {latest_pre_job.status}")
            print(f"   Created: {latest_pre_job.created_at}")
            
            if latest_pre_job.subject_question_counts:
                print(f"   Subject counts: {latest_pre_job.subject_question_counts}")
                total_expected = sum(latest_pre_job.subject_question_counts.values())
                print(f"   Total expected: {total_expected}")
        
        # Get the latest extraction job
        latest_extraction_job = ExtractionJob.objects.order_by('-created_at').first()
        
        if latest_extraction_job:
            print(f"\n📤 Latest extraction job: {latest_extraction_job.id}")
            print(f"   Status: {latest_extraction_job.status}")
            print(f"   Questions extracted: {latest_extraction_job.questions_extracted}")
            print(f"   Created: {latest_extraction_job.created_at}")
            
            # Count actual extracted questions
            extracted_questions = ExtractedQuestion.objects.filter(job=latest_extraction_job)
            actual_count = extracted_questions.count()
            print(f"   Actual questions in DB: {actual_count}")
            
            # Count by subject
            subjects = extracted_questions.values_list('suggested_subject', flat=True).distinct()
            print(f"   Subjects found: {list(subjects)}")
            
            for subject in subjects:
                count = extracted_questions.filter(suggested_subject=subject).count()
                print(f"      {subject}: {count} questions")
        
        # Check if there are any recent extraction jobs
        recent_jobs = ExtractionJob.objects.order_by('-created_at')[:5]
        print(f"\n📊 Recent extraction jobs:")
        for job in recent_jobs:
            questions_count = ExtractedQuestion.objects.filter(job=job).count()
            print(f"   {job.id}: {questions_count} questions, status: {job.status}")
        
        print(f"\n🎯 EXPECTED vs ACTUAL:")
        print(f"   Expected total: 75 questions (25 per subject)")
        if latest_extraction_job:
            actual_total = ExtractedQuestion.objects.filter(job=latest_extraction_job).count()
            print(f"   Actual total: {actual_total} questions")
            
            if actual_total < 75:
                missing = 75 - actual_total
                print(f"   ❌ Missing: {missing} questions")
                
                # Check which subjects are under-extracted
                for subject in ['Physics', 'Chemistry', 'Mathematics']:
                    count = ExtractedQuestion.objects.filter(
                        job=latest_extraction_job, 
                        suggested_subject=subject
                    ).count()
                    expected = 25
                    if count < expected:
                        print(f"      {subject}: {count}/{expected} (missing {expected-count})")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_current_status()