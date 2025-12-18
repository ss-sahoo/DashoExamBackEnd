"""
Timetable-related models.

This module handles:
- Timetable creation with date ranges (from_date to to_date)
- Day-wise time slots (each day can have different class timings)
- Free classes tracking
- Batch and teacher assignment to slots
- Teacher constraints (min/max classes per teacher)
- Teacher availability (present/absent status)
"""

from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
import uuid
from accounts.models import Batch, User, Center


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Timetable(TimeStampedModel):
    """
    Main Timetable model that represents a complete timetable for a date range.

    Admin workflow:
    1. Admin creates a Timetable with from_date, to_date, and free_classes_count
    2. Admin then creates DaySlot entries for each day (Monday, Tuesday, etc.)
    3. For each DaySlot, admin specifies start_time and end_time for each class
    4. Admin then assigns batches and teachers to these DaySlots via TimetableEntry

    Example:
    - from_date = 2025-01-01
    - to_date = 2025-03-31
    - free_classes_count = 3 (means first 3 classes are free)
    - center = Allen Jaipur Center
    """
    center = models.ForeignKey(
        Center,
        on_delete=models.CASCADE,
        related_name="timetables",
        help_text="Center for which this timetable is created.",
    )
    
    from_date = models.DateField(
        help_text="Start date of the timetable period. Example: 2025-01-01",
    )
    
    to_date = models.DateField(
        help_text="End date of the timetable period. Example: 2025-03-31",
    )
    
    free_classes_count = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text=(
            "Number of free classes in this timetable. "
            "Example: If set to 3, then the first 3 classes are marked as free."
        ),
    )
    
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this timetable is currently active.",
    )
    
    description = models.TextField(
        blank=True,
        help_text="Optional description or notes about this timetable.",
    )

    class Meta:
        ordering = ["-from_date", "-to_date"]
        verbose_name = "Timetable"
        verbose_name_plural = "Timetables"

    def __str__(self) -> str:
        return f"{self.center.name} - {self.from_date} to {self.to_date}"


class DaySlot(TimeStampedModel):
    """
    Represents a time slot for a specific day in a timetable.

    IMPORTANT: Each day can have DIFFERENT class timings.
    For example:
    - Monday might have: Class 1 (08:00-09:00), Class 2 (09:30-11:00)
    - Tuesday might have: Class 1 (08:30-09:30), Class 2 (10:00-11:30)

    Admin workflow:
    - After creating a Timetable, admin creates DaySlot entries
    - For each day (Monday, Tuesday, etc.), admin adds multiple DaySlots
    - Each DaySlot has a slot_number (1, 2, 3...) and start_time/end_time
    """
    # Days of the week choices (kept for backwards compatibility with weekly mode)
    MONDAY = "MON"
    TUESDAY = "TUE"
    WEDNESDAY = "WED"
    THURSDAY = "THU"
    FRIDAY = "FRI"
    SATURDAY = "SAT"
    SUNDAY = "SUN"

    DAY_CHOICES = [
        (MONDAY, "Monday"),
        (TUESDAY, "Tuesday"),
        (WEDNESDAY, "Wednesday"),
        (THURSDAY, "Thursday"),
        (FRIDAY, "Friday"),
        (SATURDAY, "Saturday"),
        (SUNDAY, "Sunday"),
    ]

    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="day_slots",
        help_text="Timetable to which this day slot belongs.",
    )
    
    day = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text=(
            "Day of the week (MON, TUE, etc.) for legacy weekly timetables. "
            "For date-based timetables, this is derived from actual_date. "
            "Can be null for date-based timetables where day_index is used."
        ),
    )

    # New fields to support date-based timetables (D1..Dn within timetable range)
    day_index = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Index of the calendar day within the timetable date range, starting at 1. "
            "Example: D1 = from_date, D2 = from_date + 1 day, etc."
        ),
    )

    actual_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Concrete calendar date for this slot. Used for date-based timetables. "
            "For legacy weekly timetables this may be null."
        ),
    )

    # Optional short code for this slot, used by optimisation code
    # and spreadsheets. Example:
    # - Monday slots:  m1, m2, m3, m4, m5
    # - Tuesday slots: tu1, tu2, tu3, tu4, tu5
    # - Wednesday:     w1, w2, ...
    # This lets you build dictionaries like:
    # available_slots['mon']['m1'] = '8-9.30'
    slot_code = models.CharField(
        max_length=20,
        blank=True,
        help_text="Short code for this day-slot, e.g. 'm1', 'tu3', 'w5'.",
    )
    
    slot_number = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text=(
            "Slot number for this day. "
            "Example: 1 for first class, 2 for second class, etc."
        ),
    )
    
    start_time = models.TimeField(
        help_text="Start time of this class slot. Example: 08:00",
    )
    
    end_time = models.TimeField(
        help_text="End time of this class slot. Example: 09:00",
    )
    
    is_free_class = models.BooleanField(
        default=False,
        help_text=(
            "Whether this slot is a free class. "
            "This is automatically set based on free_classes_count in Timetable."
        ),
    )

    class Meta:
        # For date-based timetables, use day_index; for weekly, use day
        # We can't have both in unique_together, so we'll use slot_code as unique identifier
        ordering = ["timetable", "day_index", "day", "slot_number"]
        verbose_name = "Day Slot"
        verbose_name_plural = "Day Slots"
        # Add index for better query performance
        indexes = [
            models.Index(fields=["timetable", "day_index", "slot_number"]),
            models.Index(fields=["timetable", "day", "slot_number"]),
        ]

    def __str__(self) -> str:
        if self.day_index:
            # Date-based timetable
            day_label = f"D{self.day_index}"
            if self.actual_date:
                day_label += f" ({self.actual_date})"
        elif self.day:
            # Weekly timetable
            day_label = self.get_day_display() if hasattr(self, 'get_day_display') else self.day
        else:
            day_label = "Unknown"
        
        return f"{day_label} - Slot {self.slot_number} ({self.start_time} to {self.end_time})"
    
    def get_day_display(self):
        """Get human-readable day name for weekly timetables."""
        day_map = {
            self.MONDAY: "Monday",
            self.TUESDAY: "Tuesday",
            self.WEDNESDAY: "Wednesday",
            self.THURSDAY: "Thursday",
            self.FRIDAY: "Friday",
            self.SATURDAY: "Saturday",
            self.SUNDAY: "Sunday",
        }
        return day_map.get(self.day, self.day or "Unknown")


