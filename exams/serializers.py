from rest_framework import serializers
from .models import (
    Exam, ExamAttempt, ExamResult, ExamInvitation, ExamAnalytics, ExamViolation, ExamProctoring, QuestionAnalytics,
    QuestionEvaluation, EvaluationBatch, EvaluationSettings, EvaluationProgress, EvaluationRubric, ExamReschedule
)
from patterns.serializers import ExamPatternSerializer
from accounts.serializers import UserSerializer


class ExamSerializer(serializers.ModelSerializer):
    pattern = ExamPatternSerializer(read_only=True)
    pattern_id = serializers.IntegerField(write_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    institute_name = serializers.CharField(source='institute.name', read_only=True)
    is_active = serializers.ReadOnlyField()
    total_questions = serializers.ReadOnlyField()
    total_marks = serializers.ReadOnlyField()
    allowed_users_data = UserSerializer(source='allowed_users', many=True, read_only=True)

    class Meta:
        model = Exam
        fields = [
            'id', 'title', 'description', 'institute', 'institute_name', 'pattern', 'pattern_id',
            'status', 'start_date', 'end_date', 'duration_minutes', 'max_attempts',
            'allow_late_submission', 'late_submission_penalty', 'require_fullscreen',
            'disable_copy_paste', 'disable_right_click', 'enable_webcam_proctoring',
            'allow_tab_switching', 'is_public', 'allowed_users', 'allowed_users_data',
            'created_by', 'created_by_name', 'is_active', 'total_questions', 'total_marks',
            'timezone', 'grace_period_minutes', 'buffer_time_minutes', 'auto_start', 'auto_end',
            'reschedule_allowed', 'max_reschedules', 'reschedule_deadline',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        if attrs['start_date'] >= attrs['end_date']:
            raise serializers.ValidationError("Start date must be before end date")
        return attrs

    def create(self, validated_data):
        # Automatically set duration_minutes from the pattern
        pattern = validated_data['pattern']
        validated_data['duration_minutes'] = pattern.total_duration
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # If pattern_id is provided, update the pattern and duration
        if 'pattern_id' in validated_data:
            pattern_id = validated_data.pop('pattern_id')
            from patterns.models import ExamPattern
            pattern = ExamPattern.objects.get(id=pattern_id)
            validated_data['pattern'] = pattern
            validated_data['duration_minutes'] = pattern.total_duration
        return super().update(instance, validated_data)


class ExamCreateSerializer(serializers.ModelSerializer):
    pattern_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = Exam
        fields = [
            'title', 'description', 'pattern_id', 'start_date', 'end_date',
            'max_attempts', 'allow_late_submission', 'late_submission_penalty',
            'require_fullscreen', 'disable_copy_paste', 'disable_right_click',
            'enable_webcam_proctoring', 'allow_tab_switching', 'is_public', 'allowed_users',
            'status'
        ]

    def create(self, validated_data):
        # Get the pattern object and set duration_minutes from it
        pattern_id = validated_data.pop('pattern_id')
        from patterns.models import ExamPattern
        pattern = ExamPattern.objects.get(id=pattern_id)
        validated_data['pattern'] = pattern
        validated_data['duration_minutes'] = pattern.total_duration
        
        # Set status to 'active' so students can see the exam immediately
        validated_data['status'] = 'active'
        
        return super().create(validated_data)


class ExamAttemptSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    exam = ExamSerializer(read_only=True)  # Include full exam object
    is_completed = serializers.ReadOnlyField()
    time_remaining = serializers.ReadOnlyField()

    class Meta:
        model = ExamAttempt
        fields = [
            'id', 'exam', 'exam_title', 'student', 'student_name', 'attempt_number',
            'status', 'started_at', 'submitted_at', 'time_spent', 'score', 'percentage',
            'rank', 'ip_address', 'violations_count', 'proctoring_enabled', 
            'max_violations_allowed', 'fullscreen_required', 'is_completed', 'time_remaining',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'student', 'created_at', 'updated_at']


class ExamResultSerializer(serializers.ModelSerializer):
    attempt = ExamAttemptSerializer(read_only=True)

    class Meta:
        model = ExamResult
        fields = [
            'id', 'attempt', 'section_scores', 'total_questions_attempted',
            'total_correct_answers', 'total_wrong_answers', 'total_unattempted',
            'answers', 'created_at'
        ]


class ExamInvitationSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    invited_by_name = serializers.CharField(source='invited_by.get_full_name', read_only=True)
    is_valid_now = serializers.ReadOnlyField()
    can_attempt = serializers.ReadOnlyField()

    class Meta:
        model = ExamInvitation
        fields = [
            'id', 'exam', 'exam_title', 'user', 'user_name', 'user_email',
            'invited_by', 'invited_by_name', 'invited_at', 'is_accepted', 'accepted_at',
            'access_code', 'valid_from', 'valid_until', 'max_attempts', 'used_attempts',
            'is_active', 'is_valid_now', 'can_attempt'
        ]
        read_only_fields = ['id', 'invited_by', 'invited_at']


class ExamViolationSerializer(serializers.ModelSerializer):
    attempt_student = serializers.CharField(source='attempt.student.get_full_name', read_only=True)
    attempt_exam = serializers.CharField(source='attempt.exam.title', read_only=True)
    violation_type_display = serializers.CharField(source='get_violation_type_display', read_only=True)

    class Meta:
        model = ExamViolation
        fields = [
            'id', 'attempt', 'attempt_student', 'attempt_exam', 'violation_type',
            'violation_type_display', 'timestamp', 'screenshot', 'metadata'
        ]
        read_only_fields = ['id', 'timestamp']


class ExamProctoringSerializer(serializers.ModelSerializer):
    attempt_student = serializers.CharField(source='attempt.student.get_full_name', read_only=True)
    attempt_exam = serializers.CharField(source='attempt.exam.title', read_only=True)

    class Meta:
        model = ExamProctoring
        fields = [
            'id', 'attempt', 'attempt_student', 'attempt_exam', 'webcam_enabled',
            'snapshots', 'face_verification_passed', 'total_violations',
            'auto_disqualified', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ExamAnalyticsSerializer(serializers.ModelSerializer):
    exam_title = serializers.CharField(source='exam.title', read_only=True)

    class Meta:
        model = ExamAnalytics
        fields = [
            'id', 'exam', 'exam_title', 'total_invited', 'total_started',
            'total_completed', 'completion_rate', 'average_score', 'highest_score',
            'lowest_score', 'average_time_spent', 'last_updated'
        ]


class ExamStartSerializer(serializers.Serializer):
    exam_id = serializers.IntegerField()

    def validate_exam_id(self, value):
        try:
            exam = Exam.objects.get(id=value)
            if not exam.is_active:
                raise serializers.ValidationError("Exam is not currently active")
            return value
        except Exam.DoesNotExist:
            raise serializers.ValidationError("Exam not found")


class ExamSubmitSerializer(serializers.Serializer):
    attempt_id = serializers.IntegerField()
    answers = serializers.JSONField()

    def validate_attempt_id(self, value):
        try:
            attempt = ExamAttempt.objects.get(id=value)
            if attempt.status != 'in_progress':
                raise serializers.ValidationError("Exam attempt is not in progress")
            return value
        except ExamAttempt.DoesNotExist:
            raise serializers.ValidationError("Exam attempt not found")


class ViolationLogSerializer(serializers.Serializer):
    violation_type = serializers.ChoiceField(choices=ExamViolation.VIOLATION_TYPES)
    screenshot = serializers.ImageField(required=False)
    metadata = serializers.JSONField(default=dict)
    
    def create(self, validated_data):
        attempt = self.context.get('attempt')
        if not attempt:
            raise serializers.ValidationError("Attempt context is required")
        
        return ExamViolation.objects.create(
            attempt=attempt,
            violation_type=validated_data['violation_type'],
            screenshot=validated_data.get('screenshot'),
            metadata=validated_data.get('metadata', {})
        )


class ExamAccessSerializer(serializers.Serializer):
    access_code = serializers.CharField(max_length=20, required=False)
    exam_id = serializers.IntegerField(required=False)
    
    def validate(self, attrs):
        access_code = attrs.get('access_code')
        exam_id = attrs.get('exam_id')
        
        if not access_code and not exam_id:
            raise serializers.ValidationError("Either access_code or exam_id must be provided")
        
        return attrs


class SnapshotUploadSerializer(serializers.Serializer):
    image_data = serializers.CharField(help_text="Base64 encoded image data")
    timestamp = serializers.CharField()  # Accept string timestamp from frontend
    metadata = serializers.JSONField(default=dict)
    
    def validate_timestamp(self, value):
        """Convert string timestamp to datetime"""
        from datetime import datetime
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise serializers.ValidationError("Invalid timestamp format")


class QuestionAnalyticsSerializer(serializers.ModelSerializer):
    success_rate = serializers.ReadOnlyField()
    
    class Meta:
        model = QuestionAnalytics
        fields = [
            'id', 'exam', 'question_number', 'question_text', 'total_attempts',
            'correct_attempts', 'wrong_attempts', 'unattempted', 'average_score',
            'max_marks', 'difficulty_level', 'success_rate', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ExamAnalyticsDetailSerializer(serializers.ModelSerializer):
    question_analytics = QuestionAnalyticsSerializer(many=True, read_only=True)
    
    class Meta:
        model = ExamAnalytics
        fields = [
            'id', 'exam', 'total_invited', 'total_started', 'total_completed',
            'completion_rate', 'average_score', 'highest_score', 'lowest_score',
            'average_time_spent', 'last_updated', 'question_analytics'
        ]


# Evaluation System Serializers
class QuestionEvaluationSerializer(serializers.ModelSerializer):
    """Serializer for QuestionEvaluation model"""
    
    question = serializers.SerializerMethodField()
    evaluated_by_name = serializers.SerializerMethodField()
    
    class Meta:
        model = QuestionEvaluation
        fields = [
            'id', 'attempt', 'question', 'question_number',
            'student_answer', 'is_answered', 'evaluation_type', 'evaluation_status',
            'marks_obtained', 'max_marks', 'is_correct', 'evaluated_by', 'evaluated_by_name',
            'evaluated_at', 'evaluation_notes', 'ai_confidence_score', 'ai_feedback',
            'manual_feedback', 'requires_review', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_question(self, obj):
        from questions.serializers import QuestionSerializer
        return QuestionSerializer(obj.question).data
    
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


class ExamRescheduleSerializer(serializers.ModelSerializer):
    """Serializer for exam reschedule requests"""
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    student_email = serializers.CharField(source='student.email', read_only=True)
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    reviewed_by_name = serializers.CharField(source='reviewed_by.get_full_name', read_only=True)
    timezone_info = serializers.SerializerMethodField()
    
    class Meta:
        model = ExamReschedule
        fields = [
            'id', 'exam', 'exam_title', 'student', 'student_name', 'student_email',
            'original_start_date', 'original_end_date', 'new_start_date', 'new_end_date',
            'reason', 'status', 'reviewed_by', 'reviewed_by_name', 'review_notes',
            'timezone_info', 'created_at', 'reviewed_at'
        ]
        read_only_fields = ['id', 'created_at', 'reviewed_at']
    
    def get_timezone_info(self, obj):
        """Get timezone information for the exam"""
        return obj.exam.get_timezone_aware_dates()


class ExamRescheduleRequestSerializer(serializers.Serializer):
    """Serializer for creating reschedule requests"""
    new_start_date = serializers.DateTimeField()
    new_end_date = serializers.DateTimeField()
    reason = serializers.CharField(max_length=1000)
    
    def validate(self, attrs):
        if attrs['new_start_date'] >= attrs['new_end_date']:
            raise serializers.ValidationError("New start date must be before new end date")
        return attrs


class ExamRescheduleReviewSerializer(serializers.Serializer):
    """Serializer for reviewing reschedule requests"""
    status = serializers.ChoiceField(choices=ExamReschedule.RESCHEDULE_STATUS_CHOICES)
    review_notes = serializers.CharField(max_length=1000, required=False)


class TimezoneListSerializer(serializers.Serializer):
    """Serializer for timezone list"""
    value = serializers.CharField()
    label = serializers.CharField()
    offset = serializers.CharField()
    utc_offset = serializers.CharField()


class ExamInvitationSerializer(serializers.ModelSerializer):
    """Serializer for exam invitations"""
    student_name = serializers.CharField(source='student.get_full_name', read_only=True)
    student_email = serializers.CharField(source='student.email', read_only=True)
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    invited_by_name = serializers.CharField(source='invited_by.get_full_name', read_only=True)
    
    class Meta:
        model = ExamInvitation
        fields = [
            'id', 'exam', 'exam_title', 'student', 'student_name', 'student_email',
            'invited_by', 'invited_by_name', 'status', 'invited_at', 'accepted_at',
            'declined_at', 'custom_message', 'decline_reason', 'invitation_token'
        ]
        read_only_fields = ['id', 'invited_at', 'accepted_at', 'declined_at', 'invitation_token']


class ExamInvitationCreateSerializer(serializers.Serializer):
    """Serializer for creating exam invitations"""
    student_emails = serializers.ListField(
        child=serializers.EmailField(),
        min_length=1,
        max_length=100
    )
    custom_message = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    send_reminder = serializers.BooleanField(default=False)


class ExamInvitationBulkSerializer(serializers.Serializer):
    """Serializer for bulk invitation operations"""
    student_emails = serializers.ListField(
        child=serializers.EmailField(),
        min_length=1,
        max_length=100
    )
    custom_message = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    send_reminder = serializers.BooleanField(default=False)


class EmailTemplateSerializer(serializers.Serializer):
    """Serializer for email templates"""
    template_type = serializers.ChoiceField(choices=[
        ('invitation', 'Exam Invitation'),
        ('reminder', 'Reminder'),
        ('accepted', 'Invitation Accepted'),
        ('declined', 'Invitation Declined'),
    ])
    subject = serializers.CharField(max_length=200)
    text_content = serializers.CharField()
    html_content = serializers.CharField()
