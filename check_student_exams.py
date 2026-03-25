#!/usr/bin/env python
"""
Check what exams are available for the student
"""

import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User
from exams.models import Exam, ExamAttempt
from django.utils import timezone
from django.db.models import Q

# Get the student
user = User.objects.get(email='shradha@examflow.com')
print(f"Student: {user.email}")
print(f"Role: {user.role}")
print(f"Institute: {user.institute}")
print(f"Center: {user.center if hasattr(user, 'center') else 'N/A'}")
print("=" * 60)

now = timezone.now()

# Check available exams
print("\n1. AVAILABLE EXAMS (published/active, within time window)")
print("-" * 60)
available_exams = Exam.objects.filter(
    institute=user.institute,
    status__in=['published', 'active'],
    start_date__lte=now,
    end_date__gte=now
).filter(
    Q(is_public=True) | Q(allowed_users=user)
).distinct()

print(f"Found {available_exams.count()} available exams:")
for exam in available_exams:
    print(f"  - {exam.title}")
    print(f"    Status: {exam.status}")
    print(f"    Start: {exam.start_date}")
    print(f"    End: {exam.end_date}")
    print(f"    Public: {exam.is_public}")
    print(f"    Max attempts: {exam.max_attempts}")
    
    # Check attempts
    attempts = ExamAttempt.objects.filter(student=user, exam=exam)
    print(f"    Student attempts: {attempts.count()}")
    for attempt in attempts:
        print(f"      - Attempt {attempt.id}: {attempt.status}")

# Check scheduled exams (future)
print("\n2. SCHEDULED EXAMS (future exams)")
print("-" * 60)
scheduled_exams = Exam.objects.filter(
    institute=user.institute,
    status__in=['published', 'active'],
    start_date__gt=now
).filter(
    Q(is_public=True) | Q(allowed_users=user)
).distinct()

print(f"Found {scheduled_exams.count()} scheduled exams:")
for exam in scheduled_exams:
    print(f"  - {exam.title}")
    print(f"    Start: {exam.start_date}")
    print(f"    End: {exam.end_date}")

# Check ongoing attempts
print("\n3. ONGOING EXAMS (in progress)")
print("-" * 60)
ongoing_attempts = ExamAttempt.objects.filter(
    student=user,
    status='in_progress'
).select_related('exam')

print(f"Found {ongoing_attempts.count()} ongoing attempts:")
for attempt in ongoing_attempts:
    print(f"  - {attempt.exam.title}")
    print(f"    Started: {attempt.started_at}")
    print(f"    Time spent: {attempt.time_spent} seconds")

# Check completed exams
print("\n4. COMPLETED EXAMS")
print("-" * 60)
completed_attempts = ExamAttempt.objects.filter(
    student=user,
    status__in=['submitted', 'auto_submitted']
).select_related('exam').order_by('-submitted_at')[:10]

print(f"Found {completed_attempts.count()} completed attempts:")
for attempt in completed_attempts:
    print(f"  - {attempt.exam.title}")
    print(f"    Submitted: {attempt.submitted_at}")
    print(f"    Score: {attempt.score}/{attempt.exam.total_marks}")
    print(f"    Percentage: {attempt.percentage}%")

# Check ALL exams in the institute
print("\n5. ALL EXAMS IN INSTITUTE")
print("-" * 60)
all_exams = Exam.objects.filter(institute=user.institute)
print(f"Total exams in institute: {all_exams.count()}")
for exam in all_exams:
    print(f"  - {exam.title}")
    print(f"    Status: {exam.status}")
    print(f"    Public: {exam.is_public}")
    print(f"    Start: {exam.start_date}")
    print(f"    End: {exam.end_date}")
    print(f"    Allowed users: {exam.allowed_users.count()}")
    if user in exam.allowed_users.all():
        print(f"    ✓ Student is in allowed_users")
    else:
        print(f"    ✗ Student NOT in allowed_users")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Available exams: {available_exams.count()}")
print(f"Scheduled exams: {scheduled_exams.count()}")
print(f"Ongoing attempts: {ongoing_attempts.count()}")
print(f"Completed attempts: {completed_attempts.count()}")
print(f"Total exams in institute: {all_exams.count()}")
