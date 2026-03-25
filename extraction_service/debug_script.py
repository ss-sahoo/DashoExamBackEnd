
import os
import sys
import logging
from dotenv import load_dotenv

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Load env before imports
load_dotenv()

from core.services.mathpix import mathpix_service
from core.services.chunker import chunker
from core.services.gemini import gemini_service
from core.config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_extraction")

def debug_flow(file_path):
    print(f"\n--- Debugging Extraction Flow for {file_path} ---")
    
    # Step 1: Mathpix Extraction
    print("\n[Step 1] Testing Mathpix extraction...")
    try:
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return
            
        text = mathpix_service.extract_pdf(file_path)
        print(f"Mathpix extracted {len(text)} characters.")
        print(f"First 500 chars:\n{text[:500]}...")
        
        if len(text) < 100:
            print("WARNING: Extracted text is very short!")
    except Exception as e:
        print(f"ERROR in Mathpix: {e}")
        return

    # Step 2: Chunking
    print("\n[Step 2] Testing Chunker...")
    try:
        chunks = chunker.chunk(text, expected_count=75)
        print(f"Created {len(chunks)} chunks.")
        for i, chunk in enumerate(chunks):
            print(f"  Chunk {i+1}: {len(chunk.text)} chars (Q{chunk.start_q}-Q{chunk.end_q})")
            if i == 0:
                print(f"  First chunk preview:\n{chunk.text[:200]}...")
    except Exception as e:
        print(f"ERROR in Chunker: {e}")
        return

    # Step 3: Gemini Extraction (First chunk only)
    print("\n[Step 3] Testing Gemini on FIRST chunk only...")
    try:
        if chunks:
            first_chunk = chunks[0]
            context = {
                "chunk_idx": 0,
                "total_chunks": len(chunks),
                "pattern_id": "debug",
                "expected_count": 75,
                "subjects": ["Physics", "Chemistry", "Maths"]
            }
            questions = gemini_service.extract_chunk(first_chunk.text, context)
            print(f"Gemini extracted {len(questions)} questions from the first chunk.")
            if questions:
                print(f"Sample Question 1:\n{questions[0]}")
            else:
                print("Gemini returned NO questions.")
                print("Checking raw response...")
                # We can't easily check raw response here as method returns parsed object
                # But empty list means parsing failed or model returned nothing
    except Exception as e:
        print(f"ERROR in Gemini: {e}")

if __name__ == "__main__":
    # Point to the file identified in previous step
    # Note: Using absolute path from previous find_by_name result
    # We need to find where exactly 'extraction_uploads' is relative to execution
    # Based on previous ls, it's in exam_flow_backend/extraction_uploads
    
    # Path construction
    base_path = "/home/tushar/Pictures/exam_flow_diracai/exam_flow_backend/extraction_uploads"
    # Pick the latest file
    filename = "v2_1770888756.883051_Exam Pattern PDF - Replit.pdf"
    full_path = os.path.join(base_path, filename)
    
    debug_flow(full_path)
