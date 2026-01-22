"""
GeolocationService for handling geolocation capture and validation.
Implements requirements 2.2, 2.3, 2.4, 2.5 from exam-security-enhancements spec.
"""
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import ExamAttempt


class GeolocationService:
    """Service class for handling geolocation capture and validation"""
    
    # Valid coordinate ranges
    MIN_LATITUDE = Decimal('-90.0')
    MAX_LATITUDE = Decimal('90.0')
    MIN_LONGITUDE = Decimal('-180.0')
    MAX_LONGITUDE = Decimal('180.0')
    
    @classmethod
    def validate_coordinates(cls, latitude: Decimal, longitude: Decimal) -> bool:
        """
        Validate that latitude and longitude are within valid ranges.
        
        Args:
            latitude: Latitude value to validate (-90 to 90)
            longitude: Longitude value to validate (-180 to 180)
            
        Returns:
            bool: True if coordinates are valid, False otherwise
            
        Raises:
            ValidationError: If coordinates are invalid
        """
        try:
            # Convert to Decimal if not already
            if not isinstance(latitude, Decimal):
                latitude = Decimal(str(latitude))
            if not isinstance(longitude, Decimal):
                longitude = Decimal(str(longitude))
            
            # Validate latitude range
            if latitude < cls.MIN_LATITUDE or latitude > cls.MAX_LATITUDE:
                raise ValidationError(
                    f"Latitude must be between {cls.MIN_LATITUDE} and {cls.MAX_LATITUDE}. "
                    f"Got: {latitude}"
                )
            
            # Validate longitude range
            if longitude < cls.MIN_LONGITUDE or longitude > cls.MAX_LONGITUDE:
                raise ValidationError(
                    f"Longitude must be between {cls.MIN_LONGITUDE} and {cls.MAX_LONGITUDE}. "
                    f"Got: {longitude}"
                )
            
            return True
            
        except (InvalidOperation, ValueError, TypeError) as e:
            raise ValidationError(f"Invalid coordinate format: {str(e)}")
    
    @classmethod
    def capture_location(
        cls,
        exam_attempt: ExamAttempt,
        latitude: Optional[Decimal] = None,
        longitude: Optional[Decimal] = None,
        permission_denied: bool = False
    ) -> Dict:
        """
        Capture and store geolocation data for an exam attempt.
        
        Args:
            exam_attempt: The ExamAttempt instance to store location for
            latitude: Latitude coordinate (optional if permission denied)
            longitude: Longitude coordinate (optional if permission denied)
            permission_denied: Whether geolocation permission was denied
            
        Returns:
            Dict with capture status and details
            
        Raises:
            ValidationError: If coordinates are invalid
        """
        try:
            # Handle permission denied case
            if permission_denied:
                exam_attempt.geolocation_permission_denied = True
                exam_attempt.geolocation_latitude = None
                exam_attempt.geolocation_longitude = None
                exam_attempt.geolocation_captured_at = timezone.now()
                exam_attempt.save(update_fields=[
                    'geolocation_permission_denied',
                    'geolocation_latitude',
                    'geolocation_longitude',
                    'geolocation_captured_at'
                ])
                
                return {
                    'success': True,
                    'permission_denied': True,
                    'message': 'Geolocation permission denied by user',
                    'captured_at': exam_attempt.geolocation_captured_at
                }
            
            # Validate coordinates if provided
            if latitude is None or longitude is None:
                raise ValidationError("Latitude and longitude are required when permission is granted")
            
            # Validate coordinate ranges
            cls.validate_coordinates(latitude, longitude)
            
            # Store geolocation data
            exam_attempt.geolocation_latitude = latitude
            exam_attempt.geolocation_longitude = longitude
            exam_attempt.geolocation_captured_at = timezone.now()
            exam_attempt.geolocation_permission_denied = False
            exam_attempt.save(update_fields=[
                'geolocation_latitude',
                'geolocation_longitude',
                'geolocation_captured_at',
                'geolocation_permission_denied'
            ])
            
            return {
                'success': True,
                'permission_denied': False,
                'latitude': float(exam_attempt.geolocation_latitude),
                'longitude': float(exam_attempt.geolocation_longitude),
                'captured_at': exam_attempt.geolocation_captured_at,
                'message': 'Geolocation captured successfully'
            }
            
        except ValidationError as e:
            # Re-raise validation errors
            raise e
        except Exception as e:
            # Handle unexpected errors
            raise ValidationError(f"Failed to capture geolocation: {str(e)}")
    
    @classmethod
    def get_location_for_attempt(cls, exam_attempt_id: int) -> Optional[Dict]:
        """
        Retrieve geolocation data for a specific exam attempt.
        
        Args:
            exam_attempt_id: ID of the exam attempt
            
        Returns:
            Dict with geolocation data or None if not found
        """
        try:
            exam_attempt = ExamAttempt.objects.get(id=exam_attempt_id)
            
            # Check if geolocation was captured
            if exam_attempt.geolocation_captured_at is None:
                return {
                    'captured': False,
                    'message': 'Geolocation not yet captured for this attempt'
                }
            
            # Check if permission was denied
            if exam_attempt.geolocation_permission_denied:
                return {
                    'captured': True,
                    'permission_denied': True,
                    'captured_at': exam_attempt.geolocation_captured_at,
                    'message': 'Geolocation permission was denied by user'
                }
            
            # Return captured location data
            return {
                'captured': True,
                'permission_denied': False,
                'latitude': float(exam_attempt.geolocation_latitude) if exam_attempt.geolocation_latitude else None,
                'longitude': float(exam_attempt.geolocation_longitude) if exam_attempt.geolocation_longitude else None,
                'captured_at': exam_attempt.geolocation_captured_at,
                'message': 'Geolocation data retrieved successfully'
            }
            
        except ExamAttempt.DoesNotExist:
            return None
        except Exception as e:
            raise ValidationError(f"Failed to retrieve geolocation: {str(e)}")
