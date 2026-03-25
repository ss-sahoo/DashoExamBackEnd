#!/bin/bash

# ============================================
# Exam Flow Backend - Automated Setup Script
# ============================================
# This script sets up the Django backend environment
# Usage: bash setup.sh

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ============================================
# 1. Check Prerequisites
# ============================================
print_info "Checking prerequisites..."

if ! command_exists python3; then
    print_error "Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
print_success "Python $PYTHON_VERSION found"

if ! command_exists pip3; then
    print_error "pip3 is not installed. Please install pip3."
    exit 1
fi
print_success "pip3 found"

# Check for PostgreSQL
if ! command_exists psql; then
    print_warning "PostgreSQL client not found. Make sure PostgreSQL is installed."
else
    print_success "PostgreSQL client found"
fi

# ============================================
# 2. Create Virtual Environment
# ============================================
print_info "Setting up virtual environment..."

if [ -d "venv" ]; then
    print_warning "Virtual environment already exists. Skipping creation."
else
    python3 -m venv venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
source venv/bin/activate
print_success "Virtual environment activated"

# ============================================
# 3. Upgrade pip and install dependencies
# ============================================
print_info "Upgrading pip..."
pip install --upgrade pip

print_info "Installing dependencies from requirements.txt..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    print_success "Dependencies installed successfully"
else
    print_error "requirements.txt not found!"
    exit 1
fi

# ============================================
# 4. Database Configuration
# ============================================
print_info "Checking database configuration..."

# Check if config.py exists
if [ ! -f "config.py" ]; then
    print_warning "config.py not found. Creating from example..."
    cat > config.py << 'EOF'
# Database Configuration
DB_NAME = "exam_flow_db"
DB_USER = "postgres"
DB_PASSWORD = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"

# Secret Key (Change in production!)
SECRET_KEY = "django-insecure-change-this-in-production"

# Debug Mode
DEBUG = True

# Allowed Hosts
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# CORS Configuration
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
EOF
    print_success "config.py created. Please update it with your database credentials."
fi

# ============================================
# 5. Database Setup
# ============================================
print_info "Setting up database..."

# Read database credentials from config.py
DB_NAME=$(grep "DB_NAME" config.py | cut -d'"' -f2)
DB_USER=$(grep "DB_USER" config.py | cut -d'"' -f2)
DB_PASSWORD=$(grep "DB_PASSWORD" config.py | cut -d'"' -f2)

print_info "Database: $DB_NAME, User: $DB_USER"

# Check if database exists
if command_exists psql; then
    print_info "Checking if database exists..."
    if PGPASSWORD=$DB_PASSWORD psql -h localhost -U $DB_USER -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
        print_success "Database '$DB_NAME' already exists"
    else
        print_warning "Database '$DB_NAME' does not exist. Creating..."
        PGPASSWORD=$DB_PASSWORD createdb -h localhost -U $DB_USER $DB_NAME
        print_success "Database '$DB_NAME' created"
    fi
    
    # Enable pgvector extension
    print_info "Enabling pgvector extension..."
    PGPASSWORD=$DB_PASSWORD psql -h localhost -U $DB_USER -d $DB_NAME -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null || print_warning "Could not enable pgvector. Install it if needed."
fi

# ============================================
# 6. Django Migrations
# ============================================
print_info "Running Django migrations..."

python manage.py makemigrations
print_success "Migrations created"

python manage.py migrate
print_success "Migrations applied"

# ============================================
# 7. Create Superuser (Optional)
# ============================================
print_info "Checking for superuser..."

if python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); print(User.objects.filter(is_superuser=True).exists())" | grep -q "True"; then
    print_success "Superuser already exists"
else
    print_warning "No superuser found."
    read -p "Would you like to create a superuser now? (y/n): " create_superuser
    if [ "$create_superuser" = "y" ] || [ "$create_superuser" = "Y" ]; then
        python manage.py createsuperuser
        print_success "Superuser created"
    else
        print_info "You can create a superuser later with: python manage.py createsuperuser"
    fi
fi

# ============================================
# 8. Collect Static Files (Optional)
# ============================================
print_info "Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || print_warning "Static files collection skipped"

# ============================================
# 9. Create necessary directories
# ============================================
print_info "Creating necessary directories..."
mkdir -p media/questions/images
mkdir -p media/questions/attachments
mkdir -p logs
print_success "Directories created"

# ============================================
# 10. Final Setup Summary
# ============================================
echo ""
echo "============================================"
print_success "Backend Setup Complete! 🚀"
echo "============================================"
echo ""
print_info "Setup Summary:"
echo "  ✓ Virtual environment: venv/"
echo "  ✓ Dependencies: Installed"
echo "  ✓ Database: $DB_NAME"
echo "  ✓ Migrations: Applied"
echo "  ✓ Media directories: Created"
echo ""
print_info "Next Steps:"
echo "  1. Activate virtual environment: source venv/bin/activate"
echo "  2. Start development server: python manage.py runserver 0.0.0.0:8000"
echo "  3. Access admin panel: http://localhost:8000/admin"
echo "  4. Access API docs: http://localhost:8000/api/"
echo ""
print_info "Useful Commands:"
echo "  • Run server: python manage.py runserver 0.0.0.0:8000"
echo "  • Create superuser: python manage.py createsuperuser"
echo "  • Make migrations: python manage.py makemigrations"
echo "  • Apply migrations: python manage.py migrate"
echo "  • Shell: python manage.py shell"
echo ""
print_warning "Remember to update config.py with your production settings!"
echo ""

# Ask if user wants to start the server
read -p "Would you like to start the development server now? (y/n): " start_server
if [ "$start_server" = "y" ] || [ "$start_server" = "Y" ]; then
    print_info "Starting development server..."
    python manage.py runserver 0.0.0.0:8000
else
    print_info "Setup complete. Run 'python manage.py runserver 0.0.0.0:8000' to start the server."
fi

