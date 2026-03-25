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
        default_db = settings.DATABASES['default']
        # Start with all keys from default (Django 4.2 requires specific keys like CONN_HEALTH_CHECKS)
        db_config = dict(default_db)
        # Override with tenant-specific values
        db_config['NAME'] = institute.db_name
        if institute.db_user:
            db_config['USER'] = institute.db_user
        if institute.db_password:
            db_config['PASSWORD'] = institute.db_password
        if institute.db_host:
            db_config['HOST'] = institute.db_host
        if institute.db_port:
            db_config['PORT'] = institute.db_port
        
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
