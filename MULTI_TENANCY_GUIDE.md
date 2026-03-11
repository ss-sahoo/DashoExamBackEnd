# Multi-Tenancy Database Allocation Guide

This guide explains how to allocate and manage separate databases for each institute in the Exam Flow system.

## 1. Overview
The system uses a **Centralized Shared Model** for core entities and **Isolated Tenant Databases** for operational data.

- **Shared Database (`default`)**: Stores `Institute`, `User` (Auth), `Center`, `Batch`, `Program`, and session data.
- **Tenant Databases (`institute_X`)**: Stores `Exam`, `Question`, `Attempt`, `Result`, `Timetable`, and `OMR` data specific to one institute.

## 2. Setting up a Tenant Database

To allocate a separate database for an existing institute, use the custom management command:

```bash
python manage.py setup_tenant_db <institute_id> --create_db
```

### Arguments:
- `institute_id`: The ID of the institute in your `default` database.
- `--db_name`: (Optional) Specify a custom database name. Defaults to `exam_flow_inst_<id>`.
- `--create_db`: (Optional) Automatically attempts to create the database in PostgreSQL.

### What this command does:
1. Updates the `Institute` record with database connection details.
2. Creates the physical database in PostgreSQL (if `--create_db` is used).
3. Registers the new database in Django settings dynamically.
4. Runs migrations to create all necessary tables in the new database.

## 3. How Routing Works
The system automatically routes database queries based on the "Tenant Context":

### A. Automatic Routing (Middleware)
For API requests, `TenantMiddleware` detects the institute based on:
1. **Header**: `X-Institute-DB: your_db_name`
2. **Authenticated User**: If a user is logged in, their `institute.db_name` is used.

### B. Manual Routing (Code)
In your Python scripts or tests, you can manually set or get the current database:

```python
from accounts.utils import set_current_db, get_current_db, clear_current_db

# Set context
set_current_db('institute_1')

# Now all queries to Exams/Questions will go to institute_1 DB
exams = Exam.objects.all() 

# Queries to Users/Institutes will still go to 'default' DB
users = User.objects.all()

# Clear context
clear_current_db()
```

## 4. Multi-Institute Setup (One User, Many Institutes)
A single user can belong to multiple institutes while maintaining a single login:

1.  **Primary Institute**: The `user.institute` field marks the "Default" institute.
2.  **Additional Institutes**: Use the `UserInstituteMembership` model for extra links.
3.  **Context Switching**: 
    - To switch contexts, send the header `X-Institute-DB: <db_name>`.
    - `TenantMiddleware` verifies that the user is either a `super_admin` or has a valid membership for that database before switching.

## 5. Database Foreign Keys
Because databases are physically separate, database-level Foreign Key constraints across databases are disabled (`db_constraint=False`).
- `Exam -> Institute` (Cross-DB: Works in Django, but no DB constraint)
- `Exam -> Pattern` (Same-DB: Normal DB constraint)

## 5. Deployment Considerations
1. **DB Permissions**: Ensure your PostgreSQL user has `CREATEDB` permissions if using `--create_db`, or create databases manually.
2. **Connections**: Each active tenant database adds to the total connection count. Use connection pooling (like PgBouncer) if scaling to many institutes.
3. **Backup**: Remember that each institute's data is now in a separate database and needs its own backup strategy.
