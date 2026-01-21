#!/usr/bin/env python
"""
Clear all device sessions for a user
"""

import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User, DeviceSession

# Get the student
user = User.objects.get(email='shradha@examflow.com')
print(f"User: {user.email}")
print(f"Role: {user.role}")
print("=" * 60)

# Get all device sessions
sessions = DeviceSession.objects.filter(user=user)
print(f"\nFound {sessions.count()} device session(s)")

# Clear all sessions
print("\n" + "=" * 60)
print("Clearing all device sessions...")
print("=" * 60)

deleted_count = sessions.delete()[0]
print(f"\n✓ Deleted {deleted_count} device session(s)")
print("\nUser can now login fresh without device conflicts!")
