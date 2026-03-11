from django.conf import settings
from django.db import connections
from django import db

def register_institute_database(institute):
    """
    Dynamically adds an institute's database to Django's DATABASES setting
    if it's not already there.
    """
    if not institute.db_name:
        return 'default'
    
    db_key = institute.db_name
    
    if db_key not in settings.DATABASES:
        # Create the configuration
        db_config = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': institute.db_name,
            'USER': institute.db_user or settings.DATABASES['default'].get('USER'),
            'PASSWORD': institute.db_password or settings.DATABASES['default'].get('PASSWORD'),
            'HOST': institute.db_host or settings.DATABASES['default'].get('HOST'),
            'PORT': institute.db_port or settings.DATABASES['default'].get('PORT'),
        }
        
        # Inject into settings (this is not standard but works for dynamic routing)
        settings.DATABASES[db_key] = db_config
        
    return db_key

def ensure_database_exists(db_name):
    """
    Utility to ensure a database exists (PostgreSQL specific).
    In a real system, you'd use a master connection to CREATE DATABASE.
    """
    # This would require a connection with CREATEDB permissions
    pass
