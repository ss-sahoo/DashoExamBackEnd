from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Institute, UserPermission, InstituteSettings, InstituteInvitation, DeviceSession


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = ['name', 'domain', 'contact_email', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'domain', 'contact_email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'get_full_name', 'role', 'institute', 'is_verified', 'is_active', 'created_at']
    list_filter = ['role', 'institute', 'is_verified', 'is_active', 'created_at']
    search_fields = ['email', 'first_name', 'last_name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'phone', 'profile_picture')}),
        ('Institute & Role', {'fields': ('institute', 'role', 'is_verified')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'institute', 'role', 'password1', 'password2'),
        }),
    )
    
    ordering = ['-created_at']


@admin.register(UserPermission)
class UserPermissionAdmin(admin.ModelAdmin):
    list_display = ['user', 'permission_type', 'granted_by', 'is_active', 'granted_at']
    list_filter = ['permission_type', 'is_active', 'granted_at']
    search_fields = ['user__email', 'permission_type']
    readonly_fields = ['granted_at']


@admin.register(InstituteSettings)
class InstituteSettingsAdmin(admin.ModelAdmin):
    list_display = ['institute', 'allow_student_registration', 'require_email_verification', 'exam_security_level']
    list_filter = ['allow_student_registration', 'require_email_verification', 'exam_security_level']
    search_fields = ['institute__name']


@admin.register(InstituteInvitation)
class InstituteInvitationAdmin(admin.ModelAdmin):
    list_display = ['institute', 'email', 'role', 'status', 'invited_by', 'expires_at', 'created_at']
    list_filter = ['status', 'role', 'institute']
    search_fields = ['email', 'institute__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(DeviceSession)
class DeviceSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'device_type', 'browser', 'os', 'is_active', 'last_activity', 'created_at']
    list_filter = ['is_active', 'device_type', 'created_at']
    search_fields = ['user__email', 'device_fingerprint', 'ip_address']
    readonly_fields = ['created_at', 'last_activity', 'device_fingerprint']
    ordering = ['-last_activity']
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'is_active')
        }),
        ('Device Information', {
            'fields': ('device_fingerprint', 'device_type', 'browser', 'os', 'screen_resolution', 'timezone')
        }),
        ('Network Information', {
            'fields': ('ip_address', 'user_agent')
        }),
        ('Session Timing', {
            'fields': ('created_at', 'last_activity', 'expires_at')
        }),
    )