from locust import HttpUser, task, between

class ExamUser(HttpUser):
    wait_time = between(1, 2)

    def on_start(self):
        # Login first
        response = self.client.post(
            "api/auth/login/",
            json={
                "email": "mtapas.mohanty95@gmail.com",
                "password": "Test@1234"
            }
        )

        data = response.json()

        if "tokens" in data:
            self.token = data["tokens"]["access"]

            self.headers = {
                "Authorization": f"Bearer {self.token}"
            }

            print("Login successful")
        else:
            print("Login failed:", data)

    @task
    def exams(self):
        with self.client.get("api/exams/exams/", headers=self.headers, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Failed with {response.status_code}")