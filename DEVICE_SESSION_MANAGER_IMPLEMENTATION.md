# DeviceSessionManager Service Implementation

## Summary

Successfully implemented task 2 "Implement DeviceSessionManager service" from the exam-security-enhancements spec.

## What Was Implemented

### 1. DeviceSessionManager Service Class

Created a comprehensive service class in `accounts/device_session_manager.py` with the following methods:

#### Core Methods

**`generate_device_fingerprint(device_info: Dict) -> str`**
- Generates a unique SHA256 hash from device characteristics
- Uses user_agent, screen_resolution, and timezone
- **Validates**: Requirements 8.1 (Property 33)

**`create_session(user: User, device_info: Dict) -> DeviceSession`**
- Creates a new device session for a user
- Handles existing sessions by updating them
- Sets expiration to 24 hours from creation
- Uses atomic database transaction
- **Validates**: Requirements 1.1 (Property 1)

**`get_active_session(user: User) -> Optional[DeviceSession]`**
- Retrieves the active session for a user
- Filters out expired sessions
- Returns None if no active session exists
- **Validates**: Requirements 1.2 (Property 2)

**`check_session_conflict(user: User, device_fingerprint: str) -> Optional[Dict]`**
- Checks if a user is trying to login from a different device
- Returns conflict information if detected
- Returns None if no conflict (same device or no active session)
- **Validates**: Requirements 1.2 (Property 2)

**`invalidate_session(device_fingerprint: str) -> bool`**
- Invalidates a device session immediately
- Used for logout functionality
- Returns True if successful, False if session not found
- **Validates**: Requirements 8.4 (Property 36)

**`swap_device_session(user: User, old_fingerprint: str, new_device_info: Dict) -> DeviceSession`**
- Atomically invalidates old session and creates new one
- Ensures exactly one active session at all times
- Uses database transaction for atomicity
- **Validates**: Requirements 1.4 (Property 4)

**`cleanup_expired_sessions() -> int`**
- Background task to clean up expired sessions
- Marks sessions inactive after 24 hours of inactivity
- Returns count of cleaned up sessions
- **Validates**: Requirements 8.3 (Property 35)

**`update_session_activity(device_fingerprint: str) -> bool`**
- Updates last activity timestamp
- Extends session expiration by 24 hours
- Used to keep active sessions alive

### 2. Management Command

Created Django management command `cleanup_expired_sessions.py`:

```bash
python manage.py cleanup_expired_sessions
```

This command should be run periodically via:
- Cron job (e.g., every hour)
- Celery beat task
- System scheduler

### 3. Property-Based Tests

Implemented comprehensive property-based tests in `test_device_session_manager_properties.py`:

#### Test Results (All Passed ✓)

**Property 2: Device conflict detection**
- **Validates**: Requirements 1.2
- **Test**: For any student with an active session attempting login from a different device, the system should return the previous device information
- **Result**: ✓ PASSED (100 examples)

**Property 4: Device session swap atomicity**
- **Validates**: Requirements 1.4
- **Test**: For any user with an active session, logging out the previous device and creating a new session should result in exactly one active session with the new device fingerprint
- **Result**: ✓ PASSED (100 examples)

**Property 5: Session preservation on cancel**
- **Validates**: Requirements 1.5
- **Test**: For any user with an active session, cancelling a device switch should leave the original session unchanged
- **Result**: ✓ PASSED (100 examples)

**Property 35: Session expiration after inactivity**
- **Validates**: Requirements 8.3
- **Test**: For any device session inactive for 24 hours, it should be automatically invalidated
- **Result**: ✓ PASSED (100 examples)

**Property 36: Session invalidation on logout**
- **Validates**: Requirements 8.4
- **Test**: For any logout action, the device session should be immediately invalidated
- **Result**: ✓ PASSED (100 examples)

## Architecture

### Service Layer Pattern

