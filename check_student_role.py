#!/usr/bin/env python
"""
Check student role in database
"""

import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User

# Get all users with shradha in email
users = User.objects.filter(email__icontains='shradha')
print(f"Found {users.count()} user(s) with 'shradha' in email:\n")

for user in users:
    print(f"Email: {user.email}")
    print(f"Role: '{user.role}'")
    print(f"Role type: {type(user.role)}")
    print(f"First name: {user.first_name}")
    print(f"Last name: {user.last_name}")
    print(f"Institute: {user.institute}")
    print(f"Is active: {user.is_active}")
    print(f"\nRole comparison:")
    print(f"  role == 'student': {user.role == 'student'}")
    print(f"  role == 'STUDENT': {user.role == 'STUDENT'}")
    print(f"  role.lower() == 'student': {user.role.lower() == 'student'}")
    print("-" * 60)

