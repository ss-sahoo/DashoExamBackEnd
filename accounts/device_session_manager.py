"""
Device Session Manager Service

Manages device-based login sessions for users to ensure students can only
be logged in on one device at a time.

**Feature: exam-security-enhancements, Property 2: Device conflict detection**
**Validates: Requirements 1.2**
"""

from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from typing import Optional, Dict, Any, Tuple
import hashlib
import logging

from .models import DeviceSession, User

logger = logging.getLogger(__name__)


class DeviceSessionManager:
    """
    Service class for managing device sessions.
    
    Handles session lifecycle including creation, conflict detection,
    invalidation, and cleanup of expired sessions.
    """
    
    # Session expiration time (24 hours)
    SESSION_EXPIRATION_HOURS = 24
    
    @classmethod
    def generate_device_fingerprint(cls, device_info: Dict[str, Any]) -> str:
        """
        Generate a unique device fingerprint from device information.
        
        Args:
            device_info: Dictionary containing device information:
                - user_agent: Browser user agent string
                - screen_resolution: Screen resolution (e.g., "1920x1080")
                - timezone: User's timezone
                
        Returns:
            A unique fingerprint string (SHA256 hash)
            
        **Feature: exam-security-enhancements, Property 33: Device fingerprint composition**
        **Validates: Requirements 8.1**
        """
        # Combine device characteristics
        fingerprint_data = (
            f"{device_info.get('user_agent', '')}"
            f"{device_info.get('screen_resolution', '')}"
            f"{device_info.get('timezone', '')}"
        )
        
        # Generate SHA256 hash
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()
    
    @classmethod
    @transaction.atomic
    def create_session(cls, user: User, device_info: Dict[str, Any], force_logout_others: bool = False) -> DeviceSession:
        """
        Create a new device session for a user.
        
        Args:
            user: User instance
            device_info: Dictionary containing device information:
                - user_agent: Browser user agent string
                - screen_resolution: Screen resolution
                - timezone: User's timezone
                - device_type: Type of device (mobile, desktop, tablet)
                - browser: Browser name and version
                - os: Operating system name and version
                - ip_address: IP address of the device
            force_logout_others: If True, invalidate all other active sessions for this user
                
        Returns:
            Created DeviceSession instance
            
        **Feature: exam-security-enhancements, Property 1: Device session creation on login**
        **Validates: Requirements 1.1**
        """
        # Generate device fingerprint
        device_fingerprint = cls.generate_device_fingerprint(device_info)
        
        # If force_logout_others is True, invalidate all other sessions
        if force_logout_others:
            DeviceSession.objects.filter(
                user=user,
                is_active=True
            ).exclude(
                device_fingerprint=device_fingerprint
            ).update(is_active=False)
            logger.info(f"Invalidated all other sessions for user {user.email}")
        
        # Calculate expiration time
        expires_at = timezone.now() + timedelta(hours=cls.SESSION_EXPIRATION_HOURS)
        
        # Check if session already exists for this fingerprint
        existing_session = DeviceSession.objects.filter(
            device_fingerprint=device_fingerprint
        ).first()
        
        if existing_session:
            # Update existing session
            existing_session.user = user
            existing_session.is_active = True
            existing_session.last_activity = timezone.now()
            existing_session.expires_at = expires_at
            existing_session.ip_address = device_info.get('ip_address', '')
            existing_session.save()
            logger.info(f"Updated existing session for user {user.email} on device {device_fingerprint[:8]}...")
            return existing_session
        
        # Create new session
        session = DeviceSession.objects.create(
            user=user,
            device_fingerprint=device_fingerprint,
            device_type=device_info.get('device_type', 'unknown'),
            browser=device_info.get('browser', 'unknown'),
            os=device_info.get('os', 'unknown'),
            screen_resolution=device_info.get('screen_resolution', 'unknown'),
            timezone=device_info.get('timezone', 'UTC'),
            ip_address=device_info.get('ip_address', '0.0.0.0'),
            user_agent=device_info.get('user_agent', ''),
            is_active=True,
            expires_at=expires_at
        )
        
        logger.info(f"Created new session for user {user.email} on device {device_fingerprint[:8]}...")
        return session
    
    @classmethod
    def get_active_session(cls, user: User) -> Optional[DeviceSession]:
        """
        Get the active device session for a user.
        
        Args:
            user: User instance
            
        Returns:
            Active DeviceSession instance or None if no active session exists
            
        **Feature: exam-security-enhancements, Property 2: Device conflict detection**
        **Validates: Requirements 1.2**
        """
        # Get active session that hasn't expired
        now = timezone.now()
        session = DeviceSession.objects.filter(
            user=user,
            is_active=True,
            expires_at__gt=now
        ).first()
        
        return session
    
    @classmethod
    def check_session_conflict(cls, user: User, device_info: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if there's a session conflict for a user trying to login from a new device.
        
        Args:
            user: User instance
            device_info: Dictionary containing device information
            
        Returns:
            Tuple of (has_conflict: bool, conflict_info: dict or None)
            If has_conflict is True, conflict_info contains:
                - device_type: Type of the conflicting device
                - browser: Browser of the conflicting device
                - os: Operating system of the conflicting device
                - login_timestamp: When the conflicting session was created
                - last_activity: Last activity time of the conflicting session
                - device_fingerprint: Fingerprint of the conflicting device
                - screen_resolution: Screen resolution of the conflicting device
                
        **Feature: exam-security-enhancements, Property 2: Device conflict detection**
        **Validates: Requirements 1.2**
        """
        # Generate fingerprint for the new device
        new_device_fingerprint = cls.generate_device_fingerprint(device_info)
        
        # Get active session
        active_session = cls.get_active_session(user)
        
        # No conflict if no active session or same device
        if not active_session or active_session.device_fingerprint == new_device_fingerprint:
            return False, None
        
        # Return conflict information
        conflict_info = {
            'device_type': active_session.device_type,
            'browser': active_session.browser,
            'os': active_session.os,
            'login_timestamp': active_session.created_at.isoformat(),
            'last_activity': active_session.last_activity.isoformat(),
            'device_fingerprint': active_session.device_fingerprint,
            'screen_resolution': active_session.screen_resolution,
        }
        
        logger.info(f"Device conflict detected for user {user.email}: existing device {active_session.device_fingerprint[:8]}... vs new device {new_device_fingerprint[:8]}...")
        
        return True, conflict_info
    
    @classmethod
    @transaction.atomic
    def invalidate_session(cls, device_fingerprint: str) -> bool:
        """
        Invalidate a device session by device fingerprint.
        
        Args:
            device_fingerprint: Fingerprint of the device session to invalidate
            
        Returns:
            True if session was invalidated, False if session not found
            
        **Feature: exam-security-enhancements, Property 36: Session invalidation on logout**
        **Validates: Requirements 8.4**
        """
        try:
            session = DeviceSession.objects.get(
                device_fingerprint=device_fingerprint,
                is_active=True
            )
            session.is_active = False
            session.save()
            logger.info(f"Invalidated session for device {device_fingerprint[:8]}...")
            return True
        except DeviceSession.DoesNotExist:
            logger.warning(f"Attempted to invalidate non-existent session {device_fingerprint[:8]}...")
            return False
    
    @classmethod
    @transaction.atomic
    def swap_device_session(cls, user: User, old_fingerprint: str, new_device_info: Dict[str, Any]) -> DeviceSession:
        """
        Swap device session: invalidate old session and create new one atomically.
        
        Args:
            user: User instance
            old_fingerprint: Fingerprint of the old device to invalidate
            new_device_info: Device information for the new session
            
        Returns:
            Newly created DeviceSession instance
            
        **Feature: exam-security-enhancements, Property 4: Device session swap atomicity**
        **Validates: Requirements 1.4**
        """
        # Invalidate ALL active sessions for this user (not just the old one)
        # This ensures that if there are multiple sessions, they all get logged out
        DeviceSession.objects.filter(
            user=user,
            is_active=True
        ).update(is_active=False)
        
        logger.info(f"Invalidated all active sessions for user {user.email}")
        
        # Create new session with force_logout_others=False since we already invalidated all
        new_session = cls.create_session(user, new_device_info, force_logout_others=False)
        
        logger.info(f"Swapped device session for user {user.email}")
        return new_session
    
    @classmethod
    def cleanup_expired_sessions(cls) -> int:
        """
        Clean up expired device sessions.
        
        This should be run as a background task (e.g., via Celery or Django management command).
        
        Returns:
            Number of sessions cleaned up
            
        **Feature: exam-security-enhancements, Property 35: Session expiration after inactivity**
        **Validates: Requirements 8.3**
        """
        now = timezone.now()
        
        # Find expired sessions
        expired_sessions = DeviceSession.objects.filter(
            is_active=True,
            expires_at__lte=now
        )
        
        count = expired_sessions.count()
        
        # Mark as inactive
        expired_sessions.update(is_active=False)
        
        logger.info(f"Cleaned up {count} expired device sessions")
        return count
    
    @classmethod
    def update_session_activity(cls, device_fingerprint: str) -> bool:
        """
        Update the last activity timestamp and extend expiration for a session.
        
        Args:
            device_fingerprint: Fingerprint of the device session
            
        Returns:
            True if session was updated, False if session not found
        """
        try:
            session = DeviceSession.objects.get(
                device_fingerprint=device_fingerprint,
                is_active=True
            )
            session.last_activity = timezone.now()
            session.expires_at = timezone.now() + timedelta(hours=cls.SESSION_EXPIRATION_HOURS)
            session.save()
            return True
        except DeviceSession.DoesNotExist:
            return False
