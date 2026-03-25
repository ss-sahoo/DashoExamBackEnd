#!/usr/bin/env python
"""
Debug script to check current device sessions.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from accounts.models import User, DeviceSession
from django.utils import timezone

def main():
    print("=" * 80)
    print("Device Sessions Debug")
    print("=" * 80)
    
    # Get all users with active sessions
    users_with_sessions = User.objects.filter(
        device_sessions__is_active=True
    ).distinct()
    
    print(f"\nUsers with active sessions: {users_with_sessions.count()}")
    
    for user in users_with_sessions:
        print(f"\n{'=' * 80}")
        print(f"User: {user.email} ({user.role})")
        print(f"{'=' * 80}")
        
        sessions = DeviceSession.objects.filter(user=user, is_active=True)
        print(f"Active sessions: {sessions.count()}")
        
        for i, session in enumerate(sessions, 1):
            print(f"\nSession {i}:")
            print(f"  - Fingerprint: {session.device_fingerprint}")
            print(f"  - Device Type: {session.device_type}")
            print(f"  - Browser: {session.browser}")
            print(f"  - OS: {session.os}")
            print(f"  - Screen: {session.screen_resolution}")
            print(f"  - IP: {session.ip_address}")
            print(f"  - User Agent: {session.user_agent[:80]}...")
            print(f"  - Created: {session.created_at}")
            print(f"  - Last Activity: {session.last_activity}")
            print(f"  - Expires: {session.expires_at}")
            print(f"  - Active: {session.is_active}")
    
    # Show all sessions (including inactive)
    print(f"\n{'=' * 80}")
    print("All Sessions (Last 10)")
    print(f"{'=' * 80}")
    
    all_sessions = DeviceSession.objects.all().order_by('-created_at')[:10]
    
    for session in all_sessions:
        status = "✓ ACTIVE" if session.is_active else "✗ INACTIVE"
        print(f"\n{status} - {session.user.email}")
        print(f"  - Browser: {session.browser}")
        print(f"  - Fingerprint: {session.device_fingerprint[:16]}...")
        print(f"  - Created: {session.created_at}")
        print(f"  - Last Activity: {session.last_activity}")

if __name__ == '__main__':
    main()
