#!/usr/bin/env python3
"""
Debug script to analyze why not all questions are being extracted
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

from questions.services.section_question_extractor import SectionQuestionExtractor
from questions.services.gemini_extraction_v2 import GeminiExtractionServiceV2

def analyze_extraction_issue():
    """Analyze why not all questions are being extracted"""
    print("🔍 Analyzing extraction issue...")
    
    # Path to the input PDF
    pdf_path = "/Users/shradha/Exam_app/Exam_Frontendnextjs/input.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"❌ PDF file not found: {pdf_path}")
        return
    
    try:
        # Initialize the extractor
        extractor = SectionQuestionExtractor()
        
        # Extract text content from PDF
        print("📄 Extracting text from PDF...")
        gemini_service = GeminiExtractionServiceV2()
        # Use a simpler method to get text content
        with open(pdf_path, 'rb') as f:
            # For now, let's use the extractor's method to get content
            pass
        
        print(f"📊 Total text content length: {len(text_content)} characters")
        
        # Detect subjects
        print("🔍 Detecting subjects...")
        subjects = extractor.detect_subjects(text_content)
        print(f"📋 Detected subjects: {subjects}")
        
        # Analyze each subject
        for subject in subjects:
            print(f"\n🧪 Analyzing {subject}...")
            
            # Get subject-specific content
            subject_content = extractor._get_subject_content(text_content, subject)
            print(f"📏 {subject} content length: {len(subject_content)} characters")
            
            # Count questions in content
            question_count = extractor._count_questions_in_content(subject_content)
            print(f"🔢 Expected {subject} questions: {question_count}")
            
            # Check document structure detection
            doc_structure = extractor._detect_document_structure(subject_content, subject)
            print(f"🏗️ {subject} document structure:")
            if doc_structure and doc_structure.get('sections'):
                for section in doc_structure['sections']:
                    print(f"   - {section.get('name')}: {section.get('type_hint')} ({section.get('question_range')})")
            else:
                print("   - No structure detected")
            
            # Show content preview
            print(f"📝 {subject} content preview (first 500 chars):")
            print(subject_content[:500])
            print("...")
            
        print("\n🎯 EXPECTED PATTERN:")
        print("- Physics: 25 questions (20 MCQ + 5 numerical)")
        print("- Chemistry: 25 questions (20 MCQ + 5 numerical)")  
        print("- Mathematics: 25 questions (20 MCQ + 5 numerical)")
        print("- Total: 75 questions")
        
        print("\n🔍 CURRENT RESULTS:")
        print("- Physics: 34 questions")
        print("- Chemistry: 30 questions")
        print("- Mathematics: 8 questions")
        print("- Total: 72 questions")
        
        print("\n❌ ISSUES IDENTIFIED:")
        print("1. Mathematics severely under-extracted (8 vs 25)")
        print("2. Physics over-extracted (34 vs 25)")
        print("3. Chemistry slightly over-extracted (30 vs 25)")
        print("4. Total count incorrect (72 vs 75)")
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_extraction_issue()