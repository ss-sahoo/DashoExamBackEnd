#!/usr/bin/env python
"""
Publish exams so students can see them
"""

import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User
from exams.models import Exam

# Get the student
student = User.objects.get(email='shradha@examflow.com')
print(f"Student: {student.email}")
print(f"Institute: {student.institute}")
print("=" * 60)

# Get all draft exams in the institute
draft_exams = Exam.objects.filter(
    institute=student.institute,
    status='draft'
)

print(f"\nFound {draft_exams.count()} draft exams")
print("\nPublishing exams...")
print("-" * 60)

for exam in draft_exams:
    print(f"\nExam: {exam.title}")
    print(f"  Current status: {exam.status}")
    print(f"  Public: {exam.is_public}")
    print(f"  Start: {exam.start_date}")
    print(f"  End: {exam.end_date}")
    
    # Change status to published
    exam.status = 'published'
    exam.save()
    
    print(f"  ✓ Changed status to: {exam.status}")
    
    # Add student to allowed_users if not already there
    if not exam.allowed_users.filter(id=student.id).exists():
        exam.allowed_users.add(student)
        print(f"  ✓ Added student to allowed_users")
    else:
        print(f"  - Student already in allowed_users")

print("\n" + "=" * 60)
print("DONE! Exams are now published and visible to student")
print("=" * 60)

# Verify
print("\nVerification:")
published_exams = Exam.objects.filter(
    institute=student.institute,
    status='published'
)
print(f"Published exams in institute: {published_exams.count()}")
for exam in published_exams:
    print(f"  - {exam.title}")
    print(f"    Student in allowed_users: {student in exam.allowed_users.all()}")
