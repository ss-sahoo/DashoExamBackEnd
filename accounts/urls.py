from django.urls import path
from . import views

urlpatterns = [
    # Authentication
    path('register/', views.user_registration_view, name='user-register'),
    path('login/', views.user_login_view, name='user-login'),
    path('logout/', views.user_logout_view, name='user-logout'),
    
    # User management
    path('profile/', views.UserProfileView.as_view(), name='user-profile'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('dashboard/', views.user_dashboard_view, name='user-dashboard'),
    
    # User listing
    path('users/', views.UserListView.as_view(), name='user-list'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user-detail'),
    
    # Permissions
    path('permissions/', views.UserPermissionListView.as_view(), name='user-permission-list'),
    
    # Institutes
    path('institutes/', views.InstituteListCreateView.as_view(), name='institute-list-create'),
    path('institutes/<int:pk>/', views.InstituteDetailView.as_view(), name='institute-detail'),
    path('institutes/<int:pk>/update/', views.InstituteUpdateView.as_view(), name='institute-update'),
    path('institutes/<int:institute_id>/users/', views.InstituteUserListView.as_view(), name='institute-user-list'),
    path('institute-settings/', views.InstituteSettingsView.as_view(), name='institute-settings'),
    path('institute-search/', views.institute_search, name='institute-search'),
    path('leave-institute/', views.leave_institute, name='leave-institute'),
    
    # Institute Invitations
    path('invitations/', views.InstituteInvitationListView.as_view(), name='institute-invitation-list'),
    path('invitations/<int:pk>/', views.InstituteInvitationDetailView.as_view(), name='institute-invitation-detail'),
    path('invitations/<int:invitation_id>/accept/', views.accept_invitation, name='accept-invitation'),
    path('invitations/<int:invitation_id>/decline/', views.decline_invitation, name='decline-invitation'),
    path('my-invitations/', views.my_invitations, name='my-invitations'),
]
