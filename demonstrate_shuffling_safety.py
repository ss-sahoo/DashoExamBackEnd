#!/usr/bin/env python3
"""
Demonstration that question/option shuffling is SAFE for answer evaluation.

This script shows the key concept without needing database setup:
- Answers are stored and compared by TEXT CONTENT, not position
- Shuffling only affects visual order, not evaluation logic
"""

import random
import hashlib

def demonstrate_shuffling_safety():
    """Demonstrate that shuffling doesn't break answer evaluation"""
    
    print("🚀 Demonstrating Shuffling Safety")
    print("=" * 50)
    
    # Original question with options
    original_question = {
        'id': 1,
        'question_text': 'What is the capital of France?',
        'options': ['London', 'Berlin', 'Paris', 'Madrid'],
        'correct_answer': 'Paris',  # ← Text-based, not index-based
        'question_type': 'single_mcq'
    }
    
    print("📋 Original Question:")
    print(f"   Text: {original_question['question_text']}")
    print(f"   Options: {original_question['options']}")
    print(f"   Correct Answer: {original_question['correct_answer']}")
    
    # Simulate shuffling for different students
    students = ['Alice', 'Bob', 'Charlie']
    
    for student in students:
        print(f"\n👤 Student: {student}")
        
        # Generate deterministic seed for this student
        seed_source = f"exam_1_user_{student}"
        seed_hex = hashlib.sha256(seed_source.encode()).hexdigest()
        seed = int(seed_hex[:8], 16)
        rng = random.Random(seed)
        
        # Shuffle options for this student
        shuffled_options = original_question['options'].copy()
        rng.shuffle(shuffled_options)
        
        print(f"   Shuffled Options: {shuffled_options}")
        
        # Student selects the correct answer by TEXT (not position)
        student_answer = 'Paris'  # Student clicks on "Paris" regardless of position
        
        print(f"   Student Selected: {student_answer}")
        
        # Backend evaluation (text-based comparison)
        is_correct = student_answer.lower().strip() == original_question['correct_answer'].lower().strip()
        
        print(f"   Evaluation: {student_answer} == {original_question['correct_answer']} → {is_correct}")
        print(f"   Result: {'✅ CORRECT' if is_correct else '❌ WRONG'}")
    
    print(f"\n🎯 Key Insight:")
    print(f"   • All students see different option orders")
    print(f"   • All students select 'Paris' (by text content)")
    print(f"   • All students get marked correct")
    print(f"   • Position doesn't matter, only text content!")

def demonstrate_multiple_choice():
    """Demonstrate multiple choice with shuffling"""
    
    print(f"\n🔢 Multiple Choice Example")
    print("=" * 30)
    
    question = {
        'question_text': 'Which are prime numbers?',
        'options': ['2', '3', '4', '5'],
        'correct_answer': '2|3|5',  # Pipe-separated text
        'question_type': 'multiple_mcq'
    }
    
    print(f"📋 Question: {question['question_text']}")
    print(f"   Original Options: {question['options']}")
    print(f"   Correct Answer: {question['correct_answer']}")
    
    # Shuffle options
    shuffled_options = ['5', '2', '4', '3']  # Different order
    print(f"   Shuffled Options: {shuffled_options}")
    
    # Student selects correct answers by text
    student_selections = ['2', '3', '5']  # Text content, not positions
    student_answer = '|'.join(student_selections)
    
    print(f"   Student Selected: {student_answer}")
    
    # Backend evaluation (set comparison)
    correct_set = set(question['correct_answer'].split('|'))
    student_set = set(student_answer.split('|'))
    is_correct = correct_set == student_set
    
    print(f"   Correct Set: {correct_set}")
    print(f"   Student Set: {student_set}")
    print(f"   Sets Match: {is_correct}")
    print(f"   Result: {'✅ CORRECT' if is_correct else '❌ WRONG'}")

def demonstrate_wrong_approach():
    """Show what would happen with position-based answers (WRONG approach)"""
    
    print(f"\n❌ Wrong Approach (Position-Based)")
    print("=" * 35)
    
    original_options = ['London', 'Berlin', 'Paris', 'Madrid']
    correct_position = 2  # Paris is at index 2
    
    print(f"   Original Options: {original_options}")
    print(f"   Correct Position: {correct_position} (Paris)")
    
    # After shuffling
    shuffled_options = ['Paris', 'Madrid', 'London', 'Berlin']
    print(f"   Shuffled Options: {shuffled_options}")
    
    # If we used position-based evaluation (WRONG!)
    if len(shuffled_options) > correct_position:
        wrong_answer = shuffled_options[correct_position]  # Would be 'London'!
        print(f"   Position {correct_position} now contains: {wrong_answer}")
        print(f"   This would be WRONG! ❌")
    
    print(f"\n   Why position-based is broken:")
    print(f"   • Original: Position 2 = 'Paris' ✅")
    print(f"   • Shuffled: Position 2 = 'London' ❌")
    print(f"   • Student who selected 'Paris' would be marked wrong!")

def demonstrate_current_system():
    """Show how the current system works correctly"""
    
    print(f"\n✅ Current System (Text-Based)")
    print("=" * 32)
    
    print(f"   Frontend stores: answer = 'Paris' (text content)")
    print(f"   Backend compares: 'Paris' == 'Paris' → True")
    print(f"   Result: ✅ CORRECT regardless of shuffle order")
    
    print(f"\n   How it works:")
    print(f"   1. Question stores correct_answer = 'Paris' (text)")
    print(f"   2. Frontend shuffles options visually")
    print(f"   3. Student clicks on 'Paris' option")
    print(f"   4. Frontend stores answer = 'Paris' (text)")
    print(f"   5. Backend compares text: 'Paris' == 'Paris'")
    print(f"   6. Evaluation: ✅ CORRECT")

def main():
    """Run all demonstrations"""
    
    demonstrate_shuffling_safety()
    demonstrate_multiple_choice()
    demonstrate_wrong_approach()
    demonstrate_current_system()
    
    print(f"\n🎉 CONCLUSION")
    print("=" * 15)
    print(f"✅ The current exam system is SAFE for shuffling!")
    print(f"✅ Answers are stored by TEXT CONTENT, not position")
    print(f"✅ Evaluation compares TEXT CONTENT, not indices")
    print(f"✅ Shuffling only affects visual presentation")
    print(f"✅ Students get correct scores regardless of shuffle order")
    
    print(f"\n🔑 Key Technical Points:")
    print(f"   • Frontend: value={{optionText}} (actual text)")
    print(f"   • Storage: answer = 'Paris' (text content)")
    print(f"   • Evaluation: 'Paris' == 'Paris' (text comparison)")
    print(f"   • Result: Position-independent evaluation ✅")

if __name__ == "__main__":
    main()