class TimetableEntry(TimeStampedModel):
    """

    - TimetableEntry answers: "This batch has a class in this slot."
    - It does NOT permanently fix which teacher will teach that slot.
      Teacher assignment for each slot is normally decided by your
      optimisation logic using BatchFacultyLoad + TeacherConstraint.

    If you want to hard-lock a specific teacher+subject in a slot,
    that is stored separately in the FixedSlot model.
    """
    day_slot = models.ForeignKey(
        DaySlot,
        on_delete=models.CASCADE,
        related_name="timetable_entries",
        help_text="Day slot for which this entry is created.",
    )
    
    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="timetable_entries",
        help_text="Batch that will have class in this slot.",
    )
    
    subject = models.CharField(
        max_length=100,
        help_text="Subject being taught. Example: 'Physics', 'Chemistry', 'Maths'.",
    )
    
    room_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="Optional room number or location where this class will be held.",
    )

    class Meta:
        unique_together = ("day_slot", "batch")
        ordering = ["day_slot__day", "day_slot__slot_number", "batch__code"]
        verbose_name = "Timetable Entry"
        verbose_name_plural = "Timetable Entries"

    def __str__(self) -> str:
        return f"{self.day_slot.get_day_display()} Slot {self.day_slot.slot_number} - {self.batch.code} - {self.subject}"


class TeacherConstraint(TimeStampedModel):
    """
    Defines min/max number of classes per teacher for a timetable.

    Admin workflow:
    - Admin sets constraints for each teacher in a timetable
    - min_classes: Minimum number of classes a teacher must teach
    - max_classes: Maximum number of classes a teacher can teach
    - This helps ensure fair distribution of workload
    """
    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="teacher_constraints",
        help_text="Timetable for which this constraint applies.",
    )
    
    teacher = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.ROLE_TEACHER},
        related_name="teacher_constraints",
        help_text="Teacher for whom this constraint is set.",
    )
    
    min_classes = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Minimum number of classes this teacher must teach per week.",
    )
    
    max_classes = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Maximum number of classes this teacher can teach per week.",
    )

    class Meta:
        unique_together = ("timetable", "teacher")
        ordering = ["timetable", "teacher__username"]
        verbose_name = "Teacher Constraint"
        verbose_name_plural = "Teacher Constraints"

    def __str__(self) -> str:
        return f"{self.teacher.username} - Min: {self.min_classes}, Max: {self.max_classes}"