The DeviceSessionManager follows the service layer pattern:
- Encapsulates business logic for device session management
- Provides clean API for controllers/views
- Handles database transactions atomically
- Includes comprehensive logging

### Transaction Safety

All state-changing operations use `@transaction.atomic`:
- `create_session` - Ensures session creation is atomic
- `swap_device_session` - Ensures old session invalidation and new session creation happen together
- `invalidate_session` - Ensures session invalidation is atomic

### Error Handling

- Graceful handling of non-existent sessions
- Comprehensive logging for debugging
- Returns appropriate values (None, False) for error cases
- No exceptions thrown for expected error conditions

## Usage Examples

### Creating a Session on Login

```python
from accounts.device_session_manager import DeviceSessionManager

# Collect device information from request
device_info = {
    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
    'screen_resolution': '1920x1080',  # From frontend
    'timezone': 'America/New_York',     # From frontend
    'device_type': 'desktop',           # From frontend
    'browser': 'Chrome/120.0',          # Parsed from user agent
    'os': 'Windows 10',                 # Parsed from user agent
    'ip_address': get_client_ip(request)
}

# Create session
session = DeviceSessionManager.create_session(user, device_info)
```

### Checking for Device Conflicts

```python
# Generate fingerprint for current device
current_fingerprint = DeviceSessionManager.generate_device_fingerprint(device_info)

# Check for conflicts
conflict_info = DeviceSessionManager.check_session_conflict(user, current_fingerprint)

if conflict_info:
    # Show device conflict modal to user
    return Response({
        'conflict': True,
        'existing_device': {
            'type': conflict_info['device_type'],
            'browser': conflict_info['browser'],
            'os': conflict_info['os'],
            'login_time': conflict_info['login_timestamp'],
            'last_activity': conflict_info['last_activity']
        }
    })
```

### Swapping Device Sessions

```python
# User chose to logout previous device and login on new device
old_fingerprint = conflict_info['device_fingerprint']
new_session = DeviceSessionManager.swap_device_session(
    user, 
    old_fingerprint, 
    new_device_info
)
```

### Invalidating Session on Logout

```python
# Get device fingerprint from request
device_fingerprint = request.data.get('device_fingerprint')

# Invalidate session
success = DeviceSessionManager.invalidate_session(device_fingerprint)

if success:
    return Response({'message': 'Logged out successfully'})
```

### Updating Session Activity

```python
# On each authenticated request, update session activity
device_fingerprint = request.session.get('device_fingerprint')
DeviceSessionManager.update_session_activity(device_fingerprint)
```

## Configuration

### Session Expiration Time

Default: 24 hours

To change, modify the constant in `device_session_manager.py`:

```python
class DeviceSessionManager:
    SESSION_EXPIRATION_HOURS = 24  # Change this value
```

### Cleanup Schedule

Recommended: Run cleanup every hour

**Using Cron:**
```bash
0 * * * * cd /path/to/project && python manage.py cleanup_expired_sessions
```

**Using Celery Beat:**
```python
from celery import shared_task
from accounts.device_session_manager import DeviceSessionManager

@shared_task
def cleanup_expired_sessions():
    return DeviceSessionManager.cleanup_expired_sessions()

# In celery beat schedule:
CELERY_BEAT_SCHEDULE = {
    'cleanup-expired-sessions': {
        'task': 'accounts.tasks.cleanup_expired_sessions',
        'schedule': crontab(minute=0),  # Every hour
    },
}
```

## Security Considerations

### Device Fingerprinting

- Uses SHA256 hashing for fingerprints
- Combines multiple device characteristics
- Resistant to simple spoofing attempts
- Does not store raw fingerprint components

### Session Security

- Sessions expire after 24 hours of inactivity
- Only one active session per user
- Atomic operations prevent race conditions
- IP addresses logged for audit trail

### Privacy

- Device information stored for security purposes
- No personally identifiable information in fingerprints
- Sessions can be invalidated by user at any time
- Old sessions automatically cleaned up

