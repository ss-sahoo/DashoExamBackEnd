import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User, Institute

def setup_default_institute():
    try:
        # Create or get default institute
        institute, created = Institute.objects.get_or_create(
            name="Default Institute",
            defaults={
                'address': 'Head Office',
                'is_active': True,
                'is_verified': True
            }
        )
        
        if created:
            print(f" Created default institute: {institute.name}")
        else:
            print(f"ℹ️ Default institute already exists: {institute.name}")
            
        # Assign institute to administrative users
        users = User.objects.filter(email__in=['superadmin@example.com', 'admin@example.com'])
        for user in users:
            user.institute = institute
            user.save()
            print(f" Assigned {user.email} to {institute.name}")
            
    except Exception as e:
        print(f"❌ Error during setup: {e}")

if __name__ == '__main__':
    setup_default_institute()
