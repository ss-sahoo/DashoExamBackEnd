from __future__ import annotations

"""
Role-aware authentication APIs using JWT tokens.

We do a normal username/email + password login (NO phone number),
then check the user's role and return a JWT plus basic profile info.

Front-end can hit different endpoints for different roles:
- /api/auth/superadmin/login/
- /api/auth/admin/login/
- /api/auth/teacher/login/
- /api/auth/staff/login/

All of them accept the same payload:
{
  "username": "user_or_email",
  "password": "plain_password"
}
"""

from typing import Type

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

        # Get user from timetable_account.User model directly
        user = _get_user_by_identifier(identifier)
        if not user:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Check password directly (since we're using timetable_account.User, not AUTH_USER_MODEL)
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

        if self.allowed_roles and user.role not in self.allowed_roles:
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
    Only users with role = SUPER_ADMIN can login here.
    """

    allowed_roles = (User.ROLE_SUPER_ADMIN,)


class AdminLoginView(BaseRoleLoginView):
    """
    Admin login (center admins). We also allow SUPER_ADMIN here if desired.
    """

    allowed_roles = (User.ROLE_ADMIN, User.ROLE_SUPER_ADMIN)


class TeacherLoginView(BaseRoleLoginView):
    """
    Teacher login.
    """

    allowed_roles = (User.ROLE_TEACHER,)


class StudentLoginView(BaseRoleLoginView):
    """
    Student login.
    """

    allowed_roles = (User.ROLE_STUDENT,)


class StaffLoginView(BaseRoleLoginView):
    """
    Non-teaching staff login.
    """

    allowed_roles = (User.ROLE_STAFF,)


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
    if user.role not in (User.ROLE_ADMIN, User.ROLE_STUDENT):
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


