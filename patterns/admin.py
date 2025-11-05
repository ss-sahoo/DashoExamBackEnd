from django.contrib import admin
from .models import ExamPattern, PatternSection, PatternTemplate


class PatternSectionInline(admin.TabularInline):
    model = PatternSection
    extra = 0
    ordering = ['order', 'start_question']


@admin.register(ExamPattern)
class ExamPatternAdmin(admin.ModelAdmin):
    list_display = ['name', 'institute', 'total_questions', 'total_duration', 'total_marks', 'is_active', 'created_at']
    list_filter = ['institute', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [PatternSectionInline]


@admin.register(PatternSection)
class PatternSectionAdmin(admin.ModelAdmin):
    list_display = ['name', 'pattern', 'subject', 'question_type', 'start_question', 'end_question', 'marks_per_question']
    list_filter = ['question_type', 'pattern__institute', 'is_compulsory']
    search_fields = ['name', 'subject', 'pattern__name']
    ordering = ['pattern', 'order', 'start_question']


@admin.register(PatternTemplate)
class PatternTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'total_questions', 'total_duration', 'total_marks', 'is_public', 'created_at']
    list_filter = ['category', 'is_public', 'created_at']
    search_fields = ['name', 'description', 'category']