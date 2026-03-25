from django.urls import path
from . import student_analytics_views

urlpatterns = [
    path('overview/', student_analytics_views.student_analytics_overview, name='student_analytics_overview'),
    path('exam/<int:exam_id>/', student_analytics_views.student_exam_analytics, name='student_exam_analytics'),
    path('trends/', student_analytics_views.student_performance_trends, name='student_performance_trends'),
    path('weak-areas/', student_analytics_views.student_weak_areas, name='student_weak_areas'),
    path('achievements/', student_analytics_views.student_achievements, name='student_achievements'),
]
