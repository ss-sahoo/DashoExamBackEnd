from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from accounts.models import Institute, User
from exams.models import Exam


class QuestionBank(models.Model):
    """Question bank for storing reusable questions"""
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='question_banks')
    is_public = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_question_banks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['name', 'institute']

    def __str__(self):
        return f"{self.name} ({self.institute.name})"


class Question(models.Model):
    """Individual question model"""
    DIFFICULTY_CHOICES = [
        ('easy', 'Easy'),
        ('medium', 'Medium'),
        ('hard', 'Hard'),
    ]

    QUESTION_TYPE_CHOICES = [
        ('single_mcq', 'Single Correct MCQ'),
        ('multiple_mcq', 'Multiple Correct MCQ'),
        ('numerical', 'Numerical Questions'),
        ('subjective', 'Subjective Questions'),
        ('true_false', 'True/False Questions'),
        ('fill_blank', 'Fill in the Blanks'),
    ]

    # Basic info
    question_text = models.TextField()
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default='medium')
    
    # Options for MCQ
    options = models.JSONField(default=list, blank=True)
    correct_answer = models.TextField()
    
    # Solution and explanation
    solution = models.TextField(blank=True)
    explanation = models.TextField(blank=True)
    
    # Metadata
    marks = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    negative_marks = models.DecimalField(max_digits=3, decimal_places=2, default=0.25)
    
    # Organization
    subject = models.CharField(max_length=100)
    topic = models.CharField(max_length=100, blank=True)
    subtopic = models.CharField(max_length=100, blank=True)
    tags = models.JSONField(default=list, blank=True)
    
    # Pattern Section Assignment (optional)
    pattern_section = models.ForeignKey('patterns.PatternSection', on_delete=models.SET_NULL, null=True, blank=True, related_name='questions')
    # Position within the overall pattern (1-based). Helps map to /pattern/:id/question/:n
    question_number_in_pattern = models.IntegerField(null=True, blank=True, db_index=True)
    
    # References
    question_bank = models.ForeignKey(QuestionBank, on_delete=models.CASCADE, related_name='questions', null=True, blank=True)
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='questions')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_questions')
    
    # Status
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_questions')
    verified_at = models.DateTimeField(null=True, blank=True)
    
    # Usage tracking
    usage_count = models.IntegerField(default=0)
    success_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Q{self.id}: {self.question_text[:50]}..."

    def increment_usage(self):
        self.usage_count += 1
        self.save(update_fields=['usage_count'])


class ExamQuestion(models.Model):
    """Questions assigned to specific exams"""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='exam_questions')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='exam_assignments')
    question_number = models.IntegerField(validators=[MinValueValidator(1)])
    section_name = models.CharField(max_length=100)
    marks = models.IntegerField(validators=[MinValueValidator(1)])
    negative_marks = models.DecimalField(max_digits=3, decimal_places=2, default=0.25)
    order = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['exam', 'question_number']
        ordering = ['question_number']

    def __str__(self):
        return f"{self.exam.title} - Q{self.question_number}"

    def save(self, *args, **kwargs):
        # Update question usage count
        self.question.increment_usage()
        super().save(*args, **kwargs)


class QuestionImage(models.Model):
    """Images associated with questions"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='question_images/')
    caption = models.CharField(max_length=200, blank=True)
    order = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Image for Q{self.question.id}"


class QuestionComment(models.Model):
    """Comments and reviews on questions"""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='question_comments')
    comment = models.TextField()
    is_review = models.BooleanField(default=False)
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.user.email} on Q{self.question.id}"


class QuestionTemplate(models.Model):
    """Templates for common question types"""
    TEMPLATE_CATEGORIES = [
        ('academic', 'Academic'),
        ('competitive', 'Competitive Exams'),
        ('language', 'Language Learning'),
        ('technical', 'Technical'),
        ('mathematics', 'Mathematics'),
        ('science', 'Science'),
        ('general', 'General Knowledge'),
    ]
    
    name = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=TEMPLATE_CATEGORIES, default='general')
    question_type = models.CharField(max_length=20, choices=Question.QUESTION_TYPE_CHOICES)
    difficulty = models.CharField(max_length=10, choices=Question.DIFFICULTY_CHOICES, default='medium')
    subject = models.CharField(max_length=100, blank=True)
    topic = models.CharField(max_length=100, blank=True)
    template_data = models.JSONField(default=dict)
    example_question = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='question_templates')
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='question_templates', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_featured', '-usage_count', 'name']

    def __str__(self):
        return f"{self.name} ({self.question_type})"
    
    def increment_usage(self):
        self.usage_count += 1
        self.save(update_fields=['usage_count'])


# AI & Vector Search Models
from pgvector.django import VectorField


class QuestionEmbedding(models.Model):
    """Store vector embeddings for questions"""
    question = models.OneToOneField(
        Question, 
        on_delete=models.CASCADE, 
        related_name='embedding',
        primary_key=True
    )
    # OpenAI ada-002 produces 1536-dimensional vectors
    text_embedding = VectorField(dimensions=1536)
    # Combined embedding (question + options + solution)
    combined_embedding = VectorField(dimensions=1536, null=True, blank=True)
    
    embedding_model = models.CharField(max_length=100, default='text-embedding-ada-002')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'question_embeddings'
        indexes = [
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Embedding for Q{self.question.id}"


class ChatHistory(models.Model):
    """Store chat conversations for context"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_history')
    session_id = models.CharField(max_length=100, db_index=True)
    role = models.CharField(max_length=20, choices=[
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System')
    ])
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)  # Store sources, timestamps, etc.
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['user', 'session_id', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.role}: {self.content[:50]}..."