class TeacherAvailability(TimeStampedModel):
    """
    Tracks whether a teacher is present or absent for a specific date.

    Admin workflow:
    - Admin can mark teachers as present or absent for specific dates
    - This helps in managing substitute teachers or rescheduling classes
    - is_present = True means teacher is available, False means absent
    """
    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="teacher_availabilities",
        help_text="Timetable for which this availability is tracked.",
    )
    
    teacher = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.ROLE_TEACHER},
        related_name="teacher_availabilities",
        help_text="Teacher whose availability is being tracked.",
    )
    
    date = models.DateField(
        help_text="Date for which availability is being tracked.",
    )
    
    is_present = models.BooleanField(
        default=True,
        help_text="True if teacher is present, False if absent.",
    )
    
    reason = models.TextField(
        blank=True,
        help_text="Optional reason for absence (if is_present = False).",
    )

    class Meta:
        unique_together = ("timetable", "teacher", "date")
        ordering = ["date", "teacher__username"]
        verbose_name = "Teacher Availability"
        verbose_name_plural = "Teacher Availabilities"

    def __str__(self) -> str:
        status = "Present" if self.is_present else "Absent"
        return f"{self.teacher.username} - {self.date} - {status}"


class TeacherSlotAvailability(TimeStampedModel):
    """
    Weekly teacher availability per slot.

    - By default, a teacher is AVAILABLE in all slots.
    - In admin UI you list all slots and allow Admin to click a slot
      to toggle it to "unavailable".
    - Optimisation code can then build a structure like:

      available_slots = {
          'mon': {'m1': '8-9.30', 'm2': '9.40-11.10', ...},
          'tue': {...},
      }

    This model is "modular": it is not tied to a single batch.
    The same availability is reused for timetable generation,
    batch-wise load calculation, etc.
    """

    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="weekly_teacher_availabilities",
        help_text="Timetable (date range) this weekly availability pattern belongs to.",
    )

    teacher = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.ROLE_TEACHER},
        related_name="weekly_slot_availabilities",
        help_text="Teacher whose weekly slot availability this record describes.",
    )

    day_slot = models.ForeignKey(
        DaySlot,
        on_delete=models.CASCADE,
        related_name="teacher_availabilities",
        help_text="Specific day + slot (e.g. Monday m1) for this availability.",
    )

    # Default = True (available). Admin can click to make it False (unavailable).
    is_available = models.BooleanField(
        default=True,
        help_text="True if the teacher is available in this slot; False if blocked.",
    )

    class Meta:
        unique_together = ("timetable", "teacher", "day_slot")
        ordering = ["teacher__username", "day_slot__day", "day_slot__slot_number"]
        verbose_name = "Teacher Slot Availability"
        verbose_name_plural = "Teacher Slot Availabilities"

    def __str__(self) -> str:
        status = "Available" if self.is_available else "Unavailable"
        return f"{self.teacher.username} - {self.day_slot} - {status}"
    
    def save(self, *args, **kwargs):
        """Override save to call full_clean() which triggers clean() validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        """
        Prevent the same teacher being marked AVAILABLE in two overlapping
        timetables at the same real-world time within the same center.

        Rules:
        - If this record is_available=True
        - And there exists another TeacherSlotAvailability for the SAME teacher
          with:
            * same weekday (day_slot.day)
            * same start/end time
            * same center (timetable.center)
            * timetable date ranges that overlap
        then we raise a ValidationError.

        This ensures a teacher cannot be available in two timetables at the same
        time slot within the same center.
        """
        super().clean()

        if not self.is_available or not self.teacher_id or not self.day_slot_id:
            return

        # Ensure timetable and day_slot are loaded
        if not self.timetable_id or not self.day_slot_id:
            return
        
        # Load timetable with center if not already loaded
        if not hasattr(self, 'timetable') or not hasattr(self.timetable, 'center'):
            self.timetable = Timetable.objects.select_related('center').get(pk=self.timetable_id)
        
        # Load day_slot if not already loaded
        if not hasattr(self, 'day_slot') or not hasattr(self.day_slot, 'day'):
            self.day_slot = DaySlot.objects.get(pk=self.day_slot_id)
        
        center = self.timetable.center

        # Find other slots for same teacher, same weekday + time, same center
        qs = (
            TeacherSlotAvailability.objects.select_related("day_slot", "timetable", "timetable__center")
            .filter(
                teacher=self.teacher,
                is_available=True,
                day_slot__day=self.day_slot.day,
                day_slot__start_time=self.day_slot.start_time,
                day_slot__end_time=self.day_slot.end_time,
                timetable__center=center,
            )
            .exclude(pk=self.pk)
        )

        # Filter further by overlapping timetable date range
        conflicting = []
        for other in qs:
            t1_start, t1_end = self.timetable.from_date, self.timetable.to_date
            t2_start, t2_end = other.timetable.from_date, other.timetable.to_date
            if t1_start <= t2_end and t2_start <= t1_end:
                conflicting.append(other)

        if conflicting:
            raise ValidationError(
                {
                    "is_available": (
                        f"This teacher is already available in timetable "
                        f"'{conflicting[0].timetable}' for the same day and time range "
                        f"with overlapping dates in the same center. Cannot be available in two places."
                    )
                }
            )


class BatchFacultyLoad(TimeStampedModel):
    """
    Batch-wise faculty load configuration.

    This mirrors your Excel sheet:
    - Faculty (teacher)
    - No. of Lectures (total in timetable period or per week)
    - Min No. of Lectures per day
    - Max No. of Lectures per day
    - Batch code

    The model is reusable for ANY optimisation logic and not tied
    to a specific algorithm implementation.
    """

    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="batch_faculty_loads",
        help_text="Timetable for which this faculty load is defined.",
    )

    teacher = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        limit_choices_to={"role": User.ROLE_TEACHER},
        related_name="batch_faculty_loads",
        help_text="Faculty / teacher.",
    )

    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="faculty_loads",
        help_text="Batch to which this load configuration applies.",
    )

    total_lectures = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Planned number of lectures for this teacher in this batch.",
    )

    # Number of FREE lectures for this teacher in this batch.
    # These are normally the trial / demo classes that admin configures
    # at the moment they add the teacher for a batch.
    free_lectures = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text=(
            "Number of free/demo lectures for this teacher in this batch. "
            "Set when assigning teacher to the batch."
        ),
    )

    min_lectures_per_day = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Minimum number of lectures per day for this teacher in this batch.",
    )

    max_lectures_per_day = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Maximum number of lectures per day for this teacher in this batch.",
    )

    max_lectures_per_week = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="Maximum number of lectures per week for this teacher in this batch.",
    )

    class Meta:
        unique_together = ("timetable", "teacher", "batch")
        ordering = ["batch__code", "teacher__username"]
        verbose_name = "Batch Faculty Load"
        verbose_name_plural = "Batch Faculty Loads"

    def __str__(self) -> str:
        return f"{self.batch.code} - {self.teacher.username} ({self.total_lectures} lectures)"


class FixedSlot(TimeStampedModel):
    """
    Fixed (locked) slots for a timetable.

    This matches your `fixed_slots` dictionary idea:

        fixed_slots[day_key][slot_code][batch_code] = (subject, teacher_code) or None

    - If `subject` and `teacher` are set, that slot is FIXED and optimisation
      code must not change it.
    - If both are null, the slot is fixed as "free / exam / something else"
      and still must not be overwritten automatically.

    Admin can change these records via a dedicated API / admin screen
    if they want to override a fixed slot manually.
    """

    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="fixed_slots",
        help_text="Timetable this fixed slot belongs to.",
    )

    day_slot = models.ForeignKey(
        DaySlot,
        on_delete=models.CASCADE,
        related_name="fixed_slots",
        help_text="Specific day + slot that is fixed.",
    )

    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="fixed_slots",
        help_text="Batch affected by this fixed slot.",
    )

    subject = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            "Subject code/name for this fixed slot. "
            "Leave empty if this is a free / exam / non-teaching slot."
        ),
    )

    teacher = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role": User.ROLE_TEACHER},
        related_name="fixed_slots",
        help_text="Teacher code for this fixed slot (optional if free/exam).",
    )

    # When true, optimisation / auto-generation logic MUST NOT change this row.
    is_locked = models.BooleanField(
        default=True,
        help_text=(
            "If true, this slot is locked and cannot be modified by "
            "automatic timetable generation logic."
        ),
    )

    class Meta:
        unique_together = ("timetable", "day_slot", "batch")
        ordering = ["day_slot__day", "day_slot__slot_number", "batch__code"]
        verbose_name = "Fixed Slot"
        verbose_name_plural = "Fixed Slots"

    def __str__(self) -> str:
        label = self.subject or "Free / Exam"
        return f"{self.day_slot} - {self.batch.code} - {label}"


class TimetableHoliday(TimeStampedModel):
    """
    Represents a holiday / non-teaching day in a timetable.

    Admin can mark specific calendar dates as holidays (full day),
    independent of weekly DaySlot patterns.
    """

    timetable = models.ForeignKey(
        Timetable,
        on_delete=models.CASCADE,
        related_name="holidays",
        help_text="Timetable this holiday belongs to.",
    )

    date = models.DateField(
        help_text="Calendar date of the holiday.",
    )

    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional description, e.g. 'Independence Day', 'Exam Day'.",
    )

    is_full_day = models.BooleanField(
        default=True,
        help_text="True if entire day is holiday; False if partial (handled by slots).",
    )

    class Meta:
        unique_together = ("timetable", "date")
        ordering = ["date"]
        verbose_name = "Timetable Holiday"
        verbose_name_plural = "Timetable Holidays"

    def __str__(self) -> str:
        return f"{self.date} - {self.description or 'Holiday'}"
