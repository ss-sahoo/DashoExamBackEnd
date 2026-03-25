"""
Django management command to cleanup expired device sessions.

This command should be run periodically (e.g., via cron or Celery beat)
to invalidate device sessions that have been inactive for 24 hours.

Usage:
    python manage.py cleanup_expired_sessions

**Feature: exam-security-enhancements, Property 35: Session expiration after inactivity**
**Validates: Requirements 8.3**
"""

from django.core.management.base import BaseCommand
from accounts.device_session_manager import DeviceSessionManager


class Command(BaseCommand):
    help = 'Cleanup expired device sessions (inactive for 24 hours)'

    def handle(self, *args, **options):
        self.stdout.write('Starting device session cleanup...')
        
        # Run cleanup
        count = DeviceSessionManager.cleanup_expired_sessions()
        
        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully cleaned up {count} expired device session(s)'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('No expired sessions found')
            )
