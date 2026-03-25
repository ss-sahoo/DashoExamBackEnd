"""
OMR App URLs
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'sheets', views.OMRSheetViewSet, basename='omr-sheets')
router.register(r'submissions', views.OMRSubmissionViewSet, basename='omr-submissions')
router.register(r'answer-keys', views.AnswerKeyViewSet, basename='answer-keys')

urlpatterns = [
    path('', include(router.urls)),
    path('exam/<int:exam_id>/status/', views.exam_omr_status, name='exam-omr-status'),
]
