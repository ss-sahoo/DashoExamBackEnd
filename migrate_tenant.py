import os
import django
import sys

sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from django.conf import settings
from django.core.management import call_command
from accounts.models import Institute

inst = Institute.objects.get(id=31)
default_db = settings.DATABASES['default']

# Register tenant DB before calling migrate
# Django 4.2 requires all these keys to be present
tenant_db = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'exam_flow_inst_31',
    'USER': default_db['USER'],
    'PASSWORD': default_db['PASSWORD'],
    'HOST': default_db['HOST'],
    'PORT': default_db['PORT'],
}
# Copy ALL keys from default so Django 4.2 doesn't complain about missing ones
for key, val in default_db.items():
    if key not in tenant_db:
        tenant_db[key] = val
# Override the name back since copying default would overwrite it
tenant_db['NAME'] = 'exam_flow_inst_31'
settings.DATABASES['exam_flow_inst_31'] = tenant_db

print("Running migrations on exam_flow_inst_31...")
# Migrate only tenant-specific apps, skip shared apps (accounts, auth, contenttypes, sessions, admin)
tenant_apps = ['exams', 'questions', 'omr', 'patterns', 'timetable']
for app in tenant_apps:
    print(f"  Migrating {app}...")
    call_command('migrate', app, database='exam_flow_inst_31', interactive=False)
print("Done!")
