"""
Django settings for exam_flow_backend project.
"""

import os
from pathlib import Path
from config import SECRET_KEY, DEBUG, DATABASE_URL, ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS, GEMINI_API_KEY as CONFIG_GEMINI_API_KEY, GEMINI_MODEL as CONFIG_GEMINI_MODEL, GEMINI_TEMPERATURE as CONFIG_GEMINI_TEMPERATURE, GEMINI_TOP_P as CONFIG_GEMINI_TOP_P, GEMINI_MAX_TOKENS as CONFIG_GEMINI_MAX_TOKENS, MATHPIX_APP_ID as CONFIG_MATHPIX_APP_ID, MATHPIX_APP_KEY as CONFIG_MATHPIX_APP_KEY, EMAIL_HOST as CONFIG_EMAIL_HOST, EMAIL_PORT as CONFIG_EMAIL_PORT, EMAIL_USE_TLS as CONFIG_EMAIL_USE_TLS, EMAIL_HOST_USER as CONFIG_EMAIL_HOST_USER, EMAIL_HOST_PASSWORD as CONFIG_EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL as CONFIG_DEFAULT_FROM_EMAIL, AZURE_OPENAI_API_KEY as CONFIG_AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT as CONFIG_AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_VERSION as CONFIG_AZURE_OPENAI_VERSION, AZURE_OPENAI_MODEL_NAME as CONFIG_AZURE_OPENAI_MODEL_NAME

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = SECRET_KEY

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = DEBUG

ALLOWED_HOSTS = ALLOWED_HOSTS

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'corsheaders',
    'django_filters',
]

LOCAL_APPS = [
    'accounts',
    'exams',
    'questions',
    'patterns',
    'timetable',  # Timetable management app (uses accounts models)
    'omr',  # OMR sheet generation and evaluation
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'exam_flow_backend.middleware.DisableCSRFForAPI',  # Disable CSRF for API
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.device_session_middleware.DeviceSessionValidationMiddleware',  # Validate device sessions
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'exam_flow_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'exam_flow_backend.wsgi.application'

# Database
# Parse DATABASE_URL or use individual components
if DATABASE_URL and DATABASE_URL.startswith('postgresql'):
    # Parse DATABASE_URL manually for Python 3.8 compatibility
    import re
    match = re.match(r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)', DATABASE_URL)
    if match:
        db_user, db_password, db_host, db_port, db_name = match.groups()
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': db_name,
                'USER': db_user,
                'PASSWORD': db_password,
                'HOST': db_host,
                'PORT': db_port,
            }
        }
    else:
        # Fallback to default
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': os.getenv('DB_NAME', 'exam_flow_db'),
                'USER': os.getenv('DB_USER', 'exam_flow_user'),
                'PASSWORD': os.getenv('DB_PASSWORD', ''),
                'HOST': os.getenv('DB_HOST', 'localhost'),
                'PORT': os.getenv('DB_PORT', '5432'),
            }
        }
else:
    # Use individual environment variables
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'exam_flow_db'),
            'USER': os.getenv('DB_USER', 'exam_flow_user'),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# === DigitalOcean Spaces / S3-Compatible Storage Configuration ===
ALWAYS_UPLOAD_FILES_TO_AWS = True  # Set to True to enable DigitalOcean Spaces upload

# AWS Configuration (needed for both modes)
AWS_ACCESS_KEY_ID = 'UCW66UXZOVY3QVYQLSEK'
AWS_SECRET_ACCESS_KEY = 'TJi4SulSCtEU5RlHWsKkOpFoL0Qo/qVf5JB6Dcg8rWk'
AWS_STORAGE_BUCKET_NAME = 'edrspace'
AWS_S3_ENDPOINT_URL = 'https://sgp1.digitaloceanspaces.com'
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',
}
AWS_LOCATION = 'edrcontainer1'
AWS_DEFAULT_ACL = 'public-read'
AWS_S3_REGION_NAME = 'sgp1'
AWS_S3_FILE_OVERWRITE = False
AWS_QUERYSTRING_AUTH = False
AWS_S3_VERIFY = False
AWS_S3_ADDRESSING_STYLE = 'virtual'
AWS_S3_SIGNATURE_VERSION = 's3v4'

# This means you are uploading to AWS even when running locally
if ALWAYS_UPLOAD_FILES_TO_AWS:    
    # Media files configuration - pointing to DigitalOcean Space
    MEDIA_URL = f'https://{AWS_STORAGE_BUCKET_NAME}.sgp1.digitaloceanspaces.com/{AWS_LOCATION}/media/'
    MEDIA_ROOT = ''
    
    # Static files configuration - pointing to DigitalOcean Space
    STATIC_URL = f'https://{AWS_STORAGE_BUCKET_NAME}.sgp1.digitaloceanspaces.com/{AWS_LOCATION}/static/'
    # Modern Django 4.2+ Storage Configuration
    STORAGES = {
        "default": {
            "BACKEND": "exam_flow_backend.storage.MediaStorage",
        },
        "staticfiles": {
            "BACKEND": "exam_flow_backend.storage.StaticStorage",
        },
    }
else:
    # Static files (CSS, JavaScript, Images)
    STATIC_URL = '/static/'
    STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

    MEDIA_URL = '/media/'
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Authentication backends
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
]

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

