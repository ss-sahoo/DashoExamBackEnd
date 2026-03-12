import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User

def create_admin_user(email, username, password, role, is_superuser=False):
    try:
        if User.objects.filter(email=email).exists():
            print(f"⚠️ User with email {email} already exists.")
            return
        
        user = User.objects.create_user(
            email=email,
            username=username,
            password=password,
            first_name=username.capitalize(),
            last_name="Admin",
            role=role,
            is_active=True,
            is_verified=True
        )
        
        if is_superuser:
            user.is_superuser = True
            user.is_staff = True
            user.save()
            print(f" Super Admin created: {email}")
        else:
            print(f" Regular Admin created: {email}")
            
    except Exception as e:
        print(f" Error creating user {email}: {e}")

if __name__ == '__main__':
    # Create Super Admin
    create_admin_user(
        email='superadmin@example.com',
        username='superadmin',
        password='Password@123',
        role='super_admin',
        is_superuser=True
    )
    
    # Create Regular Admin
    create_admin_user(
        email='admin@example.com',
        username='admin',
        password='Password@123',
        role='admin',
        is_superuser=False
    )
