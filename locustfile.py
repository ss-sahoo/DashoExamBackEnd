from locust import HttpUser, task, between

class ExamUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def get_exams(self):
        self.client.get("/api/exams/")

    @task
    def get_patterns(self):
        self.client.get("/api/patterns/")

    @task
    def admin_page(self):
        self.client.get("/admin/")
