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
from .models import User, Institute, UserPermission, InstituteSettings, InstituteInvitation
from .serializers import (
    UserRegistrationSerializer, UserSerializer, UserLoginSerializer,
    InstituteSerializer, InstituteCreateSerializer, UserPermissionSerializer, 
    InstituteSettingsSerializer, ChangePasswordSerializer, InstituteInvitationSerializer
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
    """
    from django.db.models import Q
    from rest_framework_simplejwt.tokens import RefreshToken
    
    identifier = request.data.get('email') or request.data.get('username')
    password = request.data.get('password')
    
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
    
    # Generate JWT tokens (same format as timetable)
    refresh = RefreshToken.for_user(user)
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
    
    return Response({
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
    })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])  # Allow any user to logout
@csrf_exempt
def user_logout_view(request):
    """User logout - properly clear all session data and CSRF tokens"""
    try:
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


class UserListView(generics.ListAPIView):
    """List users within the same institute"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            return User.objects.all()
        if user.is_institute_admin():
            return User.objects.filter(institute=user.institute)
        return User.objects.filter(id=user.id)


class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, or delete a user"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            return User.objects.all()
        if user.is_institute_admin():
            return User.objects.filter(institute=user.institute)
        return User.objects.filter(id=user.id)

    def perform_update(self, serializer):
        actor = self.request.user
        instance = serializer.instance

        # Allow super admins to update anyone
        if actor.role in ['super_admin', 'SUPER_ADMIN']:
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
        if actor.role in ['super_admin', 'SUPER_ADMIN']:
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
    if user.role == 'student':
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
        if user.role == 'super_admin':
            return Institute.objects.all()
        return Institute.objects.filter(users=user, users__role__in=['institute_admin', 'super_admin'])


class InstituteUserListView(generics.ListAPIView):
    """List users within an institute"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        institute_id = self.kwargs.get('institute_id')
        
        if user.role == 'super_admin':
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
        if user.role == 'super_admin':
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
        if user.role == 'super_admin':
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
    
    if user.role == 'super_admin':
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
    - role: Filter by role (e.g., 'teacher', 'student', 'ADMIN')
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
    if user.role in ['super_admin', 'SUPER_ADMIN']:
        queryset = User.objects.all()
    elif user.role in ['institute_admin', 'ADMIN', 'exam_admin']:
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
    if institute_id and user.role in ['super_admin', 'SUPER_ADMIN']:
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
        {'value': 'ADMIN', 'label': 'Center Admin'},
        {'value': 'STAFF', 'label': 'Staff'},
    ]
    
    # Get role counts
    role_counts = {}
    for role_choice in all_roles:
        role_val = role_choice['value']
        if user.role in ['super_admin', 'SUPER_ADMIN']:
            count = User.objects.filter(role=role_val).count()
        elif user.role in ['institute_admin', 'ADMIN', 'exam_admin']:
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
