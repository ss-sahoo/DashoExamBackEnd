"""
Management command to create a new institute
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import Institute, User


class Command(BaseCommand):
    help = 'Create a new institute and optionally its first admin'

    def add_arguments(self, parser):
        parser.add_argument('--name', type=str, required=True, help='Institute name')
        parser.add_argument('--domain', type=str, required=True, help='Email domain (e.g., harvard.edu)')
        parser.add_argument('--contact-email', type=str, required=True, help='Contact email')
        parser.add_argument('--description', type=str, default='', help='Institute description')
        parser.add_argument('--address', type=str, default='', help='Institute address')
        parser.add_argument('--phone', type=str, default='', help='Contact phone')
        parser.add_argument('--website', type=str, default='', help='Institute website')
        parser.add_argument('--verified', action='store_true', help='Mark as verified')
        
        # Admin creation options
        parser.add_argument('--create-admin', action='store_true', help='Create first admin user')
        parser.add_argument('--admin-email', type=str, help='Admin email (must match domain)')
        parser.add_argument('--admin-password', type=str, default='admin123', help='Admin password')
        parser.add_argument('--admin-first-name', type=str, default='Admin', help='Admin first name')
        parser.add_argument('--admin-last-name', type=str, default='User', help='Admin last name')

    def handle(self, *args, **options):
        name = options['name']
        domain = options['domain']
        contact_email = options['contact_email']
        
        self.stdout.write(self.style.WARNING(f'🏢 Creating institute: {name}'))
        
        with transaction.atomic():
            # Create Institute
            institute, created = Institute.objects.get_or_create(
                domain=domain,
                defaults={
                    'name': name,
                    'description': options['description'],
                    'contact_email': contact_email,
                    'contact_phone': options['phone'],
                    'address': options['address'],
                    'website': options['website'],
                    'is_active': True,
                    'is_verified': options['verified'],
                }
            )
            
            if not created:
                self.stdout.write(self.style.ERROR(f'❌ Institute with domain "{domain}" already exists!'))
                return
            
            self.stdout.write(self.style.SUCCESS(f' Created institute: {name}'))
            self.stdout.write(f'   Domain: {domain}')
            self.stdout.write(f'   Contact: {contact_email}')
            self.stdout.write(f'   Verified: {options["verified"]}')
            
            # Create Admin User if requested
            if options['create_admin']:
                admin_email = options.get('admin_email')
                
                if not admin_email:
                    # Generate admin email from domain
                    admin_email = f'admin@{domain}'
                
                # Validate email domain matches
                email_domain = admin_email.split('@')[1]
                if email_domain != domain:
                    self.stdout.write(self.style.ERROR(
                        f'❌ Admin email domain "{email_domain}" must match institute domain "{domain}"'
                    ))
                    return
                
                username = admin_email.split('@')[0]
                admin_user, created = User.objects.get_or_create(
                    email=admin_email,
                    defaults={
                        'username': username,
                        'first_name': options['admin_first_name'],
                        'last_name': options['admin_last_name'],
                        'role': 'institute_admin',
                        'institute': institute,
                        'is_active': True,
                        'is_verified': True,
                    }
                )
                
                if created:
                    admin_user.set_password(options['admin_password'])
                    admin_user.save()
                    
                    # Set as created_by
                    institute.created_by = admin_user
                    institute.save()
                    
                    self.stdout.write('')
                    self.stdout.write(self.style.SUCCESS('👤 Created institute admin:'))
                    self.stdout.write(f'   Email: {admin_email}')
                    self.stdout.write(f'   Password: {options["admin_password"]}')
                    self.stdout.write(f'   Role: Institute Admin')
                else:
                    self.stdout.write(self.style.WARNING(f'ℹ️  Admin user already exists: {admin_email}'))
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS(' Institute setup completed!'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('📋 Users can now register with emails matching:'))
        self.stdout.write(f'   @{domain}')
        self.stdout.write('')