# CORS settings
CORS_ALLOWED_ORIGINS = CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Allow all origins in development

# CORS headers for preflight requests
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-device-fingerprint',  # For device session validation
]

# CSRF settings
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://128.199.17.132',
    'http://exams.dashoapp.com',
    'http://exam.dashoapp.com',
    'https://exams.dashoapp.com',
    'https://exam.dashoapp.com',
    'http://timetable.dashoapp.com',
    'https://timetable.dashoapp.com',
]

# Disable CSRF for API endpoints (since we're using JWT)
CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False
CSRF_USE_SESSIONS = False
CSRF_COOKIE_AGE = None  # Don't persist CSRF cookies
CSRF_COOKIE_DOMAIN = None
CSRF_COOKIE_PATH = '/'
CSRF_COOKIE_SAMESITE = 'Lax'

# Email settings
# Use SMTP backend for production, console for development
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')

# Email configuration from config.py or environment
EMAIL_HOST = CONFIG_EMAIL_HOST or os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(CONFIG_EMAIL_PORT or os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = CONFIG_EMAIL_USE_TLS if CONFIG_EMAIL_USE_TLS is not None else os.getenv('EMAIL_USE_TLS', 'True').lower() == 'true'
EMAIL_HOST_USER = CONFIG_EMAIL_HOST_USER or os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = CONFIG_EMAIL_HOST_PASSWORD or os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = CONFIG_DEFAULT_FROM_EMAIL or os.getenv('DEFAULT_FROM_EMAIL', 'Exam Flow System <noreply@examflow.com>')

# Frontend URL for email links
FRONTEND_URL = 'http://localhost:5173'

# JWT settings (if using JWT)
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
}

# Timezone choices for UI dropdowns
TIMEZONE_CHOICES = [
    'UTC',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Madrid',
    'Europe/Rome',
    'Africa/Cairo',
    'Africa/Johannesburg',
    'Asia/Kolkata',
    'Asia/Dubai',
    'Asia/Singapore',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Asia/Hong_Kong',
    'Asia/Seoul',
    'Australia/Sydney',
    'Australia/Melbourne',
    'America/New_York',
    'America/Los_Angeles',
    'America/Chicago',
    'America/Toronto',
    'America/Mexico_City',
    'America/Sao_Paulo',
]


# ===========================
# Celery Configuration
# ===========================
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes max per task

# ===========================
# AI Configuration (Gemini)
# ===========================
# PRIMARY API KEY: AIzaSyBRBA_VMMB1B0zzYuL4QJWUmRmTE90TsmI (EXPIRED)
# Backup key: AIzaSyCCnt7RH4e_Mb2gRcdpCTZoOKpsagjnWBc
# Priority: CONFIG_GEMINI_API_KEY > GEMINI_API_KEY env var > default
GEMINI_API_KEY = CONFIG_GEMINI_API_KEY or os.getenv('GEMINI_API_KEY', 'AIzaSyCCnt7RH4e_Mb2gRcdpCTZoOKpsagjnWBc')
GEMINI_MODEL = CONFIG_GEMINI_MODEL or os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
GEMINI_TEMPERATURE = float(CONFIG_GEMINI_TEMPERATURE or os.getenv('GEMINI_TEMPERATURE', '0.7'))
GEMINI_TOP_P = float(CONFIG_GEMINI_TOP_P or os.getenv('GEMINI_TOP_P', '0.95'))
GEMINI_MAX_TOKENS = int(CONFIG_GEMINI_MAX_TOKENS or os.getenv('GEMINI_MAX_TOKENS', '8192'))

# ===========================
# Azure OpenAI Configuration
# ===========================
AZURE_OPENAI_API_KEY = CONFIG_AZURE_OPENAI_API_KEY or os.getenv('AZURE_OPENAI_API_KEY', '')
AZURE_OPENAI_ENDPOINT = CONFIG_AZURE_OPENAI_ENDPOINT or os.getenv('AZURE_OPENAI_ENDPOINT', '')
AZURE_OPENAI_VERSION = CONFIG_AZURE_OPENAI_VERSION or os.getenv('AZURE_OPENAI_VERSION', '2024-02-15-preview')
AZURE_OPENAI_MODEL_NAME = CONFIG_AZURE_OPENAI_MODEL_NAME or os.getenv('AZURE_OPENAI_MODEL_NAME', 'gpt-4o')

# ===========================
# Mathpix OCR Configuration (for PDF extraction)
# ===========================
MATHPIX_APP_ID = CONFIG_MATHPIX_APP_ID or os.getenv('MATHPIX_APP_ID', '')
MATHPIX_APP_KEY = CONFIG_MATHPIX_APP_KEY or os.getenv('MATHPIX_APP_KEY', '')

# File Upload Settings for Question Extraction
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTRACTION_FILE_TYPES = [
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'application/msword',  # .doc
    'text/plain',  # .txt
    'application/pdf',  # .pdf (via Mathpix OCR)
    'image/jpeg',  # .jpg (via Mathpix OCR)
    'image/png',  # .png (via Mathpix OCR)
]
EXTRACTION_FILE_EXTENSIONS = ['.txt', '.docx', '.doc', '.pdf', '.jpg', '.jpeg', '.png']
