import os
from decouple import config

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-this-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
DATABASE_URL = config('DATABASE_URL', default='postgresql://postgres:password@localhost:5432/exam_flow_db')
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175').split(',')

# AI Configuration
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
GEMINI_API_KEY = config('GEMINI_API_KEY', default='')  # FREE Google Gemini API
USE_OLLAMA = config('USE_OLLAMA', default='false')  # Use free local AI (needs 2GB+ RAM)
OLLAMA_BASE_URL = config('OLLAMA_BASE_URL', default='http://localhost:11434')

# AI Priority: Gemini (free) -> Ollama (free, needs RAM) -> OpenAI (paid)
