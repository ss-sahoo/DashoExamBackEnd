# AI Question Extraction - Installation Guide

## Backend Setup

### 1. Install Python Dependencies

```bash
cd exam_flow_backend
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 2. Install and Start Redis (Required for Celery)

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis-server
sudo systemctl enable redis-server
```

**macOS:**
```bash
brew install redis
brew services start redis
```

**Windows:**
Download and install Redis from: https://github.com/microsoftarchive/redis/releases

### 3. Configure Environment Variables

The `.env` file has been updated with the following configurations:
- `GEMINI_API_KEY` - Your Google Gemini API key (already set)
- `CELERY_BROKER_URL` - Redis URL for Celery (default: redis://localhost:6379/0)
- `CELERY_RESULT_BACKEND` - Redis URL for task results
- `GEMINI_MODEL` - Gemini model to use (default: gemini-2.5-flash)

### 4. Start Celery Worker

Open a new terminal and run:

```bash
cd exam_flow_backend
source venv/bin/activate
celery -A exam_flow_backend worker --loglevel=info
```

Keep this terminal running while using the extraction feature.

### 5. Verify Installation

```bash
# Test Redis connection
redis-cli ping
# Should return: PONG

# Test Celery
python manage.py shell
>>> from exam_flow_backend.celery import app
>>> app.control.inspect().active()
# Should return worker information
```

## Frontend Setup

### 1. Install npm Dependencies

```bash
cd Exam_Flow
npm install
```

This will install the new `react-dropzone` package for file uploads.

### 2. Start Development Server

```bash
npm run dev
```

## Testing the Setup

1. Ensure Redis is running: `redis-cli ping`
2. Ensure Celery worker is running (check the terminal)
3. Start Django backend: `python manage.py runserver`
4. Start React frontend: `npm run dev`
5. Navigate to the question editor page

## Troubleshooting

### Redis Connection Error
- Ensure Redis is installed and running
- Check if port 6379 is available
- Verify CELERY_BROKER_URL in .env

### Celery Worker Not Starting
- Ensure Redis is running first
- Check for Python syntax errors
- Verify all dependencies are installed

### Gemini API Errors
- Verify GEMINI_API_KEY is set correctly in .env
- Check API quota and billing status
- Ensure you have access to Gemini API

### File Upload Errors
- Check MAX_UPLOAD_SIZE in settings.py (default: 10MB)
- Verify ALLOWED_EXTRACTION_FILE_TYPES includes your file type
- Check file permissions in upload directory

## Next Steps

After successful installation, you can proceed to implement:
1. Database models (ExtractionJob, ExtractedQuestion)
2. File parsing service
3. Gemini AI extraction service
4. API endpoints
5. Frontend components

Refer to `.kiro/specs/ai-question-extraction/tasks.md` for the complete implementation plan.
