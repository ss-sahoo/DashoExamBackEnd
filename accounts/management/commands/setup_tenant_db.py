import os
import psycopg2
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings
from accounts.models import Institute
from accounts.database_utils import register_institute_database

class Command(BaseCommand):
    help = 'Setup a separate database for an institute and run migrations'

    def add_arguments(self, parser):
        parser.add_argument('institute_id', type=int, help='ID of the institute')
        parser.add_argument('--db_name', type=str, help='Database name (default: institute_<id>)')
        parser.add_argument('--create_db', action='store_true', help='Attempt to create the database if it doesn\'t exist')

    def handle(self, *args, **options):
        institute_id = options['institute_id']
        db_name = options['db_name']
        create_db = options['create_db']

        try:
            institute = Institute.objects.using('default').get(id=institute_id)
        except Institute.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"Institute with ID {institute_id} not found."))
            return

        if not db_name:
            # Use a safe name
            db_name = f"exam_flow_inst_{institute.id}"

        # Update institute record in the shared (default) database
        institute.db_name = db_name
        
        # We assume the user/pass/host/port are the same as default unless specified
        # These will be used by the router/dynamic config
        if not institute.db_user:
            institute.db_user = settings.DATABASES['default'].get('USER')
        if not institute.db_host:
            institute.db_host = settings.DATABASES['default'].get('HOST')
        if not institute.db_port:
            institute.db_port = settings.DATABASES['default'].get('PORT')
            
        institute.save(using='default')

        self.stdout.write(f"🚀 Configuring database '{db_name}' for institute '{institute.name}'...")

        if create_db:
            self.stdout.write("🛠️ Attempting to create database in PostgreSQL...")
            try:
                # Connect to 'postgres' maintenance DB
                conn = psycopg2.connect(
                    host=institute.db_host or 'localhost',
                    port=institute.db_port or '5432',
                    user=settings.DATABASES['default'].get('USER'),
                    password=settings.DATABASES['default'].get('PASSWORD'),
                    dbname='postgres'
                )
                conn.autocommit = True
                cur = conn.cursor()
                
                # Check if DB exists
                cur.execute("SELECT 1 FROM pg_database WHERE datname=%s;", (db_name,))
                if not cur.fetchone():
                    cur.execute(f'CREATE DATABASE "{db_name}";')
                    self.stdout.write(self.style.SUCCESS(f" Successfully created database '{db_name}'"))
                else:
                    self.stdout.write(f"ℹ️ Database '{db_name}' already exists.")
                    
                cur.close()
                conn.close()
            except Exception as e:
                self.stderr.write(self.style.WARNING(f"⚠️ Error creating database: {e}"))
                self.stderr.write("Make sure your database user has CREATEDB permissions or create the database manually.")

        # Register the database in settings for the current command process
        register_institute_database(institute)

        # Run migrations on the new database
        self.stdout.write(f"📦 Running migrations on database '{db_name}'...")
        try:
            # Migrating the new DB
            # We exclude 'accounts' migrations for models that are SHARED
            # But we need the tables to exist if the router redirects there.
            # Actually, the router is already configured to keep shared models in 'default'.
            # So 'migrate --database=...' will only create tables for models that ALLOW migrate to that DB.
            call_command('migrate', database=db_name, interactive=False)
            self.stdout.write(self.style.SUCCESS(f" Successfully migrated database '{db_name}'"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"❌ Error running migrations: {e}"))
            
        self.stdout.write(self.style.SUCCESS(f"\n✨ Multi-tenancy setup complete for '{institute.name}'"))
        self.stdout.write(f"Clients should now include 'X-Institute-DB: {db_name}' in headers or login as a user of this institute.")
