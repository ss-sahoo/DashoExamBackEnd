#!/usr/bin/env python3
"""
Debug script to understand the PDF content structure
"""

import os
import sys
import django
from pathlib import Path

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from questions.services.agent_extraction_service import AgentExtractionService
import re

def debug_content():
    """Debug the PDF content to understand structure"""
    
    print("Debugging PDF content structure...")
    
    # Initialize the service
    service = AgentExtractionService(
        gemini_key='AIzaSyDlR87K380gV1uTpenEHufhTOYzjZUr52k'
    )
    
    # Get the raw OCR content
    content = service._fallback_local_parsing('/Users/shradha/Exam_app/Exam_Frontendnextjs/input.pdf')
    
    print(f"Total content length: {len(content)}")
    
    # Look for question 48 specifically
    q48_pattern = r'48\..*?(?=49\.|$)'
    q48_match = re.search(q48_pattern, content, re.DOTALL)
    
    if q48_match:
        q48_content = q48_match.group(0)
        print(f"\nFound Question 48:")
        print(f"Length: {len(q48_content)}")
        print(f"Content: {q48_content[:500]}...")
        
        # Check for subparts
        subparts = re.findall(r'\n\s*([1-5])\.\s*([^\n]+)', q48_content)
        print(f"Found {len(subparts)} subparts:")
        for i, (num, text) in enumerate(subparts):
            print(f"  {num}. {text[:60]}...")
    else:
        print("Question 48 not found!")
    
    # Look for questions 46-50
    print(f"\nLooking for questions 46-50:")
    for q_num in [46, 47, 48, 49, 50]:
        pattern = rf'{q_num}\..*?(?={q_num+1}\.|$)'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            q_content = match.group(0)
            print(f"Q{q_num}: Found ({len(q_content)} chars) - {q_content[:80]}...")
        else:
            print(f"Q{q_num}: NOT FOUND")
    
    # Look for subject sections
    print(f"\nLooking for subject indicators:")
    chemistry_indicators = ['chemistry', 'chemical', 'galvanic', 'cell', 'electrode', 'salt bridge']
    physics_indicators = ['physics', 'charge', 'electric', 'magnetic', 'force']
    
    for indicator in chemistry_indicators:
        matches = len(re.findall(indicator, content, re.IGNORECASE))
        print(f"'{indicator}': {matches} matches")
    
    print(f"\nPhysics indicators:")
    for indicator in physics_indicators:
        matches = len(re.findall(indicator, content, re.IGNORECASE))
        print(f"'{indicator}': {matches} matches")
    
    # Show content around question 48
    q48_pos = content.find('48.')
    if q48_pos != -1:
        print(f"\nContent around question 48 (position {q48_pos}):")
        start = max(0, q48_pos - 200)
        end = min(len(content), q48_pos + 1000)
        print(content[start:end])
    
    # Check for section headers
    section_pattern = r'(?:^|\n)\s*(SECTION\s+[A-Z]|Part\s+[A-Z]|Chemistry|Physics)'
    sections = re.findall(section_pattern, content, re.IGNORECASE | re.MULTILINE)
    print(f"\nFound sections: {sections}")

if __name__ == "__main__":
    debug_content()