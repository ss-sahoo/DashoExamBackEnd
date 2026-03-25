"""
Custom JWT token claims
"""


def get_tokens_for_user(user):
    """Generate tokens with custom claims"""
    from rest_framework_simplejwt.tokens import RefreshToken
    
    refresh = RefreshToken.for_user(user)
    
    # Add custom claims
    refresh['email'] = user.email
    refresh['role'] = user.role
    refresh['first_name'] = user.first_name
    refresh['last_name'] = user.last_name
    refresh['institute_id'] = user.institute.id if user.institute else None
    refresh['institute_name'] = user.institute.name if user.institute else None
    
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

