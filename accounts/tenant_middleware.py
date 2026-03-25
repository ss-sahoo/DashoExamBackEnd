from django.utils.deprecation import MiddlewareMixin
from accounts.utils import set_current_db, clear_current_db
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class TenantMiddleware(MiddlewareMixin):
    """
    Middleware to detect the current institute and set the correct database connection.
    """
    def process_request(self, request):
        # 1. Check for explicit header
        requested_db = request.headers.get('X-Institute-DB')
        tenant_db = None
        
        # 2. Identify the user (session or JWT)
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            try:
                jwt_auth = JWTAuthentication()
                header = jwt_auth.get_header(request)
                if header:
                    raw_token = jwt_auth.get_raw_token(header)
                    validated_token = jwt_auth.get_validated_token(raw_token)
                    user = jwt_auth.get_user(validated_token)
            except Exception:
                user = None

        # 3. Determine the correct tenant DB
        if user and user.is_authenticated:
            if requested_db:
                # If they requested a specific DB, check if they are a member
                from .models import Institute
                try:
                    # Fetch from default to avoid recursion
                    target_institute = Institute.objects.using('default').get(db_name=requested_db)
                    
                    # Super admins can access anything
                    if user.role == 'super_admin':
                        tenant_db = requested_db
                    # Check if they belong to this institute (primary or membership)
                    elif user.institute_id == target_institute.id:
                        tenant_db = requested_db
                    elif user.memberships.filter(institute=target_institute, is_active=True).exists():
                        tenant_db = requested_db
                    else:
                        logger.warning(f"User {user.email} attempted to access unauthorized database: {requested_db}")
                        # Fallback to primary
                        tenant_db = user.institute.db_name if user.institute else None
                except Institute.DoesNotExist:
                    logger.error(f"Requested database {requested_db} does not exist.")
                    tenant_db = user.institute.db_name if user.institute else None
            else:
                # No specific requests, use primary institute
                if user.institute and user.institute.db_name:
                    tenant_db = user.institute.db_name
        else:
            # For unauthenticated requests (like login where they might provide institute hint)
            tenant_db = requested_db

        # 4. Final DB selection
        if not tenant_db or tenant_db == 'default':
            set_current_db('default')
            return None
            
        # 4. Ensure DB exists in settings.DATABASES
        # In a real environment, you'd have a pool of configurations or 
        # use dynamic DB settings from a shared cache/DB.
        if tenant_db not in settings.DATABASES:
            # For demonstration, we'll try to configure it if it's missing
            # In production, you'd preferably load all into DATABASES or 
            # use a more robust dynamic registration.
            from .models import Institute
            try:
                # We fetch from 'default' explicitly to avoid recursion
                institute = Institute.objects.using('default').get(db_name=tenant_db)
                from .database_utils import register_institute_database
                register_institute_database(institute)
            except Institute.DoesNotExist:
                logger.error(f"Tenant database {tenant_db} requested but no such institute found.")
                # Fallback to default or return error
                set_current_db('default')
                return None
                
        # Set the thread-local database name
        set_current_db(tenant_db)
        return None

    def process_response(self, request, response):
        """
        Clear the thread-local storage on response.
        """
        clear_current_db()
        return response
