
import os
import sys
import logging
import re
from dotenv import load_dotenv

# Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Load env before imports
load_dotenv()

from core.services.mathpix import mathpix_service

def inspect_text(file_path):
    print(f"\n--- Inspecting Text for {file_path} ---")
    try:
        text = mathpix_service.extract_pdf(file_path)
        print(f"Total length: {len(text)} chars")
        
        # Look for question-like patterns
        print("\n[Regex Search] Looking for question patterns...")
        patterns = [
            r'(?m)^\s*(\d+)\.\s+',        # 1. 
            r'(?m)^\s*Q\s*(\d+)',         # Q1 or Q 1
            r'(?m)^\s*Question\s*(\d+)',  # Question 1
            r'(?m)^\s*(\d+)\)',           # 1)
        ]
        
        for p in patterns:
            matches = list(re.finditer(p, text))
            print(f"Pattern '{p}': Found {len(matches)} matches")
            if matches:
                print(f"  First 3 matches at indices: {[m.start() for m in matches[:3]]}")

        # Find the first occurrence of a number followed by a dot at start of line
        first_q = re.search(r'(?m)^\s*(\d+)\.\s+', text)
        if first_q:
            start = max(0, first_q.start() - 100)
            end = min(len(text), first_q.end() + 1000)
            print(f"\n[Context around first match]:\n{text[start:end]}\n")
        else:
            print("\nCould not find '1.' type pattern. Printing middle of text:")
            mid = len(text) // 2
            print(text[mid:mid+1000])

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    base_path = "/home/tushar/Pictures/exam_flow_diracai/exam_flow_backend/extraction_uploads"
    filename = "v2_1770888756.883051_Exam Pattern PDF - Replit.pdf"
    full_path = os.path.join(base_path, filename)
    inspect_text(full_path)
