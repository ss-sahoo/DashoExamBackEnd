# Exam Flow Backend - Server Deployment Report

**Date:** November 28, 2025  
**Server:** exams.dashoapp.com (128.199.17.132)  
**OS:** Ubuntu 20.04 LTS  
**Python Version:** 3.9.5  
**User:** sammy

---

## 📁 Server Folder Structure

```
/home/sammy/
├── exam_flow_backend/              # Main Django application
│   ├── venv/                       # Python 3.9 virtual environment
│   ├── exam_flow_backend/          # Django project directory
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── celery.py              # Celery configuration
│   ├── questions/                  # Questions app
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── tasks.py               # Celery tasks
│   │   ├── services/
│   │   │   ├── gemini_extraction.py
│   │   │   └── extraction_pipeline.py
│   │   └── migrations/
│   ├── exams/                      # Exams app
│   ├── accounts/                   # Accounts app
│   ├── logs/                       # Application logs
│   │   ├── access.log             # Gunicorn access logs
│   │   ├── error.log              # Gunicorn error logs
│   │   └── celery.log             # Celery worker logs
│   ├── media/                      # Uploaded files
│   ├── staticfiles/                # Collected static files
│   ├── requirements.txt            # Python dependencies
│   ├── manage.py
│   └── .env                        # Environment variables
│
├── exam_flow_frontend/             # React frontend application
│
├── venv_old/                       # Backup of old Python 3.8 venv
└── venv_python38_backup/           # Another backup

/etc/systemd/system/
├── exam_flow.service               # Django/Gunicorn service
└── celery.service                  # Celery worker service

/etc/nginx/sites-available/
└── exam_flow                       # Nginx configuration

/var/run/celery/
└── celery.pid                      # Celery process ID file
```

---

## 🔧 System Services

### 1. Django Application Service (`exam_flow.service`)

**Location:** `/etc/systemd/system/exam_flow.service`

**Key Points:**
- Runs on port `8010` (localhost only)
- Uses Python 3.9 virtual environment
- Proxied by Nginx on ports 80/443
- Auto-restarts on failure
- Logs to `/home/sammy/exam_flow_backend/logs/`

---

### 2. Celery Worker Service (`celery.service`)

**Location:** `/etc/systemd/system/celery.service`

**Key Points:**
- Processes background tasks (question extraction)
- Requires Redis server
- Logs to `/home/sammy/exam_flow_backend/logs/celery.log`
- Auto-restarts on failure

---

### 3. Redis Server

**Purpose:** Message broker for Celery tasks  
**Port:** 6379 (localhost)  
**Service:** `redis-server.service`

---

### 4. PostgreSQL Database

**Purpose:** Main database  
**Service:** `postgresql.service`  
**Extensions:** pgvector (for vector embeddings)

---

### 5. Nginx Web Server

**Configuration:** `/etc/nginx/sites-available/exam_flow`

**Routes:**
- `/` → Frontend (React app)
- `/api/` → Backend (Django on port 8010)
- `/admin/` → Django admin
- `/static/` → Static files
- `/media/` → Uploaded media

**SSL:** Managed by Certbot (Let's Encrypt)

---

## 🔑 Environment Variables

**Location:** `/home/sammy/exam_flow_backend/.env`

**Key Variables:**
- `ENABLE_PGVECTOR=1` - Enables pgvector for embeddings
- `GEMINI_API_KEY` - Google Gemini AI API key
- `GEMINI_MODEL=gemini-2.0-flash`
- `DATABASE_URL` - PostgreSQL connection string
- `SECRET_KEY` - Django secret key
- `DEBUG=False` - Production mode

---

## 🚀 Deployment Workflow

### Local Development
```bash
cd ~/Pictures/exam_flow_diracai/exam_flow_backend
# Make changes
git add -A
git commit -m "Description of changes"
git push
```

### Server Deployment
```bash
# SSH to server
ssh sammy@128.199.17.132

# Navigate to project
cd ~/exam_flow_backend
source venv/bin/activate

# Pull latest changes
git pull

# Install new dependencies (if any)
pip install -r requirements.txt

# Run migrations (if any)
python manage.py migrate

# Restart services
sudo systemctl restart exam_flow.service
sudo systemctl restart celery.service

# Check status
sudo systemctl status exam_flow.service --no-pager
sudo systemctl status celery.service --no-pager
```

---

## 🔍 Monitoring & Logs

### View Logs
```bash
# Django application logs
tail -f /home/sammy/exam_flow_backend/logs/error.log

# Celery worker logs
tail -f /home/sammy/exam_flow_backend/logs/celery.log

# System service logs
sudo journalctl -u exam_flow.service -f
sudo journalctl -u celery.service -f
```

### Check Service Status
```bash
sudo systemctl status exam_flow.service
sudo systemctl status celery.service
sudo systemctl status redis-server
sudo systemctl status postgresql
sudo systemctl status nginx
```

---

## 📝 Important Notes

1. **Python Version:** Server uses Python 3.9.5 (upgraded from 3.8.10)
2. **Celery File:** Renamed from `celery_app.py` to `celery.py` to fix circular imports
3. **Environment Variable:** `ENABLE_PGVECTOR=1` must be set for vector operations
4. **Gunicorn Config:** Removed `--chdir` to fix import issues
5. **Service Type:** Changed from `Type=notify` to `Type=simple` for compatibility

---

**Report Generated:** November 28, 2025
