"""
Management command to create a super admin user with phone number.

Usage:
    python manage.py createsuperadmin --name "John Doe" --phone "9876543210" --email "admin@example.com"
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from timetable_account.models import User


class Command(BaseCommand):
    help = "Create a super admin user with name and phone number"

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help="Full name of the super admin",
        )
        parser.add_argument(
            "--phone",
            type=str,
            required=True,
            help="Phone number of the super admin",
        )
        parser.add_argument(
            "--email",
            type=str,
            required=False,
            help="Email address (optional)",
        )
        parser.add_argument(
            "--username",
            type=str,
            required=False,
            help="Username (optional, will auto-generate if not provided)",
        )

    def handle(self, *args, **options):
        name = options["name"]
        phone = options["phone"]
        email = options.get("email", "")
        username = options.get("username")

        # Auto-generate username if not provided
        if not username:
            # Use first name + last name initials, or phone number
            name_parts = name.strip().split()
            if len(name_parts) >= 2:
                username = f"{name_parts[0].lower()}{name_parts[-1][0].lower()}"
            else:
                username = name_parts[0].lower()
            
            # Ensure uniqueness
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

        # Check if username already exists
        if User.objects.filter(username=username).exists():
            raise CommandError(f"Username '{username}' already exists.")

        # Check if phone already exists
        if User.objects.filter(phone_number=phone).exists():
            raise CommandError(f"Phone number '{phone}' already exists.")

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=None,  # Will be set via set_password
                    first_name=name.split()[0] if name.split() else name,
                    last_name=" ".join(name.split()[1:]) if len(name.split()) > 1 else "",
                    phone_number=phone,
                    role=User.ROLE_SUPER_ADMIN,
                    is_staff=True,
                    is_superuser=True,
                )
                
                # Generate a secure default password
                # Format: SuperAdmin@<current_year>
                from datetime import datetime
                current_year = datetime.now().year
                default_password = f"SuperAdmin@{current_year}"
                
                user.set_password(default_password)
                user.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n✅ Super Admin created successfully!\n"
                        f"   Username: {username}\n"
                        f"   Password: {default_password}\n"
                        f"   Phone: {phone}\n"
                        f"   Role: SUPER_ADMIN\n"
                        f"\n⚠️  Please change the password after first login.\n"
                    )
                )
        except Exception as e:
            raise CommandError(f"Error creating super admin: {str(e)}")


