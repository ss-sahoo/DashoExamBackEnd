from django.contrib import admin
from .models import Question, QuestionBank, ExamQuestion, QuestionImage, QuestionComment, QuestionTemplate


class QuestionImageInline(admin.TabularInline):
    model = QuestionImage
    extra = 0


class QuestionCommentInline(admin.TabularInline):
    model = QuestionComment
    extra = 0
    readonly_fields = ['created_at']


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'question_text_short', 'question_type', 'difficulty', 'subject', 'marks', 'is_verified', 'created_by', 'created_at']
    list_filter = ['question_type', 'difficulty', 'subject', 'is_verified', 'is_active', 'institute', 'created_at']
    search_fields = ['question_text', 'subject', 'topic', 'created_by__email']
    readonly_fields = ['usage_count', 'success_rate', 'created_at', 'updated_at']
    inlines = [QuestionImageInline, QuestionCommentInline]
    
    def question_text_short(self, obj):
        return obj.question_text[:50] + "..." if len(obj.question_text) > 50 else obj.question_text
    question_text_short.short_description = 'Question Text'


@admin.register(QuestionBank)
class QuestionBankAdmin(admin.ModelAdmin):
    list_display = ['name', 'institute', 'is_public', 'created_by', 'created_at']
    list_filter = ['is_public', 'institute', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ExamQuestion)
class ExamQuestionAdmin(admin.ModelAdmin):
    list_display = ['exam', 'question_number', 'question_short', 'section_name', 'marks']
    list_filter = ['section_name', 'exam__institute']
    search_fields = ['exam__title', 'question__question_text']
    ordering = ['exam', 'question_number']
    
    def question_short(self, obj):
        return obj.question.question_text[:30] + "..." if len(obj.question.question_text) > 30 else obj.question.question_text
    question_short.short_description = 'Question'


@admin.register(QuestionImage)
class QuestionImageAdmin(admin.ModelAdmin):
    list_display = ['question', 'caption', 'order', 'created_at']
    list_filter = ['created_at']
    search_fields = ['question__question_text', 'caption']


@admin.register(QuestionComment)
class QuestionCommentAdmin(admin.ModelAdmin):
    list_display = ['question', 'user', 'is_review', 'rating', 'created_at']
    list_filter = ['is_review', 'rating', 'created_at']
    search_fields = ['question__question_text', 'user__email', 'comment']
    readonly_fields = ['created_at']


@admin.register(QuestionTemplate)
class QuestionTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'question_type', 'is_public', 'created_by', 'created_at']
    list_filter = ['question_type', 'is_public', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']