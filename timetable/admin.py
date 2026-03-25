"""
Django admin configuration for timetable models.

This admin interface allows:
1. Creating timetables with date ranges and free classes
2. Managing day-wise slots with different timings for each day
3. Assigning batches and teachers to slots
4. Setting teacher constraints (min/max classes)
5. Tracking teacher availability (present/absent)
"""

from django.contrib import admin
from .models import (
    Timetable,
    DaySlot,
    TimetableEntry,
    TeacherConstraint,
    TeacherAvailability,
    TeacherSlotAvailability,
    BatchFacultyLoad,
    FixedSlot,
    TimetableHoliday,
)


@admin.register(Timetable)
class TimetableAdmin(admin.ModelAdmin):
    """
    Admin interface for Timetable model.
    
    Admin can:
    - Select center, from_date, to_date
    - Set number of free classes
    - View all day slots and entries for this timetable
    """
    list_display = (
        "center",
        "from_date",
        "to_date",
        "free_classes_count",
        "is_active",
        "created_at",
    )
    list_filter = ("center", "is_active", "from_date", "to_date")
    search_fields = ("center__name", "description")
    date_hierarchy = "from_date"
    fieldsets = (
        ("Basic Information", {
            "fields": ("center", "from_date", "to_date", "is_active")
        }),
        ("Free Classes", {
            "fields": ("free_classes_count",),
            "description": "Number of free classes in this timetable period."
        }),
        ("Additional Information", {
            "fields": ("description",),
        }),
    )


@admin.register(DaySlot)
class DaySlotAdmin(admin.ModelAdmin):
    """
    Admin interface for DaySlot model.
    
    Admin can:
    - Create slots for each day (Monday, Tuesday, etc.)
    - Set different start_time and end_time for each day
    - Set slot_number (1, 2, 3...) for ordering
    - Free class status is automatically managed based on timetable's free_classes_count
    """
    list_display = (
        "timetable",
        "day",
        "slot_number",
        "start_time",
        "end_time",
        "is_free_class",
    )
    list_filter = ("timetable", "day", "is_free_class")
    search_fields = ("timetable__center__name",)
    ordering = ("timetable", "day", "slot_number")
    fieldsets = (
        ("Timetable Information", {
            "fields": ("timetable", "day", "slot_number")
        }),
        ("Time Information", {
            "fields": ("start_time", "end_time", "is_free_class")
        }),
    )


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    """
    Admin interface for TimetableEntry model.
    
    Admin can:
    - Assign batches to day slots (no fixed teacher here)
    - Specify subject and room number
    - View complete timetable skeleton (teachers are decided later
      by optimisation logic or via FixedSlot records).
    """
    list_display = (
        "day_slot",
        "batch",
        "subject",
        "room_number",
        "get_day",
        "get_time",
    )
    list_filter = (
        "day_slot__timetable",
        "day_slot__day",
        "batch",
        "subject",
    )
    search_fields = (
        "batch__code",
        "batch__name",
        "subject",
    )
    ordering = ("day_slot__day", "day_slot__slot_number", "batch__code")
    fieldsets = (
        ("Slot Information", {
            "fields": ("day_slot",)
        }),
        ("Class Assignment", {
            "fields": ("batch", "subject", "room_number")
        }),
    )
    
    def get_day(self, obj):
        """Display day of the week."""
        return obj.day_slot.get_day_display()
    get_day.short_description = "Day"
    
    def get_time(self, obj):
        """Display time slot."""
        return f"{obj.day_slot.start_time} - {obj.day_slot.end_time}"
    get_time.short_description = "Time"


@admin.register(TeacherConstraint)
class TeacherConstraintAdmin(admin.ModelAdmin):
    """
    Admin interface for TeacherConstraint model.
    
    Admin can:
    - Set minimum number of classes per teacher
    - Set maximum number of classes per teacher
    - Ensure fair workload distribution
    """
    list_display = (
        "timetable",
        "teacher",
        "min_classes",
        "max_classes",
    )
    list_filter = ("timetable", "teacher")
    search_fields = (
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
        "timetable__center__name",
    )
    ordering = ("timetable", "teacher__username")
    fieldsets = (
        ("Timetable and Teacher", {
            "fields": ("timetable", "teacher")
        }),
        ("Class Constraints", {
            "fields": ("min_classes", "max_classes"),
            "description": (
                "Set the minimum and maximum number of classes "
                "this teacher should teach per week."
            )
        }),
    )


@admin.register(TeacherAvailability)
class TeacherAvailabilityAdmin(admin.ModelAdmin):
    """
    Admin interface for TeacherAvailability model.
    
    Admin can:
    - Mark teachers as present or absent for specific dates
    - Add reason for absence
    - Track teacher availability throughout the timetable period
    """
    list_display = (
        "timetable",
        "teacher",
        "date",
        "is_present",
        "reason",
    )
    list_filter = (
        "timetable",
        "teacher",
        "is_present",
        "date",
    )
    search_fields = (
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
        "reason",
        "timetable__center__name",
    )
    date_hierarchy = "date"
    ordering = ("date", "teacher__username")
    fieldsets = (
        ("Timetable and Teacher", {
            "fields": ("timetable", "teacher", "date")
        }),
        ("Availability Status", {
            "fields": ("is_present", "reason"),
            "description": (
                "Mark teacher as present or absent. "
                "If absent, provide a reason."
            )
        }),
    )


@admin.register(TeacherSlotAvailability)
class TeacherSlotAvailabilityAdmin(admin.ModelAdmin):
    """Admin for weekly slot-level teacher availability."""

    list_display = ("timetable", "teacher", "day_slot", "is_available")
    list_filter = ("timetable", "teacher", "day_slot__day", "is_available")
    search_fields = (
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
        "day_slot__timetable__center__name",
    )
    ordering = ("teacher__username", "day_slot__day", "day_slot__slot_number")


@admin.register(BatchFacultyLoad)
class BatchFacultyLoadAdmin(admin.ModelAdmin):
    """Admin for batch-wise faculty load configuration."""

    list_display = (
        "timetable",
        "batch",
        "teacher",
        "total_lectures",
        "min_lectures_per_day",
        "max_lectures_per_day",
    )
    list_filter = ("timetable", "batch", "teacher")
    search_fields = (
        "batch__code",
        "batch__name",
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
    )
    ordering = ("batch__code", "teacher__username")


@admin.register(FixedSlot)
class FixedSlotAdmin(admin.ModelAdmin):
    """Admin for fixed (locked) timetable slots."""

    list_display = ("timetable", "day_slot", "batch", "subject", "teacher", "is_locked")
    list_filter = ("timetable", "day_slot__day", "batch", "teacher", "is_locked")
    search_fields = (
        "batch__code",
        "batch__name",
        "teacher__username",
        "teacher__first_name",
        "teacher__last_name",
        "subject",
    )
    ordering = ("day_slot__day", "day_slot__slot_number", "batch__code")


@admin.register(TimetableHoliday)
class TimetableHolidayAdmin(admin.ModelAdmin):
    """Admin for timetable holidays."""

    list_display = ("timetable", "date", "description", "is_full_day")
    list_filter = ("timetable", "is_full_day", "date")
    search_fields = ("description", "timetable__center__name")
    ordering = ("date",)
