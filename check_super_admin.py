import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User

def check_super_admins():
    print("Checking for Super Admins...")
    super_admins = User.objects.filter(role__in=['super_admin', 'SUPER_ADMIN'])
    
    if not super_admins.exists():
        print("❌ No Super Admins found!")
        print("💡 Run 'python manage.py bootstrap_system' to create one.")
    else:
        print(f" Found {super_admins.count()} Super Admin(s):")
        for user in super_admins:
            print(f"   - ID: {user.id}")
            print(f"     Username: {user.username}")
            print(f"     Email: {user.email}")
            print(f"     Active: {user.is_active}")
            print(f"     Last Login: {user.last_login}")
            print("-" * 30)

if __name__ == '__main__':
    check_super_admins()
