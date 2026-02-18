from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import login, logout
from django.contrib.auth.hashers import make_password
from django.db import transaction, models
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .models import User, Institute, UserPermission, InstituteSettings, InstituteInvitation, ActivityLog
from .serializers import (
    UserRegistrationSerializer, UserSerializer, UserLoginSerializer,
    InstituteSerializer, InstituteCreateSerializer, UserPermissionSerializer, 
    InstituteSettingsSerializer, ChangePasswordSerializer, InstituteInvitationSerializer,
    ActivityLogSerializer
)
from .jwt_utils import get_tokens_for_user
from rest_framework.exceptions import PermissionDenied


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@csrf_exempt
def user_registration_view(request):
    """User registration - no institute required"""
    serializer = UserRegistrationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    with transaction.atomic():
        user = serializer.save()
        
        # Log activity
        from .utils import log_activity
        log_activity(
            institute=user.institute,
            log_type='user',
            title='New User Registered',
            description=f'User {user.get_full_name()} ({user.email}) registered as {user.role}.',
            user=user,
            status='success',
            request=request
        ) if user.institute else None

        tokens = get_tokens_for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'access': tokens['access'],
            'refresh': tokens['refresh'],
            'message': 'User registered successfully'
        }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@csrf_exempt
def user_login_view(request):
    """
    Generic login endpoint - supports username, email, or teacher_code.
    Same authentication style as timetable role-based logins.
    Returns JWT tokens in the same format.
    Includes device session management.
    """
    from django.db.models import Q
    from rest_framework_simplejwt.tokens import RefreshToken
    from .device_session_manager import DeviceSessionManager
    
    identifier = request.data.get('email') or request.data.get('username')
    password = request.data.get('password')
    
    # Get device information from request
    device_info = {
        'user_agent': request.data.get('user_agent', request.META.get('HTTP_USER_AGENT', '')),
        'screen_resolution': request.data.get('screen_resolution', ''),
        'timezone': request.data.get('timezone', ''),
        'device_type': request.data.get('device_type', ''),
        'browser': request.data.get('browser', ''),
        'os': request.data.get('os', ''),
        'ip_address': request.META.get('REMOTE_ADDR', ''),
    }
    
    if not identifier or not password:
        return Response({
            'detail': 'Both username/email and password are required.'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Get user by username, email, or teacher_code (same as timetable)
    try:
        user = User.objects.get(
            Q(username__iexact=identifier) 
            | Q(email__iexact=identifier)
            | Q(teacher_code__iexact=identifier)
        )
    except User.DoesNotExist:
        return Response({
            'detail': 'Invalid credentials.'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Check password
    if not user.check_password(password):
        return Response({
            'detail': 'Invalid credentials.'
        }, status=status.HTTP_401_UNAUTHORIZED)
    
    # Check if user is active
    if not user.is_active:
        return Response({
            'detail': 'User account is disabled.'
        }, status=status.HTTP_403_FORBIDDEN)
    
        # Check for device conflicts
    try:
        device_manager = DeviceSessionManager()
        has_conflict, conflict_info = device_manager.check_session_conflict(user, device_info)
        
        # Check if force login is requested
        force_login = request.data.get('force_login', False)
        
        if has_conflict and not force_login:
            # Return conflict information without creating tokens
            return Response(
                {
                    "has_conflict": True,
                    "conflict_info": conflict_info,
                    "message": "You are already logged in on another device.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        
        # No conflict OR force login, create session
        # If force_login is True, it will invalidate other sessions
        session = device_manager.create_session(user, device_info, force_logout_others=force_login)
        
        # Log activity
        from .utils import log_activity
        log_activity(
            institute=user.institute,
            log_type='login',
            title='User Login',
            description=f'User {user.get_full_name()} logged in from {device_info["browser"]} on {device_info["os"]}.',
            user=user,
            status='info',
            request=request
        ) if user.institute else None

    except Exception as e:
        # Log the error but don't block login
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Device session error: {str(e)}", exc_info=True)
        # Continue with login without device session
        session = None
    
    # Generate JWT tokens (same format as timetable)
    refresh = RefreshToken.for_user(user)
    
    # Add device fingerprint to the token payload for validation
    if session:
        refresh['device_fingerprint'] = session.device_fingerprint
        # Regenerate access token with the updated payload
        access_token = refresh.access_token
        access_token['device_fingerprint'] = session.device_fingerprint
    
    tokens = {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }
    
    # Get center_id - either from direct assignment or from admin_centers
    center_id = None
    center_name = None
    if user.center_id:
        center_id = str(user.center_id)
        center_name = user.center.name if user.center else None
    else:
        # Check if user is admin of any center
        admin_center = user.admin_centers.first()
        if admin_center:
            center_id = str(admin_center.id)
            center_name = admin_center.name
    
    response_data = {
        'tokens': tokens,
        'user': {
            'id': str(user.id),
            'username': user.username,
            'email': user.email,
            'full_name': user.get_full_name(),
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'institute_id': user.institute_id,
            'institute_name': user.institute.name if user.institute else None,
            'center_id': center_id,
            'center_name': center_name,
        },
        'message': 'Login successful'
    }
    
    # Add device session info if available
    if session:
        response_data['device_session'] = {
            'device_fingerprint': session.device_fingerprint,
            'device_type': session.device_type,
            'browser': session.browser,
            'os': session.os,
        }
    
    return Response(response_data)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])  # Allow any user to logout
@csrf_exempt
def user_logout_view(request):
    """User logout - properly clear all session data, CSRF tokens, and device sessions"""
    from .device_session_manager import DeviceSessionManager
    from rest_framework_simplejwt.authentication import JWTAuthentication
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        # Get device fingerprint before logging out
        device_fingerprint = None
        
        # Try to get from header first
        device_fingerprint = request.headers.get('X-Device-Fingerprint')
        
        # If not in header, try to get from JWT token
        if not device_fingerprint and request.user.is_authenticated:
            try:
                jwt_auth = JWTAuthentication()
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                    validated_token = jwt_auth.get_validated_token(token)
                    device_fingerprint = validated_token.get('device_fingerprint')
            except Exception as e:
                logger.warning(f"Could not extract device fingerprint from token: {str(e)}")
        
        # Invalidate device session if we have the fingerprint
        if device_fingerprint:
            success = DeviceSessionManager.invalidate_session(device_fingerprint)
            if success:
                logger.info(f"Invalidated device session on logout: {device_fingerprint[:8]}...")
            else:
                logger.warning(f"Could not invalidate device session: {device_fingerprint[:8]}...")
        elif request.user.is_authenticated:
            # If we don't have fingerprint, invalidate ALL active sessions for this user
            # This is a fallback to ensure logout works even without fingerprint
            from .models import DeviceSession
            invalidated_count = DeviceSession.objects.filter(
                user=request.user,
                is_active=True
            ).update(is_active=False)
            logger.info(f"Invalidated {invalidated_count} device session(s) for user {request.user.email} on logout")
        
        # Logout the user if authenticated
        if request.user.is_authenticated:
            logout(request)
        
        # Clear all session data
        request.session.flush()
        
        # Clear CSRF token from session
        if 'csrf_token' in request.session:
            del request.session['csrf_token']
        
        # Create response
        response = Response({'message': 'Logout successful'})
        
        # Clear all cookies with different paths and domains
        response.delete_cookie('sessionid', path='/')
        response.delete_cookie('csrftoken', path='/')
        response.delete_cookie('csrftoken', path='/', domain=None)
        response.delete_cookie('csrftoken', path='/', domain='localhost')
        response.delete_cookie('csrftoken', path='/', domain='127.0.0.1')
        
        # Set cookies to expire immediately
        response.set_cookie('sessionid', '', max_age=0, path='/')
        response.set_cookie('csrftoken', '', max_age=0, path='/')
        
        return response
    except Exception as e:
        # Even if there's an error, try to clear everything
        logger.error(f"Error during logout: {str(e)}", exc_info=True)
        try:
            request.session.flush()
        except:
            pass
        
        response = Response({'message': 'Logout successful'})
        response.delete_cookie('sessionid', path='/')
        response.delete_cookie('csrftoken', path='/')
        response.set_cookie('sessionid', '', max_age=0, path='/')
        response.set_cookie('csrftoken', '', max_age=0, path='/')
        return response


class UserProfileView(generics.RetrieveUpdateAPIView):
    """Get or update authenticated user's profile"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class ChangePasswordView(generics.GenericAPIView):
    """Change user password"""
    serializer_class = ChangePasswordSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        # Generate new JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'message': 'Password changed successfully'
        })


class InstituteListCreateView(generics.ListCreateAPIView):
    """List all active institutes and create new institutes"""
    queryset = Institute.objects.filter(is_active=True)
    permission_classes = [permissions.AllowAny]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return InstituteCreateSerializer
        return InstituteSerializer
    
    def get_permissions(self):
        if self.request.method == 'POST':
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]


class InstituteDetailView(generics.RetrieveAPIView):
    """Get institute details"""
    queryset = Institute.objects.all()
    serializer_class = InstituteSerializer
    permission_classes = [permissions.AllowAny]


class UserListView(generics.ListCreateAPIView):
    """List users within the same institute or create a new user"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return UserRegistrationSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        # Priority: User's assigned institute (strict) > Query parameter (filter)
        eff_institute_id = getattr(user, 'institute_id', None) or self.request.query_params.get('institute_id')
        
        center_id = self.request.query_params.get('center_id')
        
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            queryset = User.objects.all()
            if eff_institute_id:
                queryset = queryset.filter(institute_id=eff_institute_id)
            if center_id:
                queryset = queryset.filter(center_id=center_id)
            return queryset
        
        if user.is_institute_admin():
            return User.objects.filter(institute=user.institute)
        return User.objects.filter(id=user.id)

    def perform_create(self, serializer):
        user = self.request.user
        
        # Check permissions
        if user.role not in ['super_admin', 'SUPER_ADMIN', 'institute_admin', 'exam_admin', 'admin', 'ADMIN']:
             raise PermissionDenied("You do not have permission to create users.")

        # For institute admins, force the institute_id
        if user.role in ['institute_admin', 'exam_admin'] and user.institute:
             serializer.save(institute_id=user.institute.id)
        else:
             serializer.save()


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, or delete a user"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Priority: User's assigned institute (strict) > Query parameter (filter)
        eff_institute_id = getattr(user, 'institute_id', None) or self.request.query_params.get('institute_id')
        
        if user.role in ['super_admin']:
            if eff_institute_id:
                return User.objects.filter(institute_id=eff_institute_id)
            return User.objects.all()
        
        if user.is_institute_admin():
            return User.objects.filter(institute=user.institute)
        return User.objects.filter(id=user.id)

    def perform_update(self, serializer):
        actor = self.request.user
        instance = serializer.instance

        # Allow super admins to update anyone
        if actor.role in ['super_admin']:
            serializer.save()
            return

        # Allow institute admins to update users in their institute or users updating themselves
        if actor.is_institute_admin() and instance.institute == actor.institute:
            serializer.save()
            return

        if actor.id == instance.id:
            serializer.save()
            return

        raise PermissionDenied("You do not have permission to update this user.")

    def perform_destroy(self, instance):
        actor = self.request.user

        # Allow super admins to delete anyone
        if actor.role in ['super_admin']:
            instance.delete()
            return

        if not actor.is_institute_admin():
            raise PermissionDenied("You do not have permission to delete users.")

        if instance.id == actor.id:
            raise PermissionDenied("You cannot delete your own account from this screen.")

        if instance.institute_id != actor.institute_id:
            raise PermissionDenied("You can only delete users from your institute.")

        # Prevent deleting the last institute admin
        if instance.role == 'institute_admin':
            admin_count = User.objects.filter(institute=instance.institute, role='institute_admin').exclude(id=instance.id).count()
            if admin_count == 0:
                raise PermissionDenied("You cannot remove the only institute admin.")

        instance.delete()


class UserPermissionListView(generics.ListCreateAPIView):
    """List and create user permissions"""
    serializer_class = UserPermissionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_institute_admin():
            return UserPermission.objects.filter(user__institute=user.institute)
        return UserPermission.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(granted_by=self.request.user)


class InstituteSettingsView(generics.RetrieveUpdateAPIView):
    """Get and update institute settings"""
    serializer_class = InstituteSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        user = self.request.user
        if not user.is_institute_admin():
            return None
        
        settings, created = InstituteSettings.objects.get_or_create(institute=user.institute)
        return settings


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def user_dashboard_view(request):
    """Get user dashboard data"""
    user = request.user
    
    dashboard_data = {
        'user': UserSerializer(user).data,
        'institute': InstituteSerializer(user.institute).data,
        'permissions': {
            'can_manage_exams': user.can_manage_exams(),
            'can_create_exams': user.can_create_exams(),
            'is_institute_admin': user.is_institute_admin(),
        }
    }
    
    # Add role-specific data
    if user.role in ['student', 'STUDENT']:
        dashboard_data['upcoming_exams'] = []
        dashboard_data['exam_history'] = []
    elif user.can_manage_exams():
        dashboard_data['created_exams'] = []
        dashboard_data['exam_analytics'] = []
    
    return Response(dashboard_data)


class InstituteUpdateView(generics.UpdateAPIView):
    """Update institute details"""
    serializer_class = InstituteSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            return Institute.objects.all()
        return Institute.objects.filter(users=user, users__role__in=['institute_admin', 'super_admin'])


class InstituteUserListView(generics.ListAPIView):
    """List users within an institute"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        institute_id = self.kwargs.get('institute_id')
        
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            return User.objects.filter(institute_id=institute_id)
        elif user.role in ['institute_admin', 'exam_admin'] and user.institute_id == institute_id:
            return User.objects.filter(institute_id=institute_id)
        else:
            return User.objects.none()


class InstituteInvitationListView(generics.ListCreateAPIView):
    """List and create institute invitations"""
    serializer_class = InstituteInvitationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            return InstituteInvitation.objects.all()
        elif user.role in ['institute_admin', 'exam_admin']:
            return InstituteInvitation.objects.filter(institute=user.institute)
        else:
            return InstituteInvitation.objects.none()
    
    def perform_create(self, serializer):
        user = self.request.user
        if user.role not in ['super_admin', 'institute_admin', 'exam_admin']:
            raise permissions.PermissionDenied("You don't have permission to send invitations.")
        serializer.save()


class InstituteInvitationDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Manage individual institute invitations"""
    serializer_class = InstituteInvitationSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            return InstituteInvitation.objects.all()
        elif user.role in ['institute_admin', 'exam_admin']:
            return InstituteInvitation.objects.filter(institute=user.institute)
        else:
            return InstituteInvitation.objects.none()


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def accept_invitation(request, invitation_id):
    """Accept an institute invitation"""
    try:
        invitation = InstituteInvitation.objects.get(id=invitation_id, email=request.user.email)
    except InstituteInvitation.DoesNotExist:
        return Response({'error': 'Invitation not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if invitation.is_expired():
        invitation.status = 'expired'
        invitation.save()
        return Response({'error': 'Invitation has expired'}, status=status.HTTP_400_BAD_REQUEST)
    
    if invitation.status != 'pending':
        return Response({'error': 'Invitation is no longer valid'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Update user's institute and role
    user = request.user
    user.institute = invitation.institute
    user.role = invitation.role
    user.save()
    
    # Update invitation status
    invitation.status = 'accepted'
    invitation.save()
    
    return Response({'message': 'Invitation accepted successfully'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def decline_invitation(request, invitation_id):
    """Decline an institute invitation"""
    try:
        invitation = InstituteInvitation.objects.get(id=invitation_id, email=request.user.email)
    except InstituteInvitation.DoesNotExist:
        return Response({'error': 'Invitation not found'}, status=status.HTTP_404_NOT_FOUND)
    
    if invitation.status != 'pending':
        return Response({'error': 'Invitation is no longer valid'}, status=status.HTTP_400_BAD_REQUEST)
    
    invitation.status = 'declined'
    invitation.save()
    
    return Response({'message': 'Invitation declined'})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def my_invitations(request):
    """Get invitations for the current user"""
    invitations = InstituteInvitation.objects.filter(
        email=request.user.email,
        status='pending'
    ).exclude(expires_at__lt=timezone.now())
    
    serializer = InstituteInvitationSerializer(invitations, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def leave_institute(request):
    """Leave current institute"""
    user = request.user
    
    if user.role in ['super_admin', 'SUPER_ADMIN']:
        return Response({'error': 'Super admins cannot leave institutes'}, status=status.HTTP_400_BAD_REQUEST)
    
    if not user.institute:
        return Response({'error': 'You are not part of any institute'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check if user is the only admin
    if user.role == 'institute_admin':
        admin_count = user.institute.get_admins().count()
        if admin_count <= 1:
            return Response({'error': 'You cannot leave as you are the only admin'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Remove user from institute
    user.institute = None
    user.role = 'student'  # Reset to default role
    user.save()
    
    return Response({'message': 'Successfully left the institute'})


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def all_people_view(request):
    """
    Get all people with filters and role information.
    
    Query Parameters:
    - role: Filter by role (e.g., 'teacher', 'student', 'admin', 'ADMIN')
    - search: Search by name, email, or username
    - is_active: Filter by active status ('true' or 'false')
    - center_id: Filter by center
    - institute_id: Filter by institute
    - page: Page number (default: 1)
    - page_size: Items per page (default: 20, max: 100)
    """
    from django.db.models import Q
    from django.core.paginator import Paginator
    
    user = request.user
    
    # Base queryset - admins see all, others see their institute
    if user.role in ['super_admin']:
        # Priority: User's assigned institute (strict) > Query parameter (filter)
        effective_institute_id = getattr(user, 'institute_id', None) or request.GET.get('institute_id')
        if effective_institute_id:
            queryset = User.objects.filter(institute_id=effective_institute_id)
        else:
            queryset = User.objects.all()
    elif user.role in ['institute_admin', 'admin', 'exam_admin']:
        queryset = User.objects.filter(
            Q(institute=user.institute) | Q(center__institute=user.institute)
        )
    else:
        # Regular users see people in their institute/center
        queryset = User.objects.filter(institute=user.institute)
    
    # Apply filters
    role_filter = request.GET.get('role')
    if role_filter:
        # Support both lowercase and uppercase role variants
        role_variants = [role_filter, role_filter.lower(), role_filter.upper()]
        queryset = queryset.filter(role__in=role_variants)
    
    search = request.GET.get('search')
    if search:
        queryset = queryset.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(username__icontains=search) |
            Q(teacher_code__icontains=search)
        )
    
    is_active = request.GET.get('is_active')
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active.lower() == 'true')
    
    center_id = request.GET.get('center_id')
    if center_id:
        queryset = queryset.filter(center_id=center_id)
    
    institute_id = request.GET.get('institute_id')
    if institute_id and user.role in ['super_admin']:
        queryset = queryset.filter(institute_id=institute_id)
    
    # Order by name
    queryset = queryset.order_by('first_name', 'last_name')
    
    # Pagination
    page = int(request.GET.get('page', 1))
    page_size = min(int(request.GET.get('page_size', 20)), 100)
    
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page)
    
    # Get all available roles for filter dropdown
    all_roles = [
        {'value': 'super_admin', 'label': 'Super Admin'},
        {'value': 'institute_admin', 'label': 'Institute Admin'},
        {'value': 'exam_admin', 'label': 'Exam Admin'},
        {'value': 'teacher', 'label': 'Teacher'},
        {'value': 'student', 'label': 'Student'},
        {'value': 'admin', 'label': 'Center Admin'},
        {'value': 'staff', 'label': 'Staff'},
    ]
    
    # Get role counts
    role_counts = {}
    for role_choice in all_roles:
        role_val = role_choice['value']
        if user.role in ['super_admin']:
            count = User.objects.filter(role=role_val).count()
        elif user.role in ['institute_admin', 'admin', 'exam_admin']:
            count = User.objects.filter(
                Q(institute=user.institute) | Q(center__institute=user.institute),
                role=role_val
            ).count()
        else:
            count = User.objects.filter(institute=user.institute, role=role_val).count()
        role_counts[role_val] = count
    
    # Serialize users
    users_data = []
    for u in page_obj:
        users_data.append({
            'id': str(u.id) if hasattr(u.id, 'hex') else u.id,
            'username': u.username,
            'email': u.email,
            'first_name': u.first_name,
            'last_name': u.last_name,
            'full_name': u.get_full_name(),
            'role': u.role,
            'role_display': dict(User.ROLE_CHOICES).get(u.role, u.role),
            'is_active': u.is_active,
            'is_verified': u.is_verified,
            'phone': u.phone or u.phone_number,
            'profile_picture': u.profile_picture.url if u.profile_picture else (u.profile_image.url if u.profile_image else None),
            'teacher_code': u.teacher_code,
            'institute_id': u.institute_id,
            'institute_name': u.institute.name if u.institute else None,
            'center_id': str(u.center_id) if u.center_id else None,
            'center_name': u.center.name if u.center else None,
            'created_at': u.created_at.isoformat() if u.created_at else None,
        })
    
    return Response({
        'users': users_data,
        'total_count': paginator.count,
        'page': page,
        'page_size': page_size,
        'total_pages': paginator.num_pages,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'roles': all_roles,
        'role_counts': role_counts,
    })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def institute_search(request):
    """Search for institutes by name or domain"""
    query = request.GET.get('q', '')
    if not query:
        return Response({'error': 'Search query is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    institutes = Institute.objects.filter(
        models.Q(name__icontains=query) | models.Q(domain__icontains=query),
        is_active=True
    )[:10]  # Limit to 10 results
    
    serializer = InstituteSerializer(institutes, many=True)
    return Response(serializer.data)


class ActivityLogListView(generics.ListAPIView):
    """
    List activity logs for an institute.
    """
    serializer_class = ActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        
        # Only admins can view logs
        if user.role not in ['super_admin', 'institute_admin', 'exam_admin']:
            raise PermissionDenied("You do not have permission to view activity logs.")
            
        queryset = ActivityLog.objects.filter(institute=user.institute)
        
        # Filter by log type
        log_type = self.request.query_params.get('log_type')
        if log_type and log_type != 'all':
            queryset = queryset.filter(log_type=log_type)
            
        # Filter by search term
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(title__icontains=search) |
                models.Q(description__icontains=search) |
                models.Q(user__first_name__icontains=search) |
                models.Q(user__last_name__icontains=search) |
                models.Q(user__email__icontains=search)
            )
            
        return queryset