## Testing

### Running Property-Based Tests

```bash
cd exam_flow_backend
python test_device_session_manager_properties.py
```

Expected output:
```
Running Property-Based Tests for DeviceSessionManager
======================================================================
[1/5] Testing Property 2: Device conflict detection
----------------------------------------------------------------------
✓ Property 2 PASSED (100 examples)

[2/5] Testing Property 4: Device session swap atomicity
----------------------------------------------------------------------
✓ Property 4 PASSED (100 examples)

[3/5] Testing Property 5: Session preservation on cancel
----------------------------------------------------------------------
✓ Property 5 PASSED (100 examples)

[4/5] Testing Property 35: Session expiration after inactivity
----------------------------------------------------------------------
✓ Property 35 PASSED (100 examples)

[5/5] Testing Property 36: Session invalidation on logout
----------------------------------------------------------------------
✓ Property 36 PASSED (100 examples)

======================================================================
✓ ALL PROPERTY TESTS PASSED!
======================================================================
```

### Test Coverage

- 100 randomly generated examples per property
- Tests cover all core functionality
- Tests validate all requirements from spec
- Tests use realistic device data

## Files Created/Modified

### Created:
- `exam_flow_backend/accounts/device_session_manager.py` - Service class
- `exam_flow_backend/test_device_session_manager_properties.py` - Property tests
- `exam_flow_backend/accounts/management/commands/cleanup_expired_sessions.py` - Management command
- `exam_flow_backend/DEVICE_SESSION_MANAGER_IMPLEMENTATION.md` - This documentation

### Modified:
- None (all new files)

## Requirements Validation

All requirements from task 2 have been met:

- ✓ Create DeviceSessionManager class with session lifecycle methods
- ✓ Implement create_session with device fingerprint generation
- ✓ Implement get_active_session for conflict detection
- ✓ Implement invalidate_session for logout
- ✓ Implement cleanup_expired_sessions background task
- ✓ Property test for device conflict detection (Requirements 1.2) - PASSED
- ✓ Property test for session swap atomicity (Requirements 1.4) - PASSED
- ✓ Property test for session preservation on cancel (Requirements 1.5) - PASSED
- ✓ Property test for session expiration (Requirements 8.3) - PASSED
- ✓ Property test for session invalidation on logout (Requirements 8.4) - PASSED

## Next Steps

The DeviceSessionManager service is now ready for:
1. Task 3: Create device session API endpoints
2. Task 4: Implement frontend DeviceManager component
3. Task 5: Integrate device session into login flow

## Logging

The service includes comprehensive logging:
- Session creation events
- Session invalidation events
- Session swap events
- Cleanup events
- Warning for invalid operations

Logs use the `accounts.device_session_manager` logger.

## Performance Considerations

### Database Queries

- All queries use indexed fields (device_fingerprint, user_id, is_active)
- Queries are optimized with appropriate filters
- No N+1 query problems

### Caching

Consider adding caching for:
- Active session lookups (cache for 5 minutes)
- Device fingerprint generation (cache for request duration)

### Scalability

- Service is stateless and thread-safe
- Can handle concurrent requests safely
- Database transactions prevent race conditions
- Cleanup can run on separate worker

## Monitoring

Recommended metrics to track:
- Number of active sessions
- Session creation rate
- Conflict detection rate
- Session swap rate
- Cleanup frequency and count
- Average session duration

## Troubleshooting

### Sessions Not Expiring

Check that cleanup command is running:
```bash
python manage.py cleanup_expired_sessions
```

### Conflicts Not Detected

Verify device fingerprint generation:
```python
fingerprint = DeviceSessionManager.generate_device_fingerprint(device_info)
print(f"Generated fingerprint: {fingerprint}")
```

### Multiple Active Sessions

This should not happen due to atomic transactions. If it does:
1. Check database transaction isolation level
2. Verify swap_device_session is being used
3. Check for race conditions in calling code

