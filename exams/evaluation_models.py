from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from accounts.models import User
from questions.models import Question


class QuestionEvaluation(models.Model):
    """Individual question evaluation for an exam attempt"""
    
    EVALUATION_STATUS_CHOICES = [
        ('pending', 'Pending Evaluation'),
        ('auto_evaluated', 'Auto Evaluated'),
        ('manually_evaluated', 'Manually Evaluated'),
        ('ai_evaluated', 'AI Evaluated'),
        ('reviewed', 'Reviewed'),
    ]
    
    EVALUATION_TYPE_CHOICES = [
        ('auto', 'Automatic'),
        ('manual', 'Manual'),
        ('ai', 'AI-Powered'),
        ('mixed', 'Mixed'),
    ]
    
    attempt = models.ForeignKey('ExamAttempt', on_delete=models.CASCADE, related_name='question_evaluations')
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    question_number = models.IntegerField()
    
    # Student's answer
    student_answer = models.TextField(blank=True)
    is_answered = models.BooleanField(default=False)
    
    # Evaluation details
    evaluation_type = models.CharField(max_length=10, choices=EVALUATION_TYPE_CHOICES, default='auto')
    evaluation_status = models.CharField(max_length=20, choices=EVALUATION_STATUS_CHOICES, default='pending')
    
    # Scoring
    marks_obtained = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    max_marks = models.DecimalField(max_digits=5, decimal_places=2)
    is_correct = models.BooleanField(default=False)
    
    # Evaluation metadata
    evaluated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='evaluated_questions')
    evaluated_at = models.DateTimeField(null=True, blank=True)
    evaluation_notes = models.TextField(blank=True)
    
    # AI evaluation specific
    ai_confidence_score = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, 
                                           validators=[MinValueValidator(0), MaxValueValidator(1)])
    ai_feedback = models.TextField(blank=True)
    
    # Manual evaluation specific
    manual_feedback = models.TextField(blank=True)
    requires_review = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['attempt', 'question']
        ordering = ['question_number']
    
    def __str__(self):
        return f"Q{self.question_number} - {self.attempt.student.get_full_name()} - {self.evaluation_status}"


class EvaluationBatch(models.Model):
    """Batch evaluation for multiple questions"""
    
    BATCH_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    BATCH_TYPE_CHOICES = [
        ('auto', 'Automatic'),
        ('manual', 'Manual'),
        ('ai', 'AI-Powered'),
    ]
    
    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='evaluation_batches')
    batch_type = models.CharField(max_length=10, choices=BATCH_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=BATCH_STATUS_CHOICES, default='pending')
    
    # Batch details
    questions_count = models.IntegerField(default=0)
    evaluated_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    
    # Processing details
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    # AI specific
    ai_model_used = models.CharField(max_length=100, blank=True)
    ai_processing_time = models.DurationField(null=True, blank=True)
    
    # Error handling
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.batch_type.title()} Evaluation Batch - {self.exam.title}"


class EvaluationSettings(models.Model):
    """Settings for evaluation system"""
    
    exam = models.OneToOneField('Exam', on_delete=models.CASCADE, related_name='evaluation_settings')
    
    # Auto-evaluation settings
    enable_auto_evaluation = models.BooleanField(default=True)
    auto_evaluate_mcq = models.BooleanField(default=True)
    auto_evaluate_numerical = models.BooleanField(default=True)
    auto_evaluate_true_false = models.BooleanField(default=True)
    auto_evaluate_fill_blank = models.BooleanField(default=True)
    
    # Manual evaluation settings
    enable_manual_evaluation = models.BooleanField(default=True)
    require_manual_review = models.BooleanField(default=False)
    manual_evaluation_deadline = models.DateTimeField(null=True, blank=True)
    
    # AI evaluation settings
    enable_ai_evaluation = models.BooleanField(default=False)
    ai_model_preference = models.CharField(max_length=50, default='gpt-3.5-turbo')
    ai_confidence_threshold = models.DecimalField(max_digits=3, decimal_places=2, default=0.7,
                                                validators=[MinValueValidator(0), MaxValueValidator(1)])
    ai_fallback_to_manual = models.BooleanField(default=True)
    
    # Mixed evaluation settings
    enable_mixed_evaluation = models.BooleanField(default=False)
    auto_first_then_manual = models.BooleanField(default=True)
    ai_first_then_manual = models.BooleanField(default=False)
    
    # Notification settings
    notify_evaluators = models.BooleanField(default=True)
    notify_students_on_completion = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Evaluation Settings - {self.exam.title}"


class EvaluationRubric(models.Model):
    """Rubric for manual evaluation of subjective questions"""
    
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='evaluation_rubrics')
    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='evaluation_rubrics')
    
    # Rubric details
    rubric_name = models.CharField(max_length=200)
    description = models.TextField()
    
    # Scoring criteria
    max_marks = models.DecimalField(max_digits=5, decimal_places=2)
    criteria = models.JSONField(default=list)  # List of criteria with marks distribution
    
    # Usage
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_rubrics')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Rubric for Q{self.question.id} - {self.rubric_name}"


class EvaluationProgress(models.Model):
    """Track evaluation progress for an exam"""
    
    exam = models.OneToOneField('Exam', on_delete=models.CASCADE, related_name='evaluation_progress')
    
    # Progress counts
    total_questions = models.IntegerField(default=0)
    auto_evaluated = models.IntegerField(default=0)
    manually_evaluated = models.IntegerField(default=0)
    ai_evaluated = models.IntegerField(default=0)
    pending_evaluation = models.IntegerField(default=0)
    
    # Completion status
    is_fully_evaluated = models.BooleanField(default=False)
    evaluation_completed_at = models.DateTimeField(null=True, blank=True)
    
    # Statistics
    average_auto_confidence = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    manual_evaluation_time = models.DurationField(null=True, blank=True)
    ai_evaluation_time = models.DurationField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Evaluation Progress - {self.exam.title}"
    
    @property
    def completion_percentage(self):
        if self.total_questions == 0:
            return 0
        evaluated = self.auto_evaluated + self.manually_evaluated + self.ai_evaluated
        return (evaluated / self.total_questions) * 100
