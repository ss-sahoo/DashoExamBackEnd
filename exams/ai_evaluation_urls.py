"""
AI Evaluation URL Configuration
"""
from django.urls import path
from . import ai_evaluation_views

urlpatterns = [
    # Answer sheet upload and evaluation
    path(
        '<int:exam_id>/upload-answer-sheet/',
        ai_evaluation_views.upload_answer_sheet,
        name='upload-answer-sheet'
    ),
    path(
        '<int:exam_id>/evaluate-answer-sheet/',
        ai_evaluation_views.evaluate_answer_sheet,
        name='evaluate-answer-sheet'
    ),
    path(
        '<int:exam_id>/ai-evaluation-status/',
        ai_evaluation_views.ai_evaluation_status,
        name='ai-evaluation-status'
    ),
    path(
        '<int:exam_id>/submissions/',
        ai_evaluation_views.list_submissions,
        name='list-submissions'
    ),
    path(
        '<int:exam_id>/submissions/<int:attempt_id>/update-mark/',
        ai_evaluation_views.update_submission_mark,
        name='update-submission-mark'
    ),
    
    # Testing endpoint
    path(
        'test-ai-evaluation/',
        ai_evaluation_views.test_ai_evaluation,
        name='test-ai-evaluation'
    ),
]
