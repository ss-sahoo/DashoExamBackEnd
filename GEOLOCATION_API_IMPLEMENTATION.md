# Geolocation API Implementation Summary

## Task 8: Create Geolocation API Endpoints

### Implementation Date
January 22, 2026

### Requirements Implemented
- Requirement 2.2: Geolocation capture when permission is granted
- Requirement 2.3: Geolocation data storage with exam attempt

### Files Created/Modified

#### 1. Serializers (`exam_flow_backend/exams/serializers.py`)
Added two new serializers:

- **GeolocationCaptureSerializer**: Validates geolocation capture requests
  - Fields: `attempt_id`, `latitude`, `longitude`, `permission_denied`
  - Validates that coordinates are provided when permission is not denied

- **GeolocationDataSerializer**: Serializes geolocation data responses
  - Fields: `captured`, `permission_denied`, `latitude`, `longitude`, `captured_at`, `message`

#### 2. Views (`exam_flow_backend/exams/views.py`)
Added two new API endpoints:

- **capture_location** (`POST /api/exams/capture-location/`)
  - Captures and stores geolocation data for an exam attempt
  - Validates coordinate ranges (-90 to 90 for latitude, -180 to 180 for longitude)
  - Handles permission denied cases
  - Enforces ownership (students can only update their own attempts)
  - Returns success status with captured coordinates or permission denial

- **get_attempt_location** (`GET /api/exams/attempt/{attempt_id}/location/`)
  - Retrieves geolocation data for a specific exam attempt
  - Permission checks:
    - Students can only view their own attempts
    - Admins can view any attempt from their institute
  - Returns captured location data or permission denial status

#### 3. URL Configuration (`exam_flow_backend/exams/urls.py`)
Added two new URL patterns:
- `path('capture-location/', views.capture_location, name='capture-location')`
- `path('attempt/<int:attempt_id>/location/', views.get_attempt_location, name='get-attempt-location')`

### Features Implemented

#### Coordinate Validation
- Latitude: -90.0 to 90.0
- Longitude: -180.0 to 180.0
- Invalid coordinates return HTTP 400 Bad Request

#### Permission Handling
- Supports both granted and denied geolocation permission
- When denied: stores denial flag, no coordinates stored
- When granted: validates and stores coordinates

#### Security & Access Control
- Authentication required for all endpoints
- Students can only access their own exam attempts
- Admins can access attempts from their institute
- Unauthorized access returns HTTP 403 Forbidden

#### Error Handling
- Non-existent attempts: HTTP 404 Not Found
- Invalid coordinates: HTTP 400 Bad Request with validation error
- Permission violations: HTTP 403 Forbidden
- Server errors: HTTP 500 Internal Server Error with error message

### API Request/Response Examples

#### Capture Location with Coordinates
**Request:**
```json
POST /api/exams/capture-location/
{
    "attempt_id": 123,
    "latitude": "27.7172",
    "longitude": "85.3240",
    "permission_denied": false
}
```

**Response (200 OK):**
```json
{
    "success": true,
    "permission_denied": false,
    "latitude": 27.7172,
    "longitude": 85.324,
    "captured_at": "2026-01-22T07:08:51.066643Z",
    "message": "Geolocation captured successfully"
}
```

#### Capture Location with Permission Denied
**Request:**
```json
POST /api/exams/capture-location/
{
    "attempt_id": 123,
    "permission_denied": true
}
```

**Response (200 OK):**
```json
{
    "success": true,
    "permission_denied": true,
    "message": "Geolocation permission denied by user",
    "captured_at": "2026-01-22T07:08:51.079243Z"
}
```

#### Get Attempt Location
**Request:**
```
GET /api/exams/attempt/123/location/
```

**Response (200 OK):**
```json
{
    "captured": true,
    "permission_denied": false,
    "latitude": 27.7172,
    "longitude": 85.324,
    "captured_at": "2026-01-22T07:08:51.066643Z",
    "message": "Geolocation data retrieved successfully"
}
```

### Testing

#### Property-Based Tests
Existing property tests in `test_geolocation_properties.py` pass:
- ✓ Property 6: Geolocation capture on permission grant
- ✓ Property 7: Geolocation persistence

#### Manual Integration Tests
Created `test_geolocation_manual.py` with comprehensive tests:
- ✓ Capture location with valid coordinates
- ✓ Capture location with permission denied
- ✓ Coordinate validation (rejects invalid values)
- ✓ Permission checks (rejects unauthorized access)
- ✓ Get attempt location as student
- ✓ Get attempt location as admin
- ✓ Get attempt location when not captured
- ✓ Get attempt location when permission denied

All tests pass successfully.

### Database Schema
Uses existing fields in `ExamAttempt` model:
- `geolocation_latitude`: DecimalField(max_digits=9, decimal_places=6)
- `geolocation_longitude`: DecimalField(max_digits=9, decimal_places=6)
- `geolocation_captured_at`: DateTimeField
- `geolocation_permission_denied`: BooleanField

### Integration with Existing Code
- Uses existing `GeolocationService` for business logic
- Integrates with existing authentication and permission system
- Follows existing API patterns and conventions
- Uses existing serializer patterns

### Next Steps
The geolocation API endpoints are now ready for frontend integration. The next task (Task 9) will implement the frontend `GeolocationTracker` component to use these endpoints.

### Notes
- All code compiles without syntax errors
- Django system check passes with no issues
- Endpoints follow REST best practices
- Comprehensive error handling implemented
- Security and permission checks in place
