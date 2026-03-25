"""
OMR App Admin
"""
from django.contrib import admin
from .models import OMRSheet, OMRSubmission, AnswerKey


@admin.register(OMRSheet)
class OMRSheetAdmin(admin.ModelAdmin):
    list_display = ['id', 'exam', 'sheet_id', 'status', 'is_primary', 'created_at']
    list_filter = ['status', 'is_primary', 'created_at']
    search_fields = ['exam__title', 'sheet_id']
    readonly_fields = ['sheet_id', 'metadata', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('exam', 'sheet_id', 'status', 'is_primary')
        }),
        ('Files', {
            'fields': ('pdf_file',)
        }),
        ('Configuration', {
            'fields': ('candidate_fields', 'question_config', 'metadata'),
            'classes': ('collapse',)
        }),
        ('Errors', {
            'fields': ('generation_error',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(OMRSubmission)
class OMRSubmissionAdmin(admin.ModelAdmin):
    list_display = ['id', 'student', 'omr_sheet', 'status', 'score', 'max_score', 'percentage', 'submitted_at']
    list_filter = ['status', 'submitted_at', 'evaluated_at']
    search_fields = ['student__email', 'student__first_name', 'omr_sheet__exam__title']
    readonly_fields = [
        'extracted_responses', 'candidate_info', 'evaluation_results',
        'score', 'max_score', 'percentage', 'submitted_at', 'evaluated_at'
    ]
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('omr_sheet', 'student', 'attempt', 'status')
        }),
        ('Files', {
            'fields': ('scanned_files', 'annotated_pdf', 'results_json')
        }),
        ('Results', {
            'fields': ('score', 'max_score', 'percentage', 'candidate_info', 'evaluation_results'),
            'classes': ('collapse',)
        }),
        ('Raw Data', {
            'fields': ('extracted_responses',),
            'classes': ('collapse',)
        }),
        ('Errors', {
            'fields': ('evaluation_error',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('submitted_at', 'evaluated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(AnswerKey)
class AnswerKeyAdmin(admin.ModelAdmin):
    list_display = ['id', 'exam', 'created_by', 'created_at', 'updated_at']
    list_filter = ['created_at']
    search_fields = ['exam__title']
    readonly_fields = ['created_at', 'updated_at']
