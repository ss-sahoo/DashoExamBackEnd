from django.urls import path
from . import views

urlpatterns = [
    # Subjects
    path('subjects/', views.SubjectListView.as_view(), name='subject-list'),
    path('subjects/<int:pk>/', views.SubjectDetailView.as_view(), name='subject-detail'),
    
    # Exam patterns
    path('patterns/', views.ExamPatternListView.as_view(), name='pattern-list'),
    path('patterns/<int:pk>/', views.ExamPatternDetailView.as_view(), name='pattern-detail'),
    path('patterns/<int:pattern_id>/validate/', views.pattern_validation, name='pattern-validation'),
    
    # Pattern sections
    path('patterns/<int:pattern_id>/sections/', views.PatternSectionListView.as_view(), name='pattern-section-list'),
    path('patterns/<int:pattern_id>/sections/<int:pk>/', views.PatternSectionDetailView.as_view(), name='pattern-section-detail'),
    
    # Templates
    path('templates/', views.PatternTemplateListView.as_view(), name='pattern-template-list'),
    path('templates/<int:template_id>/create-pattern/', views.create_pattern_from_template, name='create-pattern-from-template'),
    
    # Pattern question assignment
    path('patterns/<int:pattern_id>/questions/', views.get_pattern_questions, name='pattern-questions'),
    path('assign-pattern-questions/', views.assign_pattern_questions_to_exam, name='assign-pattern-questions'),
]
