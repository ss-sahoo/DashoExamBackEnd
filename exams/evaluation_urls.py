from django.urls import path
from . import evaluation_views

urlpatterns = [
    # Evaluation System URLs
    path('exams/<int:exam_id>/progress/', evaluation_views.get_evaluation_progress, name='get-evaluation-progress'),
    path('exams/<int:exam_id>/pending/', evaluation_views.get_pending_evaluations, name='get-pending-evaluations'),
    path('exams/<int:exam_id>/settings/', evaluation_views.update_evaluation_settings, name='update-evaluation-settings'),
    path('exams/<int:exam_id>/batch-ai/', evaluation_views.batch_ai_evaluate, name='batch-ai-evaluate'),
    path('attempts/<int:attempt_id>/evaluate/', evaluation_views.evaluate_exam_attempt, name='evaluate-exam-attempt'),
    path('attempts/<int:attempt_id>/questions/', evaluation_views.get_question_evaluations, name='get-question-evaluations'),
    path('questions/<int:evaluation_id>/manual/', evaluation_views.manual_evaluate_question, name='manual-evaluate-question'),
    path('questions/<int:evaluation_id>/ai/', evaluation_views.ai_evaluate_question, name='ai-evaluate-question'),
    path('exams/<int:exam_id>/batches/', evaluation_views.get_evaluation_batches, name='get-evaluation-batches'),
]
