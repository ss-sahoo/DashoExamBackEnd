#!/usr/bin/env python
"""
Assign student to a center
"""

import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User, Center

# Get the student
student = User.objects.get(email='shradha@examflow.com')
print(f"Student: {student.email}")
print(f"Current center: {student.center}")
print(f"Institute: {student.institute}")
print("=" * 60)

# Get all centers in the student's institute
centers = Center.objects.filter(institute=student.institute)
print(f"\nAvailable centers in {student.institute}:")
for center in centers:
    print(f"  - {center.name} (ID: {center.id})")

if centers.exists():
    # Assign to first center
    first_center = centers.first()
    student.center = first_center
    student.save()
    print(f"\n✓ Assigned student to center: {first_center.name}")
    print(f"  Student can now access center-specific resources")
else:
    print(f"\n⚠ No centers found in institute {student.institute}")
    print("  Create a center first, then assign students to it")

print("\n" + "=" * 60)
print("VERIFICATION")
print("=" * 60)
student.refresh_from_db()
print(f"Student center: {student.center}")
if student.center:
    print(f"Center name: {student.center.name}")
