from locust import HttpUser, task, between

class ExamUser(HttpUser):
    wait_time = between(1, 2)

    def on_start(self):
        self.headers = {
            "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsImV4cCI6MTc3Mzg5MDI4NSwiaWF0IjoxNzczMjg1NDg1LCJqdGkiOiI0NGRjNjJmYjY4MTM0YmVhYTRjMmVlZWFkOGIzYTRkYSIsInVzZXJfaWQiOjEsImRldmljZV9maW5nZXJwcmludCI6ImZiZWU2YTJmNjdlNTdmZGY0YjRhNWM5MTMyMmNiMGM5Mjk1MTIwMDg5ZmQ2ZTIyOWM5ZGRjMjMyZWUwNDQ4ODMifQ.X69qEBMP8_PHQP_1uXX2x4hEl4KyC9xGCR8lqd8l8_8"
        }

    @task
    def exams(self):
        with self.client.get("api/exams/exams/", headers=self.headers, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Failed with {response.status_code}")