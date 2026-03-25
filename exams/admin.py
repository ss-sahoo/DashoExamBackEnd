from django.contrib import admin
from .models import Exam, ExamAttempt, ExamResult, ExamInvitation, ExamAnalytics, QuestionAnalytics


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['title', 'institute', 'status', 'start_date', 'end_date', 'duration_minutes', 'created_by', 'created_at']
    list_filter = ['status', 'institute', 'is_public', 'created_at']
    search_fields = ['title', 'description']
    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ['allowed_users']


@admin.register(ExamAttempt)
class ExamAttemptAdmin(admin.ModelAdmin):
    list_display = ['student', 'exam', 'attempt_number', 'status', 'score', 'percentage', 'started_at', 'submitted_at']
    list_filter = ['status', 'exam__institute', 'started_at', 'submitted_at']
    search_fields = ['student__email', 'exam__title']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ['attempt', 'total_questions_attempted', 'total_correct_answers', 'total_wrong_answers', 'created_at']
    list_filter = ['created_at']
    search_fields = ['attempt__student__email', 'attempt__exam__title']
    readonly_fields = ['created_at']


@admin.register(ExamInvitation)
class ExamInvitationAdmin(admin.ModelAdmin):
    list_display = ['user', 'exam', 'invited_by', 'is_accepted', 'invited_at', 'accepted_at']
    list_filter = ['is_accepted', 'invited_at', 'accepted_at']
    search_fields = ['user__email', 'exam__title']
    readonly_fields = ['invited_at']


@admin.register(ExamAnalytics)
class ExamAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['exam', 'total_invited', 'total_started', 'total_completed', 'completion_rate', 'average_score', 'last_updated']
    list_filter = ['last_updated']
    search_fields = ['exam__title']
    readonly_fields = ['last_updated']


@admin.register(QuestionAnalytics)
class QuestionAnalyticsAdmin(admin.ModelAdmin):
    list_display = ['exam', 'question_number', 'total_attempts', 'correct_attempts', 'success_rate', 'difficulty_level']
    list_filter = ['difficulty_level', 'exam__institute']
    search_fields = ['exam__title', 'question_text']
    readonly_fields = ['created_at', 'updated_at']