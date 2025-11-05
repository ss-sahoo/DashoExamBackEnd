# Exam Flow Backend

A comprehensive Django REST API backend for the Exam Flow application, providing institute-based authentication, exam management, and question handling.

## Features

- **Institute-based Authentication**: Email-based login with institute domain validation
- **Role-based Access Control**: Super Admin, Institute Admin, Exam Admin, Teacher, Student roles
- **Exam Pattern System**: Flexible exam structure with sections and question types
- **Question Management**: Question banks, templates, and bulk import capabilities
- **Exam Security**: Anti-cheating measures and proctoring options
- **Analytics**: Comprehensive exam analytics and reporting

## Technology Stack

- **Backend**: Django 5.2.7 + Django REST Framework
- **Database**: PostgreSQL
- **Authentication**: Token-based authentication
- **API**: RESTful API with comprehensive endpoints

## Installation

### Prerequisites

- Python 3.8+
- PostgreSQL 12+
- pip
- Git

### Quick Setup (Automated) 🚀

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Trushank03/Exam_backendDjango.git
   cd Exam_backendDjango
   ```

2. **Run the automated setup script**:
   ```bash
   bash setup.sh
   ```
   
   This script will:
   - ✓ Check prerequisites (Python, pip, PostgreSQL)
   - ✓ Create virtual environment
   - ✓ Install all dependencies
   - ✓ Create and configure database
   - ✓ Run migrations
   - ✓ Create media directories
   - ✓ Optionally create superuser
   - ✓ Start the development server

3. **Access the application**:
   - Backend API: `http://localhost:8000/api/`
   - Admin Panel: `http://localhost:8000/admin/`

### Manual Setup

1. **Create virtual environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Setup PostgreSQL database**:
   ```sql
   CREATE DATABASE exam_flow_db;
   CREATE USER exam_flow_user WITH PASSWORD 'exam_flow_password';
   GRANT ALL PRIVILEGES ON DATABASE exam_flow_db TO exam_flow_user;
   ```

4. **Create environment file**:
   ```bash
   cp .env.example .env
   # Edit .env with your database credentials
   ```

5. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create superuser**:
   ```bash
   python manage.py createsuperuser
   ```

7. **Start server**:
   ```bash
   python manage.py runserver
   ```

## API Endpoints

### Authentication
- `POST /api/auth/register/` - User registration
- `POST /api/auth/login/` - User login
- `POST /api/auth/logout/` - User logout
- `GET /api/auth/profile/` - Get user profile
- `PUT /api/auth/profile/` - Update user profile

### Institutes
- `GET /api/auth/institutes/` - List institutes
- `GET /api/auth/institutes/{id}/` - Get institute details

### Exam Patterns
- `GET /api/patterns/patterns/` - List exam patterns
- `POST /api/patterns/patterns/` - Create exam pattern
- `GET /api/patterns/patterns/{id}/` - Get pattern details
- `PUT /api/patterns/patterns/{id}/` - Update pattern
- `DELETE /api/patterns/patterns/{id}/` - Delete pattern

### Exams
- `GET /api/exams/exams/` - List exams
- `POST /api/exams/exams/` - Create exam
- `GET /api/exams/exams/{id}/` - Get exam details
- `POST /api/exams/start-exam/` - Start exam attempt
- `POST /api/exams/submit-exam/` - Submit exam

### Questions
- `GET /api/questions/questions/` - List questions
- `POST /api/questions/questions/` - Create question
- `GET /api/questions/questions/{id}/` - Get question details
- `POST /api/questions/bulk-import/` - Bulk import questions

## Database Models

### Core Models

1. **Institute**: Organization/institution management
2. **User**: Custom user model with institute-based authentication
3. **ExamPattern**: Exam structure templates
4. **PatternSection**: Sections within exam patterns
5. **Exam**: Individual exam instances
6. **Question**: Question bank items
7. **ExamAttempt**: Student exam attempts
8. **ExamResult**: Detailed exam results

### User Roles

- **Super Admin**: Full system access
- **Institute Admin**: Institute-level management
- **Exam Admin**: Exam creation and management
- **Teacher**: Question creation and exam monitoring
- **Student**: Exam taking and result viewing

## Security Features

- **Institute Domain Validation**: Email domain must match institute
- **Role-based Permissions**: Granular access control
- **Exam Security Settings**: Anti-cheating measures
- **Token Authentication**: Secure API access
- **CORS Configuration**: Cross-origin request handling

## Development

### Running Tests
```bash
python manage.py test
```

### Creating Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### Admin Panel
Access the Django admin panel at `http://localhost:8000/admin/`

### API Documentation
The API follows RESTful conventions. Use tools like Postman or curl to test endpoints.

## Configuration

### Environment Variables

- `SECRET_KEY`: Django secret key
- `DEBUG`: Debug mode (True/False)
- `DATABASE_URL`: PostgreSQL connection string
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts
- `CORS_ALLOWED_ORIGINS`: Comma-separated list of CORS origins

### Database Configuration

The application uses PostgreSQL. Update the `DATABASE_URL` in your environment file:

```
DATABASE_URL=postgresql://username:password@localhost:5432/exam_flow_db
```

## Deployment

### Production Settings

1. Set `DEBUG=False`
2. Use a strong `SECRET_KEY`
3. Configure proper database credentials
4. Set up static file serving
5. Configure email settings
6. Use HTTPS

### Docker Deployment

```dockerfile
FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "exam_flow_backend.wsgi:application"]
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For support and questions, please contact the development team or create an issue in the repository.
