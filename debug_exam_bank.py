
import os
import django
import sys

# Setup Django
sys.path.append('/home/diracai/Desktop/dasho2.0/Exam_backendDjango')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from exams.models import Exam
from questions.models import ExamQuestion
from exams.ai_evaluation_service import AIEvaluationService

def debug_exam_questions(exam_id):
    try:
        exam = Exam.objects.get(id=exam_id)
        print(f"Exam: {exam.title} (ID: {exam_id})")
        
        direct_questions = exam.questions.all().order_by('question_number')
        print(f"Direct questions found (via Question.exam): {direct_questions.count()}")
        for q in direct_questions:
            print(f"  QID: {q.id}, QNumber: {q.question_number}, Marks: {q.marks}, NegMarks: {q.negative_marks}, Text: {q.question_text[:30]}...")
            
        mappings = ExamQuestion.objects.filter(exam=exam).order_by('question_number')
        print(f"Total mappings found: {mappings.count()}")
        
        for m in mappings:
            print(f"  QIndex: {m.question_number}, QID: {m.question.id}, Text: {m.question.question_text[:50]}...")
            
        service = AIEvaluationService(exam_id)
        bank = service.question_bank
        print(f"\nQuestion Bank (from service):")
        for q in bank:
            print(f"  Q.No.: {q['Q.No.']}, Question: {q['Question'][:50]}...")
            if 'parts' in q:
                for p in q['parts']:
                    print(f"    Part: {p['part.No.']}, Text: {p['Question'][:30]}...")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_exam_questions(27)
