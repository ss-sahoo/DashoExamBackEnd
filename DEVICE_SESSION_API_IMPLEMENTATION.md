# Device Session API Implementation

## Overview

This document describes the implementation of Device Session API endpoints for the ExamFlow platform. These endpoints enable device-based login restrictions to ensure students can only be logged in on one device at a time.

## Implemented Components

### 1. Serializers (`accounts/serializers.py`)

#### DeviceSessionSerializer
Serializes DeviceSession model instances with all required fields including:
- Device information (type, browser, OS, screen resolution, timezone)
- Session metadata (login timestamp, last activity, expiration)
- User information

#### DeviceCheckRequestSerializer
Validates incoming device check requests with required device information.

#### DeviceCheckResponseSerializer
Formats device check responses with conflict detection information.
**Validates Property 3: Device information completeness** - ensures all required fields are present in conflict info.

#### LogoutDeviceRequestSerializer
Validates logout device requests.

### 2. API Views (`accounts/device_session_views.py`)

#### POST /api/auth/check-device/
**Purpose**: Check for device conflicts when a user attempts to login.

**Request Body**:
```json
{
    "user_agent": "Mozilla/5.0...",
    "screen_resolution": "1920x1080",
    "timezone": "America/New_York",
    "device_type": "desktop",
    "browser": "Chrome 120",
    "os": "Windows 10",
    "ip_address": "192.168.1.1"
}
```

**Response**:
```json
{
    "has_conflict": true/false,
    "conflict_info": {
        "device_type": "mobile",
        "browser": "Safari 17",
        "os": "iOS 17",
        "login_timestamp": "2024-01-20T10:30:00Z",
        "last_activity": "2024-01-20T12:45:00Z",
        "device_fingerprint": "abc123..."
    },
    "device_fingerprint": "xyz789..."
}
```

**Validates**: Requirements 1.2, 1.3

#### POST /api/auth/logout-device/
**Purpose**: Logout a specific device and create a new session atomically.

**Request Body**:
```json
{
    "device_fingerprint": "abc123...",
    "new_device_info": {
        "user_agent": "Mozilla/5.0...",
        "screen_resolution": "1920x1080",
        "timezone": "America/New_York",
        "device_type": "desktop",
        "browser": "Chrome 120",
        "os": "Windows 10",
        "ip_address": "192.168.1.1"
    }
}
```

**Response**:
```json
{
    "message": "Device logged out successfully",
    "new_session": {
        "device_fingerprint": "xyz789...",
        "device_type": "desktop",
        "browser": "Chrome 120",
        ...
    }
}
```

**Validates**: Requirements 1.4 (Property 4: Device session swap atomicity)

#### GET /api/auth/active-sessions/
**Purpose**: Get all active device sessions for the authenticated user.

**Response**:
```json
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
```

**Validates**: Requirements 1.3 (Property 3: Device information completeness)

#### DELETE /api/auth/session/{fingerprint}/
**Purpose**: Invalidate a specific device session.

**Response**:
```json
{
    "message": "Session invalidated successfully"
}
```

**Validates**: Requirements 1.5 (Property 5: Session preservation on cancel)

### 3. URL Routes (`accounts/urls.py`)

Added the following routes:
- `path('check-device/', check_device_view, name='check-device')`
- `path('logout-device/', logout_device_view, name='logout-device')`
- `path('active-sessions/', active_sessions_view, name='active-sessions')`
- `path('session/<str:fingerprint>/', delete_session_view, name='delete-session')`

### 4. Property-Based Tests

#### test_device_session_api_properties.py
**Property 3: Device information completeness**
- Tests that device session information contains all required fields
- Validates both check-device and active-sessions endpoints
- Runs 100 randomized test cases using Hypothesis
- **Status**: ✓ PASSED

### 5. Integration Tests

#### test_device_session_api_integration.py
Comprehensive integration tests covering:
1. Check device endpoint (no conflict scenario)
2. Check device endpoint (with conflict scenario)
3. Logout device endpoint (atomic session swap)
4. Active sessions endpoint (session listing)
5. Delete session endpoint (session invalidation)

**Status**: ✓ ALL TESTS PASSED

## Authentication & Permissions

All endpoints require authentication:
- `@permission_classes([permissions.IsAuthenticated])`
- Users can only manage their own device sessions
- Session operations are scoped to the authenticated user

## Security Features

1. **Device Fingerprinting**: Uses SHA256 hash of user agent, screen resolution, and timezone
2. **Atomic Operations**: Device swap uses database transactions
3. **Session Validation**: All operations verify session ownership
4. **IP Tracking**: Records IP address for audit purposes
5. **Expiration Handling**: Sessions expire after 24 hours of inactivity

## Error Handling

- **400 Bad Request**: Invalid or missing required fields
- **401 Unauthorized**: User not authenticated
- **404 Not Found**: Session not found or already inactive
- **500 Internal Server Error**: Unexpected errors during session operations

## Usage Flow

### Login Flow with Device Conflict Detection

1. User attempts login with credentials
2. Frontend collects device information
3. Call `POST /api/auth/check-device/` with device info
4. If `has_conflict: false`, proceed with login
5. If `has_conflict: true`, show device conflict modal with conflict_info
6. User chooses to:
   - **Logout previous device**: Call `POST /api/auth/logout-device/`
   - **Cancel**: Reject login, preserve existing session

### Session Management

1. User can view active sessions: `GET /api/auth/active-sessions/`
2. User can manually invalidate a session: `DELETE /api/auth/session/{fingerprint}/`

## Testing

Run tests with:
```bash
# Property-based tests
python test_device_session_api_properties.py

# Integration tests
python test_device_session_api_integration.py
```

## Next Steps

To complete the device session feature:
1. Integrate device check into login flow (frontend)
2. Create device conflict modal UI (frontend)
3. Add session management UI to user settings
4. Implement automatic session cleanup background task
5. Add device change detection and suspicious activity alerts

## References

- **Design Document**: `.kiro/specs/exam-security-enhancements/design.md`
- **Requirements**: `.kiro/specs/exam-security-enhancements/requirements.md`
- **Tasks**: `.kiro/specs/exam-security-enhancements/tasks.md`
- **Device Session Manager**: `accounts/device_session_manager.py`
- **Device Session Model**: `accounts/models.py` (DeviceSession)
