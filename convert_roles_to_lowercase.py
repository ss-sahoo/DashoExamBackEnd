#!/usr/bin/env python3
"""
Convert all uppercase roles to lowercase in the database
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User

def convert_roles():
    """Convert all uppercase roles to lowercase"""
    
    print("=" * 80)
    print("CONVERTING ALL ROLES TO LOWERCASE")
    print("=" * 80)
    
    # Map of uppercase to lowercase roles
    role_mapping = {
        'STUDENT': 'student',
        'TEACHER': 'teacher',
        'ADMIN': 'admin',
        'STAFF': 'staff',
        'SUPER_ADMIN': 'super_admin',
    }
    
    total_fixed = 0
    
    for old_role, new_role in role_mapping.items():
        users = User.objects.filter(role=old_role)
        count = users.count()
        
        if count > 0:
            print(f"\nConverting {count} users from '{old_role}' to '{new_role}'...")
            for user in users:
                user.role = new_role
                user.save()
                print(f"  ✓ {user.username} ({user.email})")
                total_fixed += 1
    
    print(f"\n{'='*80}")
    print(f" DONE! Converted {total_fixed} users to lowercase roles")
    print(f"{'='*80}")
    
    # Verify
    print("\nVerifying...")
    for old_role in role_mapping.keys():
        remaining = User.objects.filter(role=old_role).count()
        if remaining > 0:
            print(f"  ⚠️  Warning: {remaining} users still have role '{old_role}'")
        else:
            print(f"  ✓ No users with role '{old_role}'")
    
    print("\n All roles converted successfully!")

if __name__ == '__main__':
    convert_roles()
