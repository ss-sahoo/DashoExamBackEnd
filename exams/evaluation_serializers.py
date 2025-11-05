from rest_framework import serializers
from .evaluation_models import (
    QuestionEvaluation, 
    EvaluationBatch, 
    EvaluationSettings, 
    EvaluationProgress,
    EvaluationRubric
)
from questions.serializers import QuestionSerializer


class QuestionEvaluationSerializer(serializers.ModelSerializer):
    """Serializer for QuestionEvaluation model"""
    
    question = QuestionSerializer(read_only=True)
    question_id = serializers.IntegerField(write_only=True)
    evaluated_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = QuestionEvaluation
        fields = [
            'id', 'attempt', 'question', 'question_id', 'question_number',
            'student_answer', 'is_answered', 'evaluation_type', 'evaluation_status',
            'marks_obtained', 'max_marks', 'is_correct', 'evaluated_by', 'evaluated_by_name',
            'evaluated_at', 'evaluation_notes', 'ai_confidence_score', 'ai_feedback',
            'manual_feedback', 'requires_review', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_evaluated_by_name(self, obj):
        if obj.evaluated_by:
            return obj.evaluated_by.get_full_name()
        return None


class EvaluationBatchSerializer(serializers.ModelSerializer):
    """Serializer for EvaluationBatch model"""
    
    processed_by_name = serializers.SerializerMethodField()
    exam_title = serializers.SerializerMethodField()
    
    class Meta:
        model = EvaluationBatch
        fields = [
            'id', 'exam', 'exam_title', 'batch_type', 'status', 'questions_count',
            'evaluated_count', 'failed_count', 'started_at', 'completed_at',
            'processed_by', 'processed_by_name', 'ai_model_used', 'ai_processing_time',
            'error_message', 'retry_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_processed_by_name(self, obj):
        if obj.processed_by:
            return obj.processed_by.get_full_name()
        return None
    
    def get_exam_title(self, obj):
        return obj.exam.title


class EvaluationSettingsSerializer(serializers.ModelSerializer):
    """Serializer for EvaluationSettings model"""
    
    class Meta:
        model = EvaluationSettings
        fields = [
            'id', 'exam', 'enable_auto_evaluation', 'auto_evaluate_mcq',
            'auto_evaluate_numerical', 'auto_evaluate_true_false', 'auto_evaluate_fill_blank',
            'enable_manual_evaluation', 'require_manual_review', 'manual_evaluation_deadline',
            'enable_ai_evaluation', 'ai_model_preference', 'ai_confidence_threshold',
            'ai_fallback_to_manual', 'enable_mixed_evaluation', 'auto_first_then_manual',
            'ai_first_then_manual', 'notify_evaluators', 'notify_students_on_completion',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class EvaluationProgressSerializer(serializers.ModelSerializer):
    """Serializer for EvaluationProgress model"""
    
    completion_percentage = serializers.ReadOnlyField()
    
    class Meta:
        model = EvaluationProgress
        fields = [
            'id', 'exam', 'total_questions', 'auto_evaluated', 'manually_evaluated',
            'ai_evaluated', 'pending_evaluation', 'is_fully_evaluated',
            'evaluation_completed_at', 'average_auto_confidence', 'manual_evaluation_time',
            'ai_evaluation_time', 'completion_percentage', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class EvaluationRubricSerializer(serializers.ModelSerializer):
    """Serializer for EvaluationRubric model"""
    
    created_by_name = serializers.SerializerMethodField()
    question_text = serializers.SerializerMethodField()
    
    class Meta:
        model = EvaluationRubric
        fields = [
            'id', 'question', 'exam', 'rubric_name', 'description', 'max_marks',
            'criteria', 'is_active', 'created_by', 'created_by_name', 'question_text',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name()
        return None
    
    def get_question_text(self, obj):
        return obj.question.question_text


class ManualEvaluationRequestSerializer(serializers.Serializer):
    """Serializer for manual evaluation requests"""
    
    marks_obtained = serializers.DecimalField(max_digits=5, decimal_places=2)
    is_correct = serializers.BooleanField()
    feedback = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    
    def validate_marks_obtained(self, value):
        if value < 0:
            raise serializers.ValidationError("Marks cannot be negative")
        return value


class AIEvaluationRequestSerializer(serializers.Serializer):
    """Serializer for AI evaluation requests"""
    
    force_evaluation = serializers.BooleanField(default=False)
    ai_model = serializers.CharField(max_length=50, required=False)
    confidence_threshold = serializers.DecimalField(
        max_digits=3, decimal_places=2, required=False,
        min_value=0, max_value=1
    )


class BatchEvaluationRequestSerializer(serializers.Serializer):
    """Serializer for batch evaluation requests"""
    
    evaluation_type = serializers.ChoiceField(choices=['manual', 'ai'])
    question_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False
    )
    force_evaluation = serializers.BooleanField(default=False)


class EvaluationSummarySerializer(serializers.Serializer):
    """Serializer for evaluation summary"""
    
    total_questions = serializers.IntegerField()
    auto_evaluated = serializers.IntegerField()
    manually_evaluated = serializers.IntegerField()
    ai_evaluated = serializers.IntegerField()
    pending_evaluation = serializers.IntegerField()
    completion_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    is_fully_evaluated = serializers.BooleanField()
    evaluation_completed_at = serializers.DateTimeField(allow_null=True)
    
    # Question details
    question_details = serializers.ListField(
        child=serializers.DictField(),
        required=False
    )


class QuestionEvaluationUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating question evaluations"""
    
    class Meta:
        model = QuestionEvaluation
        fields = [
            'marks_obtained', 'is_correct', 'evaluation_notes',
            'manual_feedback', 'requires_review'
        ]
    
    def validate_marks_obtained(self, value):
        if value < 0:
            raise serializers.ValidationError("Marks cannot be negative")
        if value > self.instance.max_marks:
            raise serializers.ValidationError(
                f"Marks cannot exceed maximum marks ({self.instance.max_marks})"
            )
        return value


class EvaluationStatisticsSerializer(serializers.Serializer):
    """Serializer for evaluation statistics"""
    
    total_attempts = serializers.IntegerField()
    fully_evaluated_attempts = serializers.IntegerField()
    partially_evaluated_attempts = serializers.IntegerField()
    pending_evaluation_attempts = serializers.IntegerField()
    
    # Time statistics
    average_evaluation_time = serializers.DurationField(allow_null=True)
    average_manual_evaluation_time = serializers.DurationField(allow_null=True)
    average_ai_evaluation_time = serializers.DurationField(allow_null=True)
    
    # Accuracy statistics
    average_ai_confidence = serializers.DecimalField(max_digits=3, decimal_places=2, allow_null=True)
    manual_review_rate = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    
    # Question type breakdown
    question_type_breakdown = serializers.DictField()
    evaluation_type_breakdown = serializers.DictField()
