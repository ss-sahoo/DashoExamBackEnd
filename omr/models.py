"""
OMR App Models
Handles OMR sheet generation and submission tracking
"""
from django.db import models
from django.core.validators import MinValueValidator
import uuid


class OMRSheet(models.Model):
    """Generated OMR sheet for an exam"""
    exam = models.ForeignKey(
        'exams.Exam',
        on_delete=models.CASCADE,
        related_name='omr_sheets'
    )
    sheet_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    
    # Generated files
    pdf_file = models.FileField(upload_to='omr_sheets/', blank=True, null=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Layout coordinates from OMR generator for evaluation"
    )
    
    # Configuration used for generation
    candidate_fields = models.JSONField(
        default=list,
        blank=True,
        help_text="Candidate identification fields (roll number, center code, etc.)"
    )
    question_config = models.JSONField(
        default=list,
        blank=True,
        help_text="Question configuration used for generation"
    )
    
    # Generation status
    STATUS_CHOICES = [
        ('pending', 'Pending Generation'),
        ('generating', 'Generating'),
        ('generated', 'Generated'),
        ('failed', 'Generation Failed'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    generation_error = models.TextField(blank=True, null=True)
    
    # Flags
    is_primary = models.BooleanField(
        default=True,
        help_text="Primary OMR sheet for the exam"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "OMR Sheet"
        verbose_name_plural = "OMR Sheets"
    
    def __str__(self):
        return f"OMR Sheet for {self.exam.title} ({self.sheet_id})"


class OMRSubmission(models.Model):
    """Scanned OMR sheet submission for evaluation"""
    STATUS_CHOICES = [
        ('pending', 'Pending Evaluation'),
        ('processing', 'Processing'),
        ('evaluated', 'Evaluated'),
        ('failed', 'Evaluation Failed'),
    ]
    
    omr_sheet = models.ForeignKey(
        OMRSheet,
        on_delete=models.CASCADE,
        related_name='submissions'
    )
    attempt = models.ForeignKey(
        'exams.ExamAttempt',
        on_delete=models.CASCADE,
        related_name='omr_submissions',
        null=True,
        blank=True
    )
    student = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='omr_submissions'
    )
    
    # Uploaded files (list of paths)
    scanned_files = models.JSONField(
        default=list,
        help_text="List of uploaded scanned image/PDF paths"
    )
    
    # Evaluation status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    evaluation_error = models.TextField(blank=True, null=True)
    
    # Extracted data from OMR evaluation
    extracted_responses = models.JSONField(
        default=dict,
        blank=True,
        help_text="Responses extracted from the scanned OMR sheet"
    )
    candidate_info = models.JSONField(
        default=dict,
        blank=True,
        help_text="Candidate identification info extracted from OMR"
    )
    evaluation_results = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full evaluation results including score and question details"
    )
    
    # Output files
    annotated_pdf = models.FileField(
        upload_to='omr_results/',
        blank=True,
        null=True,
        help_text="Annotated OMR sheet with marks/ticks"
    )
    results_json = models.FileField(
        upload_to='omr_results/',
        blank=True,
        null=True,
        help_text="JSON file with detailed results"
    )
    
    # Score summary (denormalized for quick access)
    score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    max_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True
    )
    
    # Timestamps
    submitted_at = models.DateTimeField(auto_now_add=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-submitted_at']
        verbose_name = "OMR Submission"
        verbose_name_plural = "OMR Submissions"
    
    def __str__(self):
        student_name = self.student.get_full_name() or self.student.email
        return f"OMR Submission by {student_name} for {self.omr_sheet.exam.title}"


class AnswerKey(models.Model):
    """Answer key for an exam (for OMR evaluation)"""
    exam = models.OneToOneField(
        'exams.Exam',
        on_delete=models.CASCADE,
        related_name='answer_key'
    )
    
    # Answer key data structure:
    # {
    #     'Q1': {'correct': ['A'], 'marks': 4, 'negative': 1},
    #     'Q2': {'correct': ['B', 'C'], 'marks': 4, 'negative': 0},
    #     'Q31': {'correct': ['1234'], 'marks': 4, 'negative': 0},
    # }
    answers = models.JSONField(
        default=dict,
        help_text="Answer key mapping question fields to correct answers and marks"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_answer_keys'
    )
    
    class Meta:
        verbose_name = "Answer Key"
        verbose_name_plural = "Answer Keys"
    
    def __str__(self):
        return f"Answer Key for {self.exam.title}"
