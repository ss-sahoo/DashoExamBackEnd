"""
Bootstrap command to set up initial system with platform institute and super admin
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import Institute, User


class Command(BaseCommand):
    help = 'Bootstrap the system with platform institute and super admin'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            default='admin@examflow.com',
            help='Super admin email address'
        )
        parser.add_argument(
            '--password',
            type=str,
            default='admin123',
            help='Super admin password'
        )
        parser.add_argument(
            '--first-name',
            type=str,
            default='Super',
            help='Super admin first name'
        )
        parser.add_argument(
            '--last-name',
            type=str,
            default='Admin',
            help='Super admin last name'
        )

    def handle(self, *args, **options):
        email = options['email']
        password = options['password']
        first_name = options['first_name']
        last_name = options['last_name']
        
        # Extract domain from email
        domain = email.split('@')[1]
        
        self.stdout.write(self.style.WARNING('🚀 Starting system bootstrap...'))
        
        with transaction.atomic():
            # 1. Create Platform Institute (for super admins and system users)
            platform_institute, created = Institute.objects.get_or_create(
                domain=domain,
                defaults={
                    'name': 'ExamFlow Platform',
                    'description': 'Platform administration institute for system-level users',
                    'contact_email': email,
                    'is_active': True,
                    'is_verified': True,
                }
            )
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'✅ Created platform institute: {platform_institute.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'ℹ️  Platform institute already exists: {platform_institute.name}'))
            
            # 2. Create Super Admin User
            username = email.split('@')[0]
            super_admin, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': username,
                    'first_name': first_name,
                    'last_name': last_name,
                    'role': 'super_admin',
                    'institute': platform_institute,
                    'is_active': True,
                    'is_staff': True,
                    'is_superuser': True,
                    'is_verified': True,
                }
            )
            
            if created:
                super_admin.set_password(password)
                super_admin.save()
                self.stdout.write(self.style.SUCCESS(f'✅ Created super admin: {email}'))
                self.stdout.write(self.style.SUCCESS(f'   Password: {password}'))
            else:
                self.stdout.write(self.style.WARNING(f'ℹ️  Super admin already exists: {email}'))
            
            # Update created_by for platform institute
            if created and not platform_institute.created_by:
                platform_institute.created_by = super_admin
                platform_institute.save()
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('🎉 System bootstrap completed!'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('📋 Summary:'))
        self.stdout.write(f'   Institute: {platform_institute.name}')
        self.stdout.write(f'   Domain: {platform_institute.domain}')
        self.stdout.write(f'   Super Admin Email: {email}')
        self.stdout.write(f'   Super Admin Password: {password}')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('🔗 Next Steps:'))
        self.stdout.write('   1. Access Django Admin: http://localhost:8000/admin/')
        self.stdout.write(f'   2. Login with: {email} / {password}')
        self.stdout.write('   3. Create institutes for your organizations')
        self.stdout.write('   4. Users can register with matching email domains')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('⚠️  IMPORTANT: Change the super admin password in production!'))
        self.stdout.write('')

