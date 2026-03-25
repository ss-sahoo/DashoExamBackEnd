#!/usr/bin/env python
"""
Quick script to delete a pattern by name
Usage: python delete_pattern.py "Pattern Name"
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from patterns.models import ExamPattern

def delete_pattern(pattern_name):
    """Delete a pattern by name"""
    patterns = ExamPattern.objects.filter(name=pattern_name)
    
    if not patterns.exists():
        print(f" No pattern found with name: '{pattern_name}'")
        print("\n📋 Available patterns:")
        for p in ExamPattern.objects.all().order_by('institute', 'name'):
            print(f"   - '{p.name}' (Institute: {p.institute.name})")
        return False
    
    print(f"\n🗑️  Found {patterns.count()} pattern(s) with name '{pattern_name}':")
    for p in patterns:
        print(f"   ID: {p.id} | Institute: {p.institute.name} | Sections: {p.sections.count()}")
    
    confirm = input("\n⚠️  Delete these pattern(s)? (yes/no): ")
    if confirm.lower() == 'yes':
        count = patterns.count()
        patterns.delete()
        print(f" Deleted {count} pattern(s) successfully!")
        return True
    else:
        print(" Deletion cancelled.")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python delete_pattern.py 'Pattern Name'")
        print("\n📋 Available patterns:")
        for p in ExamPattern.objects.all().order_by('institute', 'name'):
            print(f"   - '{p.name}' (Institute: {p.institute.name})")
        sys.exit(1)
    
    pattern_name = sys.argv[1]
    delete_pattern(pattern_name)

