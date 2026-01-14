import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User

def reset_password(email, new_password):
    try:
        user = User.objects.get(email=email)
        user.set_password(new_password)
        user.save()
        print(f"✅ Password for {email} has been reset to: {new_password}")
    except User.DoesNotExist:
        print(f"❌ User with email {email} not found.")

if __name__ == '__main__':
    reset_password('admin@demo.edu', 'admin123')
    reset_password('superadmin@examflow.com', 'admin123')
