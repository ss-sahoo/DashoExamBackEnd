"""
Device Session Validation Middleware

Validates that the user's device session is still active on every authenticated request.
If the session has been invalidated (e.g., user logged in on another device), 
automatically logout the user.

**Feature: exam-security-enhancements**
**Validates: Requirements 1.4**
"""

from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from .models import DeviceSession
import logging

logger = logging.getLogger(__name__)


class DeviceSessionValidationMiddleware(MiddlewareMixin):
    """
    Middleware to validate device sessions on every authenticated request.
    
    If a user's device session has been invalidated (e.g., they logged in on another device),
    this middleware will return a 401 response with a specific error code.
    """
    
    # Paths that should skip device session validation
    SKIP_PATHS = [
        '/api/auth/login',
        '/api/auth/logout',
        '/api/auth/register',
        '/api/auth/check-device',
        '/api/auth/logout-device',
        '/api/auth/student/login',
        '/api/timetable/auth/',
        '/api/auth/token/refresh',
        '/admin/',
        '/static/',
        '/media/',
    ]
    
    def process_request(self, request):
        """
        Check if the user's device session is still valid.
        """
        # Skip validation for certain paths
        path = request.path
        if any(path.startswith(skip_path) for skip_path in self.SKIP_PATHS):
            return None
        
        # Skip if user is not authenticated
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            # Try to authenticate using JWT
            try:
                jwt_auth = JWTAuthentication()
                auth_result = jwt_auth.authenticate(request)
                if auth_result is not None:
                    request.user, _ = auth_result
                else:
                    return None
            except (InvalidToken, TokenError):
                return None
        
        # Check if user has an active device session
        if request.user.is_authenticated:
            # Get device fingerprint from request headers (if provided by frontend)
            device_fingerprint = request.headers.get('X-Device-Fingerprint')
            
            # If no header provided, try to get from JWT token
            if not device_fingerprint:
                try:
                    jwt_auth = JWTAuthentication()
                    validated_token = jwt_auth.get_validated_token(
                        jwt_auth.get_raw_token(jwt_auth.get_header(request))
                    )
                    device_fingerprint = validated_token.get('device_fingerprint')
                except Exception:
                    # If we can't get device fingerprint, check if user has ANY active session
                    # If they have no active sessions at all, they should be logged out
                    active_sessions = DeviceSession.objects.filter(
                        user=request.user,
                        is_active=True
                    ).exists()
                    
                    if not active_sessions:
                        logger.warning(
                            f"No active device sessions found for user {request.user.email}"
                        )
                        return JsonResponse({
                            'detail': 'Your session has been terminated because you logged in on another device.',
                            'error_code': 'DEVICE_SESSION_INVALID',
                            'logout_required': True
                        }, status=401)
                    
                    # If they have active sessions but we can't verify which device,
                    # allow the request (backward compatibility)
                    return None
            
            if device_fingerprint:
                # Check if this device session is still active
                try:
                    session = DeviceSession.objects.get(
                        user=request.user,
                        device_fingerprint=device_fingerprint
                    )
                    
                    if not session.is_active:
                        logger.warning(
                            f"Inactive device session detected for user {request.user.email} "
                            f"on device {device_fingerprint[:8]}..."
                        )
                        return JsonResponse({
                            'detail': 'Your session has been terminated because you logged in on another device.',
                            'error_code': 'DEVICE_SESSION_INVALID',
                            'logout_required': True
                        }, status=401)
                        
                except DeviceSession.DoesNotExist:
                    # No session found for this device - might have been deleted
                    logger.warning(
                        f"No device session found for user {request.user.email} "
                        f"on device {device_fingerprint[:8]}..."
                    )
                    return JsonResponse({
                        'detail': 'Your session has been terminated because you logged in on another device.',
                        'error_code': 'DEVICE_SESSION_INVALID',
                        'logout_required': True
                    }, status=401)
        
        return None
