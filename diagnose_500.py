import os
import django
import sys

# Set up Django environment
sys.path.append('/home/tushar/Pictures/exam_flow_diracai/exam_flow_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'exam_flow_backend.settings')
django.setup()

from exams.models import Exam, ExamAttempt
from accounts.models import User
from django.utils import timezone
from rest_framework.test import APIRequestFactory
from exams.views import student_dashboard_data, ExamListView

def debug_endpoints():
    user = User.objects.filter(role='student').first()
    if not user:
        print("No student user found in DB")
        return

    factory = APIRequestFactory()
    
    print("\n--- Testing student_dashboard_data ---")
    request = factory.get('/api/exams/student-dashboard/')
    request.user = user
    try:
        response = student_dashboard_data(request)
        print(f"Status: {response.status_code}")
        if response.status_code == 500:
            print(f"Data: {response.data}")
    except Exception as e:
        import traceback
        print(f"Exception in student_dashboard_data: {e}")
        traceback.print_exc()

    print("\n--- Testing ExamListView ---")
    view = ExamListView.as_view()
    request = factory.get('/api/exams/exams/')
    request.user = user
    try:
        response = view(request)
        print(f"Status: {response.status_code}")
        if response.status_code == 500:
            print(f"Data: {response.data}")
    except Exception as e:
        import traceback
        print(f"Exception in ExamListView: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    debug_endpoints()
