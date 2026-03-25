"""
Device Session API Views

Provides REST API endpoints for managing device-based login sessions.

**Feature: exam-security-enhancements**
**Validates: Requirements 1.2, 1.3, 1.4, 1.5**
"""

from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import logging

from .models import DeviceSession
from .device_session_manager import DeviceSessionManager
from .serializers import (
    DeviceSessionSerializer,
    DeviceCheckRequestSerializer,
    DeviceCheckResponseSerializer,
    LogoutDeviceRequestSerializer
)

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@csrf_exempt
def check_device_view(request):
    """
    Check for device conflicts when a user attempts to login.
    
    POST /api/auth/check-device/
    
    Request body:
    {
        "user_agent": "Mozilla/5.0...",
        "screen_resolution": "1920x1080",
        "timezone": "America/New_York",
        "device_type": "desktop",
        "browser": "Chrome 120",
        "os": "Windows 10",
        "ip_address": "192.168.1.1"  # optional
    }
    
    Response:
    {
        "has_conflict": true/false,
        "conflict_info": {  # only if has_conflict is true
            "device_type": "mobile",
            "browser": "Safari 17",
            "os": "iOS 17",
            "login_timestamp": "2024-01-20T10:30:00Z",
            "last_activity": "2024-01-20T12:45:00Z",
            "device_fingerprint": "abc123..."
        },
        "device_fingerprint": "xyz789..."
    }
    
    **Feature: exam-security-enhancements, Property 2: Device conflict detection**
    **Validates: Requirements 1.2, 1.3**
    """
    # Validate request data
    request_serializer = DeviceCheckRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)
    
    device_info = request_serializer.validated_data
    
    # Add IP address from request if not provided
    if 'ip_address' not in device_info:
        device_info['ip_address'] = request.META.get('REMOTE_ADDR', '0.0.0.0')
    
    # Generate device fingerprint
    device_fingerprint = DeviceSessionManager.generate_device_fingerprint(device_info)
    
    # Check for conflicts
    conflict_info = DeviceSessionManager.check_session_conflict(
        request.user,
        device_fingerprint
    )
    
    response_data = {
        'has_conflict': conflict_info is not None,
        'conflict_info': conflict_info,
        'device_fingerprint': device_fingerprint
    }
    
    # Validate response
    response_serializer = DeviceCheckResponseSerializer(data=response_data)
    response_serializer.is_valid(raise_exception=True)
    
    logger.info(
        f"Device check for user {request.user.email}: "
        f"conflict={'yes' if conflict_info else 'no'}"
    )
    
    return Response(response_serializer.validated_data)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])  # Allow during login flow
@csrf_exempt
def logout_device_view(request):
    """
    Logout a specific device and create a new session for the current device.
    
    POST /api/auth/logout-device/
    
    Request body:
    {
        "device_fingerprint": "abc123...",  # fingerprint of device to logout
        "new_device_info": {
            "user_agent": "Mozilla/5.0...",
            "screen_resolution": "1920x1080",
            "timezone": "America/New_York",
            "device_type": "desktop",
            "browser": "Chrome 120",
            "os": "Windows 10",
            "ip_address": "192.168.1.1"  # optional
        }
    }
    
    Response:
    {
        "message": "Device logged out successfully",
        "new_session": {
            "device_fingerprint": "xyz789...",
            "device_type": "desktop",
            "browser": "Chrome 120",
            ...
        }
    }
    
    **Feature: exam-security-enhancements, Property 4: Device session swap atomicity**
    **Validates: Requirements 1.4**
    """
    old_fingerprint = request.data.get('device_fingerprint')
    new_device_info = request.data.get('new_device_info')
    
    if not old_fingerprint or not new_device_info:
        return Response(
            {'error': 'Both device_fingerprint and new_device_info are required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate new device info
    device_serializer = DeviceCheckRequestSerializer(data=new_device_info)
    device_serializer.is_valid(raise_exception=True)
    
    # Add IP address if not provided
    if 'ip_address' not in new_device_info:
        new_device_info['ip_address'] = request.META.get('REMOTE_ADDR', '0.0.0.0')
    
    # Swap device session atomically
    try:
        new_session = DeviceSessionManager.swap_device_session(
            request.user,
            old_fingerprint,
            new_device_info
        )
        
        session_serializer = DeviceSessionSerializer(new_session)
        
        # Generate new JWT tokens with device fingerprint embedded
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(request.user)
        refresh['device_fingerprint'] = new_session.device_fingerprint
        access_token = refresh.access_token
        access_token['device_fingerprint'] = new_session.device_fingerprint
        
        tokens = {
            "refresh": str(refresh),
            "access": str(access_token),
        }
        
        logger.info(
            f"Device swap for user {request.user.email}: "
            f"old={old_fingerprint[:8]}... -> new={new_session.device_fingerprint[:8]}..."
        )
        
        return Response({
            'message': 'Device logged out successfully',
            'new_session': session_serializer.data,
            'tokens': tokens  # Include new tokens with device fingerprint
        })
    except Exception as e:
        logger.error(f"Error swapping device session: {str(e)}")
        return Response(
            {'error': 'Failed to logout device'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def active_sessions_view(request):
    """
    Get all active device sessions for the authenticated user.
    
    GET /api/auth/active-sessions/
    
    Response:
    {
        "sessions": [
            {
                "device_fingerprint": "abc123...",
                "device_type": "desktop",
                "browser": "Chrome 120",
                "os": "Windows 10",
                "login_timestamp": "2024-01-20T10:30:00Z",
                "last_activity": "2024-01-20T12:45:00Z",
                ...
            }
        ]
    }
    
    **Feature: exam-security-enhancements, Property 3: Device information completeness**
    **Validates: Requirements 1.3**
    """
    sessions = DeviceSession.objects.filter(
        user=request.user,
        is_active=True
    ).order_by('-last_activity')
    
    serializer = DeviceSessionSerializer(sessions, many=True)
    
    logger.info(f"Retrieved {sessions.count()} active sessions for user {request.user.email}")
    
    return Response({
        'sessions': serializer.data
    })


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
@csrf_exempt
def delete_session_view(request, fingerprint):
    """
    Invalidate a specific device session by fingerprint.
    
    DELETE /api/auth/session/{fingerprint}/
    
    Response:
    {
        "message": "Session invalidated successfully"
    }
    
    **Feature: exam-security-enhancements, Property 5: Session preservation on cancel**
    **Validates: Requirements 1.5**
    """
    # Verify the session belongs to the authenticated user
    try:
        session = DeviceSession.objects.get(
            device_fingerprint=fingerprint,
            user=request.user,
            is_active=True
        )
    except DeviceSession.DoesNotExist:
        return Response(
            {'error': 'Session not found or already inactive'},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Invalidate the session
    success = DeviceSessionManager.invalidate_session(fingerprint)
    
    if success:
        logger.info(
            f"Session invalidated for user {request.user.email}: "
            f"fingerprint={fingerprint[:8]}..."
        )
        return Response({
            'message': 'Session invalidated successfully'
        })
    else:
        return Response(
            {'error': 'Failed to invalidate session'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
