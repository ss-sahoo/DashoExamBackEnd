"""
Timetable-specific authentication APIs using JWT tokens.
Role-aware login endpoints for timetable system.
"""

from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


def _get_user_by_identifier(identifier: str) -> User | None:
    """
    Allow login using username, email, OR teacher_code (for teachers).
    """
    try:
        return User.objects.get(
            Q(username__iexact=identifier) 
            | Q(email__iexact=identifier)
            | Q(teacher_code__iexact=identifier)  # Allow login with teacher code
        )
    except User.DoesNotExist:
        return None


def _build_tokens_for_user(user: User) -> dict:
    """
    Create JWT refresh + access tokens for the authenticated user.
    """
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


class BaseRoleLoginView(APIView):
    """
    Base class: implement role-specific login by setting `allowed_roles`.
    """

    permission_classes = [AllowAny]
    allowed_roles: tuple[str, ...] = ()

    def post(self, request, *args, **kwargs):
        identifier = request.data.get("username")  # username OR email
        password = request.data.get("password")

        if not identifier or not password:
            return Response(
                {"detail": "Both 'username' and 'password' are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get user from accounts.User model
        user = _get_user_by_identifier(identifier)
        if not user:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Check password directly
        if not user.check_password(password):
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        
        # Check if user is active
        if not user.is_active:
            return Response(
                {"detail": "User account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check role compatibility (support both formats)
        if self.allowed_roles:
            # Map roles for compatibility
            role_mapping = {
                'super_admin': ['super_admin', 'SUPER_ADMIN'],
                'SUPER_ADMIN': ['super_admin', 'SUPER_ADMIN'],
                'ADMIN': ['ADMIN', 'institute_admin', 'super_admin'],
                'institute_admin': ['ADMIN', 'institute_admin', 'super_admin'],
                'TEACHER': ['TEACHER', 'teacher'],
                'teacher': ['TEACHER', 'teacher'],
                'STUDENT': ['STUDENT', 'student'],
                'student': ['STUDENT', 'student'],
                'STAFF': ['STAFF'],
            }
            
            user_allowed = False
            for allowed_role in self.allowed_roles:
                compatible_roles = role_mapping.get(allowed_role, [allowed_role])
                if user.role in compatible_roles:
                    user_allowed = True
                    break
            
            if not user_allowed:
                return Response(
                    {
                        "detail": "User does not have permission to use this login endpoint.",
                        "role": user.role,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        tokens = _build_tokens_for_user(user)

        return Response(
            {
                "tokens": tokens,
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "full_name": user.get_full_name(),
                    "role": user.role,
                    "center_id": user.center_id,
                },
            },
            status=status.HTTP_200_OK,
        )


class SuperAdminLoginView(BaseRoleLoginView):
    """
    Only users with role = SUPER_ADMIN or super_admin can login here.
    """
    allowed_roles = ('SUPER_ADMIN', 'super_admin')


class AdminLoginView(BaseRoleLoginView):
    """
    Admin login (center admins). We also allow SUPER_ADMIN here if desired.
    """
    allowed_roles = ('ADMIN', 'institute_admin', 'SUPER_ADMIN', 'super_admin')


class TeacherLoginView(BaseRoleLoginView):
    """
    Teacher login.
    """
    allowed_roles = ('TEACHER', 'teacher')


class StudentLoginView(BaseRoleLoginView):
    """
    Student login.
    """
    allowed_roles = ('STUDENT', 'student')


class StaffLoginView(BaseRoleLoginView):
    """
    Non-teaching staff login.
    """
    allowed_roles = ('STAFF',)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def change_password(request):
    """
    Allow Admin and Student to change their password.
    
    Payload:
    {
        "old_password": "current_password",
        "new_password": "new_secure_password"
    }
    
    Returns:
    {
        "message": "Password changed successfully."
    }
    """
    user = request.user
    
    # Only Admin and Student can change their password via this API
    if user.role not in ('ADMIN', 'institute_admin', 'STUDENT', 'student'):
        return Response(
            {"detail": "Only Admin and Student can change password via this API."},
            status=status.HTTP_403_FORBIDDEN,
        )
    
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    
    if not old_password or not new_password:
        return Response(
            {"detail": "old_password and new_password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Verify old password
    if not user.check_password(old_password):
        return Response(
            {"detail": "Invalid old password."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Validate new password (basic validation)
    if len(new_password) < 8:
        return Response(
            {"detail": "New password must be at least 8 characters long."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    
    # Set new password
    user.set_password(new_password)
    user.save()
    
    return Response(
        {"message": "Password changed successfully."},
        status=status.HTTP_200_OK,
    )

