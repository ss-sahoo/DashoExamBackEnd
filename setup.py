#!/usr/bin/env python3
"""
Setup script for Exam Flow Backend
"""

import os
import sys
import subprocess
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f" {description} completed successfully")
        return result
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e.stderr}")
        return None

def setup_database():
    """Setup PostgreSQL database"""
    print("\n📊 Setting up PostgreSQL database...")
    
    # Create database if it doesn't exist
    db_commands = [
        "sudo -u postgres psql -c \"CREATE DATABASE exam_flow_db;\" 2>/dev/null || echo 'Database might already exist'",
        "sudo -u postgres psql -c \"CREATE USER exam_flow_user WITH PASSWORD 'exam_flow_password';\" 2>/dev/null || echo 'User might already exist'",
        "sudo -u postgres psql -c \"GRANT ALL PRIVILEGES ON DATABASE exam_flow_db TO exam_flow_user;\" 2>/dev/null || echo 'Privileges might already be granted'",
    ]
    
    for cmd in db_commands:
        run_command(cmd, "Database setup")

def create_env_file():
    """Create environment file"""
    env_content = """SECRET_KEY=django-insecure-change-this-in-production-1234567890
DEBUG=True
DATABASE_URL=postgresql://exam_flow_user:exam_flow_password@localhost:5432/exam_flow_db
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
"""
    
    env_file = Path(".env")
    if not env_file.exists():
        with open(env_file, "w") as f:
            f.write(env_content)
        print(" Created .env file")
    else:
        print("ℹ️  .env file already exists")

def main():
    """Main setup function"""
    print("🚀 Setting up Exam Flow Backend...")
    
    # Check if we're in the right directory
    if not Path("manage.py").exists():
        print("❌ Please run this script from the exam_flow_backend directory")
        sys.exit(1)
    
    # Create virtual environment if it doesn't exist
    if not Path("venv").exists():
        run_command("python3 -m venv venv", "Creating virtual environment")
    
    # Install requirements
    run_command("venv/bin/pip install -r requirements.txt", "Installing requirements")
    
    # Create environment file
    create_env_file()
    
    # Setup database
    setup_database()
    
    # Run migrations
    run_command("venv/bin/python manage.py migrate", "Running database migrations")
    
    # Create superuser
    print("\n👤 Creating superuser...")
    print("You'll be prompted to enter superuser details...")
    run_command("venv/bin/python manage.py createsuperuser", "Creating superuser")
    
    # Create sample data
    print("\n📝 Creating sample data...")
    run_command("venv/bin/python manage.py shell -c \"from accounts.models import Institute; Institute.objects.get_or_create(name='Demo University', domain='demo.edu', contact_email='admin@demo.edu')\"", "Creating sample institute")
    
    print("\n🎉 Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Start the development server: source venv/bin/activate && python manage.py runserver")
    print("2. Access admin panel: http://localhost:8000/admin/")
    print("3. API endpoints: http://localhost:8000/api/")

if __name__ == "__main__":
    main()
