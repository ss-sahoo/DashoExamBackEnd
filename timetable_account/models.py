"""
Account-related models.

This app holds:
- Custom User model with roles (Super Admin, Admin, Teacher, Student)
- Institute / Center / Program / Batch / Enrollment
"""

from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid


class TimeStampedModel(models.Model):
    """
    Base abstract model for common timestamp fields.
    Makes all child models automatically track creation & update times.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)  # set once when created
    updated_at = models.DateTimeField(auto_now=True)  # updated on every save

    class Meta:
        abstract = True


class User(AbstractUser):
    """
    Custom user model for the entire system.

    We extend Django's AbstractUser to add 'role' and relations to centers.
    This keeps the system scalable and compatible with Django's auth framework.
    """

    # Possible roles in the system.
    # - SUPER_ADMIN: Top-level user who controls the whole institute and all centers.
    # - ADMIN: Admin of a particular center (can manage programs, batches, students in that center).
    # - TEACHER: Teacher who teaches in one or more batches.
    # - STUDENT: Student who is enrolled in one or more batches.
    # - STAFF: Non-teaching staff (front-office, accounts, etc.).
    ROLE_SUPER_ADMIN = "SUPER_ADMIN"
    ROLE_ADMIN = "ADMIN"
    ROLE_TEACHER = "TEACHER"
    ROLE_STUDENT = "STUDENT"
    ROLE_STAFF = "STAFF"

    ROLE_CHOICES = [
        (ROLE_SUPER_ADMIN, "Super Admin"),  # Head-quarter / main control user
        (ROLE_ADMIN, "Admin"),  # Center-level admin
        (ROLE_TEACHER, "Teacher"),
        (ROLE_STUDENT, "Student"),
        (ROLE_STAFF, "Staff"),
    ]

    # Main "type" of the user. This decides what this user is allowed to do.
    # You will control permissions in views / DRF / templates based on this field.
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default=ROLE_STUDENT,
        help_text="Role of the user in the system.",
    )
    # ================
    # BASIC USER INFO
    # ================

    # Optional profile photo for the user.
    profile_image = models.ImageField(
        upload_to="profiles/",
        blank=True,
        null=True,
        help_text="Optional profile image of the user.",
    )

    # Primary contact number for the user.
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Primary contact phone number of the user.",
    )

    # ==========================
    # TEACHER EXTRA FIELDS
    # ==========================
    # These fields are mainly useful when role = TEACHER.

    # Short teacher code used in timetables / Excel sheets.
    # Example: "AK-CAP", "BTDS", etc.
    teacher_code = models.CharField(
        max_length=50,
        blank=True,
        help_text=(
            "Readable code for a teacher. "
            "Example values from your sheet: 'AK-CAP', 'BTDS', etc."
        ),
    )

    # Employee ID from HR/payroll system (string to support any format).
    teacher_employee_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="Official employee id of the teacher. Example: 'EMP-00123'.",
    )

    # Subjects that the teacher handles, stored as plain text.
    # Example: "Physics" or "Physics, Chemistry".
    teacher_subjects = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Subjects that the teacher handles, stored as plain text. "
            "Example: 'Physics', or 'Physics, Chemistry', etc."
        ),
    )

    # Optional DEFAULT weekly availability pattern for this teacher.
    #
    # This is only a template. Real availability per timetable is stored in
    # `TeacherSlotAvailability` in the `timetable` app, but when you create a
    # new timetable you can copy from this field to pre-fill slots.
    #
    # Example structure (matches your optimisation code style):
    # {
    #   "mon": ["m1", "m2", "m3"],
    #   "tue": ["tu1", "tu2"],
    #   "wed": [],
    #   ...
    # }
    default_available_slots = models.JSONField(
        blank=True,
        null=True,
        help_text=(
            "Optional default weekly slot availability for this teacher. "
            "Use this as a template when creating TeacherSlotAvailability "
            "rows for a new timetable."
        ),
    )

    # Optional relation to a Center:
    # - Super Admins typically don't belong to any specific center -> can be null.
    # - Admins, Teachers, Students usually belong to one Center.
    #   Example: An Admin of 'Allen Jaipur Center' will have center = that Center.
    center = models.ForeignKey(
        "Center",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
        help_text="Center to which the user belongs (if applicable).",
    )

    def is_super_admin(self) -> bool:
        return self.role == self.ROLE_SUPER_ADMIN

    def is_admin(self) -> bool:
        """
        Convenience helper: check if the user is a Center Admin (role = ADMIN).
        Use this when writing permission checks, for example:
        if request.user.is_admin(): allow to create batches in their center.
        """
        return self.role == self.ROLE_ADMIN

    def is_teacher(self) -> bool:
        return self.role == self.ROLE_TEACHER

    def is_student(self) -> bool:
        return self.role == self.ROLE_STUDENT

    def is_staff_role(self) -> bool:
        """
        Distinguish our custom STAFF role from Django's built-in is_staff flag.
        Use this for non-teaching staff members.
        """
        return self.role == self.ROLE_STAFF

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"


class Institute(TimeStampedModel):
    """
    Represents the Head Office / Main Institute.
    In your example: "Allen Coaching" with headquarters in Delhi.
    Usually there will be only ONE instance, but the model supports many.
    """

    name = models.CharField(max_length=255, unique=True)
    head_office_location = models.CharField(
        max_length=255,
        help_text="City / address of the head office. Example: Delhi.",
    )

    def __str__(self) -> str:  # type: ignore[override]
        return self.name


class Center(TimeStampedModel):
    """
    Represents a physical or virtual center/branch of the Institute.
    Example: 'Allen - Jaipur Center', 'Allen - Mumbai Center', etc.

    Super Admin can:
    - create Centers
    - assign Admin(s) to a Center
    """

    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="centers",
        help_text="Parent institute of this center.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Name of the center. Example: 'Allen - Jaipur Center'.",
    )
    city = models.CharField(
        max_length=100,
        help_text="City where this center is located.",
    )
    address = models.TextField(
        blank=True,
        help_text="Optional full address of the center.",
    )

    # Admin user(s) for this center:
    # - only users with role=ADMIN should be added here (you enforce this in forms/views/serializers).
    # - This lets one center have multiple admins if needed (for example, academic admin + office admin).
    admins = models.ManyToManyField(
        User,
        blank=True,
        related_name="admin_centers",
        help_text="Users who are admins of this center.",
    )

    def __str__(self) -> str:  # type: ignore[override]
        return f"{self.name} ({self.city})"


class Program(TimeStampedModel):
    """
    Represents a Program running at a specific center.

    Examples:
    - 'Super 30'
    - 'Only Board'
    Each Program belongs to ONE Center, but a Center can have MANY Programs.

    Created/managed by Super Admin (as per requirement).
    """

    center = models.ForeignKey(
        Center,
        on_delete=models.CASCADE,
        related_name="programs",
        help_text="Center where this program is offered.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Program name, e.g. 'Super 30', 'Only Board'.",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional detailed description of the program.",
    )
    # Example: Class 11, Class 12, JEE Prep, NEET Prep, etc.
    category = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional category for grouping programs.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Programs can be deactivated instead of deleting.",
    )

    class Meta:
        unique_together = ("center", "name")  # same name allowed in other centers
        ordering = ["center__name", "name"]

    def __str__(self) -> str:  # type: ignore[override]
        return f"{self.name} - {self.center.name}"


class Batch(TimeStampedModel):
    """
    Represents a Batch inside a Program.

    - Created by Admin of that particular center.
    - Students are enrolled into Batches.
    - Teachers can be assigned to Batches as well.
    """

    program = models.ForeignKey(
        Program,
        on_delete=models.CASCADE,
        related_name="batches",
        help_text="Program under which this batch runs.",
    )

    # Short code for this batch.
    # Example: 'BATCH-10A-2025', 'S30-A', etc.
    # This is useful for quickly referencing batches in reports, attendance sheets, etc.
    code = models.CharField(
        max_length=50,
        help_text="Short unique-like code for this batch. Example: 'S30-A-2025'.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Batch name, e.g. 'Super 30 - Batch A (2025)'.",
    )
    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Optional batch start date.",
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Optional batch end date.",
    )

    # Teachers who teach this batch
    teachers = models.ManyToManyField(
        User,
        blank=True,
        related_name="teaching_batches",
        help_text="Teachers assigned to this batch.",
    )

    # Students are linked via a separate Enrollment model (below) for extra flexibility.
    # This allows you to store join_date, status, etc.

    class Meta:
        unique_together = ("program", "name")  # unique batch name per program
        ordering = ["program__name", "name"]

    def __str__(self) -> str:  # type: ignore[override]
        return f"{self.name} ({self.program.name})"


class Enrollment(TimeStampedModel):
    """
    Represents the relationship between a Student and a Batch.

    This intermediate model makes the system more scalable because we can
    easily add more fields later (e.g. fees, payment status, attendance stats, etc.)
    """

    STATUS_ACTIVE = "ACTIVE"
    STATUS_COMPLETED = "COMPLETED"
    STATUS_DROPPED = "DROPPED"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_DROPPED, "Dropped"),
    ]

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="enrollments",
        help_text="User with role=STUDENT enrolled in this batch.",
    )
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="enrollments",
        help_text="Batch into which the student is enrolled.",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        help_text="Current enrollment status of the student in this batch.",
    )
    joined_on = models.DateField(
        auto_now_add=True,
        help_text="Date when the student joined this batch.",
    )

    class Meta:
        unique_together = ("student", "batch")  # student can't be enrolled twice in same batch
        ordering = ["-created_at"]

    def __str__(self) -> str:  # type: ignore[override]
        return f"{self.student.username} -> {self.batch.name} ({self.status})"


