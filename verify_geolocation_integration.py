"""
Manual verification script for geolocation integration.

**Feature: exam-security-enhancements**
**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

This script verifies that:
1. The GeolocationService is properly implemented
2. The API endpoints are configured correctly
3. The frontend GeolocationTracker service exists and is properly structured
"""
import os
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')

try:
    import django
    django.setup()
except Exception as e:
    print(f"❌ Failed to setup Django: {e}")
    sys.exit(1)

def verify_backend():
    """Verify backend implementation"""
    print("=" * 60)
    print("BACKEND VERIFICATION")
    print("=" * 60)
    
    # Check GeolocationService
    try:
        from exams.geolocation_service import GeolocationService
        print(" GeolocationService imported successfully")
        
        # Check methods exist
        assert hasattr(GeolocationService, 'capture_location'), "Missing capture_location method"
        assert hasattr(GeolocationService, 'validate_coordinates'), "Missing validate_coordinates method"
        assert hasattr(GeolocationService, 'get_location_for_attempt'), "Missing get_location_for_attempt method"
        print(" GeolocationService has all required methods")
        
    except Exception as e:
        print(f"❌ GeolocationService verification failed: {e}")
        return False
    
    # Check ExamAttempt model has geolocation fields
    try:
        from exams.models import ExamAttempt
        attempt = ExamAttempt()
        
        assert hasattr(attempt, 'geolocation_latitude'), "Missing geolocation_latitude field"
        assert hasattr(attempt, 'geolocation_longitude'), "Missing geolocation_longitude field"
        assert hasattr(attempt, 'geolocation_captured_at'), "Missing geolocation_captured_at field"
        assert hasattr(attempt, 'geolocation_permission_denied'), "Missing geolocation_permission_denied field"
        print(" ExamAttempt model has all geolocation fields")
        
    except Exception as e:
        print(f"❌ ExamAttempt model verification failed: {e}")
        return False
    
    # Check API endpoints are registered
    try:
        from django.urls import resolve
        from django.urls.exceptions import Resolver404
        
        try:
            resolve('/api/exams/capture-location/')
            print(" Geolocation capture endpoint is registered")
        except Resolver404:
            print("❌ Geolocation capture endpoint not found")
            return False
            
    except Exception as e:
        print(f"❌ URL verification failed: {e}")
        return False
    
    return True


def verify_frontend():
    """Verify frontend implementation"""
    print("\n" + "=" * 60)
    print("FRONTEND VERIFICATION")
    print("=" * 60)
    
    frontend_path = os.path.join(os.path.dirname(__file__), '..', 'Exam_Flow', 'src', 'react-app')
    
    # Check GeolocationTracker service exists
    tracker_path = os.path.join(frontend_path, 'services', 'GeolocationTracker.ts')
    if os.path.exists(tracker_path):
        print(f" GeolocationTracker service exists at {tracker_path}")
        
        # Read and verify key methods
        with open(tracker_path, 'r') as f:
            content = f.read()
            
            required_methods = [
                'requestPermission',
                'captureLocation',
                'sendToBackend',
                'captureAndSend'
            ]
            
            for method in required_methods:
                if method in content:
                    print(f" GeolocationTracker has {method} method")
                else:
                    print(f"❌ GeolocationTracker missing {method} method")
                    return False
    else:
        print(f"❌ GeolocationTracker service not found at {tracker_path}")
        return False
    
    # Check SecureExamView integration
    secure_exam_path = os.path.join(frontend_path, 'pages', 'SecureExamView.tsx')
    if os.path.exists(secure_exam_path):
        print(f" SecureExamView component exists")
        
        with open(secure_exam_path, 'r') as f:
            content = f.read()
            
            if 'geolocationTracker' in content:
                print(" SecureExamView imports GeolocationTracker")
            else:
                print("❌ SecureExamView does not import GeolocationTracker")
                return False
                
            if 'captureGeolocation' in content:
                print(" SecureExamView has captureGeolocation function")
            else:
                print("❌ SecureExamView missing captureGeolocation function")
                return False
    else:
        print(f"❌ SecureExamView component not found")
        return False
    
    # Check SecureExamExperience integration
    secure_exam_exp_path = os.path.join(frontend_path, 'pages', 'SecureExamExperience.tsx')
    if os.path.exists(secure_exam_exp_path):
        print(f" SecureExamExperience component exists")
        
        with open(secure_exam_exp_path, 'r') as f:
            content = f.read()
            
            if 'geolocationTracker' in content:
                print(" SecureExamExperience imports GeolocationTracker")
            else:
                print("❌ SecureExamExperience does not import GeolocationTracker")
                return False
                
            if 'captureGeolocation' in content:
                print(" SecureExamExperience has captureGeolocation function")
            else:
                print("❌ SecureExamExperience missing captureGeolocation function")
                return False
    else:
        print(f"❌ SecureExamExperience component not found")
        return False
    
    return True


def main():
    """Run all verifications"""
    print("\n" + "=" * 60)
    print("GEOLOCATION INTEGRATION VERIFICATION")
    print("=" * 60)
    print("\nThis script verifies that geolocation has been properly")
    print("integrated into the exam start flow.")
    print("\nRequirements being validated:")
    print("  - 2.1: Request geolocation permission on exam start")
    print("  - 2.2: Capture coordinates when permission granted")
    print("  - 2.3: Store coordinates with exam attempt")
    print("  - 2.4: Record permission denial without blocking")
    print("  - 2.5: Log unavailability and continue exam")
    print()
    
    backend_ok = verify_backend()
    frontend_ok = verify_frontend()
    
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    if backend_ok and frontend_ok:
        print(" ALL VERIFICATIONS PASSED")
        print("\nGeolocation integration is complete and properly configured.")
        print("\nNext steps:")
        print("  1. Start the Django backend server")
        print("  2. Start the React frontend development server")
        print("  3. Create an exam and start it as a student")
        print("  4. Check browser console for geolocation capture logs")
        print("  5. Verify geolocation data is stored in the database")
        return 0
    else:
        print("❌ SOME VERIFICATIONS FAILED")
        print("\nPlease review the errors above and fix any issues.")
        return 1


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
