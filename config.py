import os

# Try python-decouple first (in requirements.txt)
try:
    from decouple import config
    get_config = config
except ImportError:
    # Fallback to python-dotenv
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Simple fallback using os.getenv
    def get_config(key, default='', cast=None):
        """Get config from environment variables"""
        value = os.getenv(key, default)
        if cast == bool:
            return str(value).lower() in ('true', '1', 'yes', 'on')
        return value

SECRET_KEY = get_config('SECRET_KEY', default='django-insecure-change-this-in-production')
DEBUG = get_config('DEBUG', default='False', cast=bool)

# Build DATABASE_URL from components or use full URL
DB_NAME = get_config('DB_NAME', 'exam_flow_db')
DB_USER = get_config('DB_USER', 'exam_flow_user')
DB_PASSWORD = get_config('DB_PASSWORD', '')
DB_HOST = get_config('DB_HOST', 'localhost')
DB_PORT = get_config('DB_PORT', '5432')

# Construct DATABASE_URL
DATABASE_URL = get_config('DATABASE_URL', 
    default=f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}')

ALLOWED_HOSTS = get_config('ALLOWED_HOSTS', default='localhost,127.0.0.1,128.199.17.132,exams.dashoapp.com,exam.dashoapp.com,dashoapp.com').split(',')
CORS_ALLOWED_ORIGINS = get_config('CORS_ALLOWED_ORIGINS', 
    default='http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://128.199.17.132,http://exams.dashoapp.com,http://exam.dashoapp.com,https://exams.dashoapp.com,https://exam.dashoapp.com').split(',')

# AI Configuration - Disabled for low-memory deployment
OPENAI_API_KEY = get_config('OPENAI_API_KEY', default='')
# Primary Gemini API Key: AIzaSyBRBA_VMMB1B0zzYuL4QJWUmRmTE90TsmI
# Previous key (backup): AIzaSyCCnt7RH4e_Mb2gRcdpCTZoOKpsagjnWBc
# Can be overridden by GEMINI_API_KEY environment variable
GEMINI_API_KEY = get_config('GEMINI_API_KEY', default='AIzaSyBRBA_VMMB1B0zzYuL4QJWUmRmTE90TsmI')
USE_OLLAMA = get_config('USE_OLLAMA', default='false')
OLLAMA_BASE_URL = get_config('OLLAMA_BASE_URL', default='http://localhost:11434')

# Mathpix OCR Configuration (for PDF extraction)
MATHPIX_APP_ID = get_config('MATHPIX_APP_ID', default='')
MATHPIX_APP_KEY = get_config('MATHPIX_APP_KEY', default='')

# Email Configuration
EMAIL_HOST = get_config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = get_config('EMAIL_PORT', default='587')
EMAIL_USE_TLS = get_config('EMAIL_USE_TLS', default='True', cast=bool)
EMAIL_HOST_USER = get_config('EMAIL_HOST_USER', default='diracai.info@gmail.com')
EMAIL_HOST_PASSWORD = get_config('EMAIL_HOST_PASSWORD', default='fibmduvwoxsjtjvh')
DEFAULT_FROM_EMAIL = get_config('DEFAULT_FROM_EMAIL', default='Exam Flow System <diracai.info@gmail.com>')
