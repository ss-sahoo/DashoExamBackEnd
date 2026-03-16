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
settings.DATABASES['exam_flow_inst_31'] = {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': 'exam_flow_inst_31',
    'USER': default_db['USER'],
    'PASSWORD': default_db['PASSWORD'],
    'HOST': default_db['HOST'],
    'PORT': default_db['PORT'],
}

print("Running migrations on exam_flow_inst_31...")
call_command('migrate', database='exam_flow_inst_31', interactive=False)
print("Done!")
