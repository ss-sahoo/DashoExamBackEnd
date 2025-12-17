from django.contrib import admin

from .models import User, Institute, Center, Program, Batch, Enrollment


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "role", "center")
    list_filter = ("role", "center")
    search_fields = ("username", "email")


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = ("name", "head_office_location", "created_at")
    search_fields = ("name", "head_office_location")


@admin.register(Center)
class CenterAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "institute", "created_at")
    list_filter = ("city", "institute")
    search_fields = ("name", "city")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "center", "category", "is_active")
    list_filter = ("center", "category", "is_active")
    search_fields = ("name", "center__name")


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "program", "start_date", "end_date")
    list_filter = ("program",)
    search_fields = ("code", "name", "program__name")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "batch", "status", "joined_on")
    list_filter = ("status", "batch")
    search_fields = ("student__username", "batch__name")



