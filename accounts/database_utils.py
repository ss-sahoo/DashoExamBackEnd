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
        # Create the configuration, inheriting all options from default DB
        db_config = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': institute.db_name,
            'USER': institute.db_user or default_db.get('USER'),
            'PASSWORD': institute.db_password or default_db.get('PASSWORD'),
            'HOST': institute.db_host or default_db.get('HOST'),
            'PORT': institute.db_port or default_db.get('PORT'),
            'TIME_ZONE': default_db.get('TIME_ZONE', None),
            'CONN_MAX_AGE': default_db.get('CONN_MAX_AGE', 0),
            'OPTIONS': default_db.get('OPTIONS', {}),
            'ATOMIC_REQUESTS': default_db.get('ATOMIC_REQUESTS', False),
            'AUTOCOMMIT': default_db.get('AUTOCOMMIT', True),
            'TEST': default_db.get('TEST', {}),
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
