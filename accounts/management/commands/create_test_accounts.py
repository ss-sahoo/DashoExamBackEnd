"""
Management command to create test accounts for Super Admin, Admin, and Teacher
"""
from django.core.management.base import BaseCommand
from django.db import transaction, connection
from django.contrib.auth import get_user_model
from accounts.models import Institute
from django.contrib.auth.hashers import make_password
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = 'Create test accounts: Super Admin, Admin, and Teacher'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('🚀 Creating test accounts...'))
        
        # Get first institute ID using raw SQL to avoid model field issues
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT id FROM accounts_institute LIMIT 1")
            row = cursor.fetchone()
            if not row:
                self.stdout.write(self.style.ERROR('No institute found. Please create one first.'))
                return
            institute_id = row[0]
            self.stdout.write(self.style.WARNING(f'Using institute ID: {institute_id}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error getting institute: {e}'))
            return

        # Create users - handle each independently to avoid transaction issues
        users_to_create = [
                {
                    'email': 'superadmin@examflow.com',
                    'username': 'superadmin_test',
                    'first_name': 'Super',
                    'last_name': 'Admin',
                    'role': 'super_admin',
                    'password': 'admin123',
                    'is_staff': True,
                    'is_superuser': True,
                },
                {
                    'email': 'admin@examflow.com',
                    'username': 'admin_test',
                    'first_name': 'Center',
                    'last_name': 'Admin',
                    'role': 'ADMIN',
                    'password': 'admin123',
                    'is_staff': True,
                    'is_superuser': False,
                },
                {
                    'email': 'teacher@examflow.com',
                    'username': 'teacher_test',
                    'first_name': 'John',
                    'last_name': 'Teacher',
                    'role': 'teacher',
                    'password': 'teacher123',
                    'teacher_code': 'TCH-001',
                    'is_staff': False,
                    'is_superuser': False,
                },
            ]

        for user_data in users_to_create:
            email = user_data['email']
            
            try:
                with transaction.atomic():
                    # Check if user exists
                    cursor.execute("SELECT id FROM accounts_user WHERE email = %s", [email])
                    existing = cursor.fetchone()
                    
                    if existing:
                        user_id = existing[0]
                        # Update password
                        hashed_password = make_password(user_data['password'])
                        cursor.execute(
                            "UPDATE accounts_user SET password = %s WHERE id = %s",
                            [hashed_password, user_id]
                        )
                        if 'teacher_code' in user_data:
                            cursor.execute(
                                "UPDATE accounts_user SET teacher_code = %s WHERE id = %s",
                                [user_data['teacher_code'], user_id]
                            )
                        self.stdout.write(self.style.WARNING(f'ℹ️  User already exists: {email} (password updated)'))
                    else:
                        # Use raw SQL to insert user to avoid model field type mismatches
                        hashed_password = make_password(user_data['password'])
                        now = timezone.now()
                        
                        cursor.execute("""
                            INSERT INTO accounts_user (
                                password, username, first_name, last_name, email,
                                role, institute_id, is_active, is_verified, is_staff, is_superuser,
                                phone, date_joined, created_at, updated_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, [
                            hashed_password,
                            user_data['username'],
                            user_data['first_name'],
                            user_data['last_name'],
                            email,
                            user_data['role'],
                            institute_id,
                            True,  # is_active
                            True,  # is_verified
                            user_data.get('is_staff', False),
                            user_data.get('is_superuser', False),
                            '',    # phone (empty string)
                            now,   # date_joined
                            now,   # created_at
                            now,   # updated_at
                        ])
                        user_id = cursor.fetchone()[0]
                        
                        # Update teacher_code if provided
                        if 'teacher_code' in user_data:
                            cursor.execute(
                                "UPDATE accounts_user SET teacher_code = %s WHERE id = %s",
                                [user_data['teacher_code'], user_id]
                            )
                        
                        user = User.objects.get(id=user_id)
                        
                        # Update teacher_code if provided
                        if 'teacher_code' in user_data:
                            user.teacher_code = user_data['teacher_code']
                            user.save(update_fields=['teacher_code'])
                        
                        self.stdout.write(self.style.SUCCESS(f'✅ Created: {email}'))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'❌ Error creating {email}: {e}'))
                # Continue with next user

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('🎉 Test accounts created successfully!'))
        self.stdout.write(self.style.SUCCESS('=' * 70))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('📋 Login Credentials:'))
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('  Super Admin:'))
        self.stdout.write(f'    Email: superadmin@examflow.com')
        self.stdout.write(f'    Username: superadmin')
        self.stdout.write(f'    Password: admin123')
        self.stdout.write(f'    Dashboard: /superadmin/dashboard')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('  Admin (Center Admin):'))
        self.stdout.write(f'    Email: admin@examflow.com')
        self.stdout.write(f'    Username: admin')
        self.stdout.write(f'    Password: admin123')
        self.stdout.write(f'    Dashboard: /center-admin/dashboard')
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('  Teacher:'))
        self.stdout.write(f'    Email: teacher@examflow.com')
        self.stdout.write(f'    Username: teacher')
        self.stdout.write(f'    Teacher Code: TCH-001')
        self.stdout.write(f'    Password: teacher123')
        self.stdout.write(f'    Dashboard: /teacher')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('🔗 Login URL: http://localhost:5173/login'))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('⚠️  IMPORTANT: Change passwords in production!'))
        self.stdout.write('')
