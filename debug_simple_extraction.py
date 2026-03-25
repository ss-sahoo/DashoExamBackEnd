#!/usr/bin/env python3
"""
Simple debug script to test the extraction process
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

def debug_extraction():
    """Debug the extraction process using the latest pre-analysis job"""
    print("🔍 Debugging extraction process...")
    
    try:
        # Get the latest pre-analysis job
        latest_job = PreAnalysisJob.objects.order_by('-created_at').first()
        
        if not latest_job:
            print("❌ No pre-analysis job found")
            return
            
        print(f"📋 Using pre-analysis job: {latest_job.id}")
        print(f"📄 File: {latest_job.file_name}")
        
        # Check subject separated content
        if latest_job.subject_separated_content:
            print("\n📊 Subject separated content:")
            for subject, data in latest_job.subject_separated_content.items():
                if isinstance(data, dict):
                    content_length = len(data.get('content', ''))
                    print(f"   - {subject}: {content_length} characters")
                else:
                    content_length = len(str(data))
                    print(f"   - {subject}: {content_length} characters")
        
        # Check subject question counts
        if latest_job.subject_question_counts:
            print("\n🔢 Expected question counts:")
            for subject, count in latest_job.subject_question_counts.items():
                print(f"   - {subject}: {count} questions")
        
        # Check document structure
        if latest_job.document_structure:
            print("\n🏗️ Document structure:")
            for subject, structure in latest_job.document_structure.items():
                print(f"   - {subject}:")
                if isinstance(structure, dict) and 'sections' in structure:
                    for section in structure['sections']:
                        print(f"     * {section.get('name')}: {section.get('type_hint')} ({section.get('question_range')})")
        
        # Test extraction for each subject
        from questions.services.section_question_extractor import SectionQuestionExtractor
        from django.conf import settings
        
        extractor = SectionQuestionExtractor(
            api_key=getattr(settings, 'GEMINI_API_KEY', '')
        )
        
        print("\n🧪 Testing extraction for each subject...")
        
        for subject in ['Physics', 'Chemistry', 'Mathematics']:
            print(f"\n--- Testing {subject} ---")
            
            # Get subject content
            subject_content = ""
            if latest_job.subject_separated_content:
                # Find subject content with fuzzy matching
                normalized_subj = subject.lower().strip()
                found_key = None
                for key in latest_job.subject_separated_content.keys():
                    if normalized_subj == key.lower().strip():
                        found_key = key
                        break
                
                if found_key:
                    content_data = latest_job.subject_separated_content[found_key]
                    if isinstance(content_data, dict):
                        subject_content = content_data.get('content', '')
                    else:
                        subject_content = str(content_data)
                    print(f"✓ Found content for {subject}: {len(subject_content)} characters")
                else:
                    print(f"❌ No content found for {subject}")
                    print(f"Available keys: {list(latest_job.subject_separated_content.keys())}")
                    continue
            
            # Get expected count
            expected_count = 0
            if latest_job.subject_question_counts:
                expected_count = latest_job.subject_question_counts.get(subject, 0)
            
            print(f"📊 Expected questions: {expected_count}")
            
            # Get document structure
            doc_structure = {}
            if latest_job.document_structure:
                doc_structure = latest_job.document_structure.get(subject, {})
            
            # Test question counting
            actual_count = extractor._count_questions_in_content(subject_content)
            print(f"🔢 Actual questions found in content: {actual_count}")
            
            # Show content preview
            print(f"📝 Content preview (first 300 chars):")
            print(subject_content[:300])
            print("...")
            
            if actual_count != expected_count:
                print(f"⚠️  Mismatch: Expected {expected_count}, Found {actual_count}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_extraction()