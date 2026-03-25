"""
Django management command to change a user's role.
Usage: python manage.py change_user_role <email_or_username> <new_role>
"""
from django.core.management.base import BaseCommand, CommandError
from accounts.models import User


class Command(BaseCommand):
    help = 'Change a user\'s role'

    def add_arguments(self, parser):
        parser.add_argument('identifier', type=str, help='User email or username')
        parser.add_argument('role', type=str, help='New role (e.g., super_admin, institute_admin, etc.)')

    def handle(self, *args, **options):
        identifier = options['identifier']
        new_role = options['role']
        
        # Get user by email or username
        try:
            user = User.objects.get(email=identifier)
        except User.DoesNotExist:
            try:
                user = User.objects.get(username=identifier)
            except User.DoesNotExist:
                raise CommandError(f'User with email/username "{identifier}" not found.')
        
        old_role = user.role
        user.role = new_role
        user.save()
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully updated user "{user.email}" (username: {user.username}) '
                f'from role "{old_role}" to "{new_role}"'
            )
        )

