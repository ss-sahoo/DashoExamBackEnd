from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import RegexValidator


class Institute(models.Model):
    """Institute/Organization model"""
    name = models.CharField(max_length=200, unique=True)
    domain = models.CharField(max_length=100, unique=True, blank=True, null=True, help_text="Optional email domain (e.g., 'university.edu')")
    description = models.TextField(blank=True, help_text="Brief description of the institute")
    address = models.TextField(blank=True)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=20, blank=True)
    website = models.URLField(blank=True)
    logo = models.ImageField(upload_to='institute_logos/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False, help_text="Whether the institute is verified by super admin")
    created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_institutes')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name
    
    def get_user_count(self):
        """Get the number of users in this institute"""
        return self.users.count()
    
    def get_active_user_count(self):
        """Get the number of active users in this institute"""
        return self.users.filter(is_active=True).count()
    
    def get_admins(self):
        """Get all admin users in this institute"""
        return self.users.filter(role__in=['institute_admin', 'super_admin'])
    
    def can_be_managed_by(self, user):
        """Check if a user can manage this institute"""
        if user.role == 'super_admin':
            return True
        return user.institute == self and user.role in ['institute_admin', 'super_admin']


class InstituteInvitation(models.Model):
    """Model for inviting users to join an institute"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
    ]
    
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='invitations')
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=[
        ('super_admin', 'Super Admin'),
        ('institute_admin', 'Institute Admin'),
        ('exam_admin', 'Exam Admin'),
        ('teacher', 'Teacher'),
        ('student', 'Student'),
    ], default='student')
    invited_by = models.ForeignKey('User', on_delete=models.CASCADE, related_name='sent_institute_invitations')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    message = models.TextField(blank=True, help_text="Optional message to include with invitation")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['institute', 'email']
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Invitation to {self.email} for {self.institute.name}"
    
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at


class User(AbstractUser):
    """Custom User model with institute-based authentication"""
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('institute_admin', 'Institute Admin'),
        ('exam_admin', 'Exam Admin'),
        ('teacher', 'Teacher'),
        ('student', 'Student'),
    ]

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    institute = models.ForeignKey(Institute, on_delete=models.CASCADE, related_name='users', null=True, blank=True)
    phone = models.CharField(
        max_length=15, 
        blank=True,
        validators=[RegexValidator(regex=r'^\+?1?\d{9,15}$', message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")]
    )
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_full_name()} ({self.email})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def is_institute_admin(self):
        return self.role in ['super_admin', 'institute_admin']

    def can_manage_exams(self):
        return self.role in ['super_admin', 'institute_admin', 'exam_admin', 'teacher']

    def can_create_exams(self):
        return self.role in ['super_admin', 'institute_admin', 'exam_admin']


class UserPermission(models.Model):
    """Custom permissions for users within institutes"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='permissions')
    permission_type = models.CharField(max_length=50)
    granted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='granted_permissions')
    granted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ['user', 'permission_type']

    def __str__(self):
        return f"{self.user.email} - {self.permission_type}"


class InstituteSettings(models.Model):
    """Institute-specific settings"""
    institute = models.OneToOneField(Institute, on_delete=models.CASCADE, related_name='settings')
    allow_student_registration = models.BooleanField(default=True)
    require_email_verification = models.BooleanField(default=True)
    max_exam_duration = models.IntegerField(default=180, help_text="Maximum exam duration in minutes")
    allow_exam_retakes = models.BooleanField(default=False)
    max_retake_attempts = models.IntegerField(default=1)
    exam_security_level = models.CharField(
        max_length=20,
        choices=[
            ('basic', 'Basic'),
            ('standard', 'Standard'),
            ('high', 'High'),
        ],
        default='standard'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Settings for {self.institute.name}"