import random
import string
from locust import HttpUser, task, between

class QueueFlowUser(HttpUser):
    """Simulates a single QueueFlow user.
    
    Each instance of this class is one simulated user.
    If you run Locust with 50 users, 50 instances of this class
    are created, each running indepedently.

    HttpUser gives us self.client, - an HTTP client that automatically
    records response times and success/failure for Locust's statistics.
    """
    # wait_time  = between(0.5, 2) means:
    # after each action, wait a random time between o.5 and 2 seconds
    # before doing the next action. This simulates real user behaviour - 
    # humans don't click buttons 100 times per second.
    wait_time = between(0.5, 2)

    def on_start(self):
        """Called once when this simulated user starts.
        Like __inti__ byt runs after the client is ready.
        We create a tenant and API Key so thies user can make
        authenticated requests.
        """

        # Generate a random 8-character suffix so each simulated user
        # get a unique tenant name. Without this, the second user
        # would get "Tenant already exists" error.
        suffix = ''.join(random.choices(string.ascii_lowercase, k=8))

        # Create a tenant - POST /tenants/ doesn't need auth
        response = self.client.post("/tenants/", json={
            "name": f"loadtest -{suffix}"
        })

        # If tenant creation failed, this user can't do anything
        if response.status_code !=201:
            print(f"Failed to create tenant: {response.text}")
            return
        
        tenant_id = response.json()["id"]

        # Create an API key for this tenant
        response = self.client.post(
            f"/tenants/{tenant_id}/api-keys",
            json = {"label": "loadtest"}
        )

        if response.status_code != 201:
            print(f"Failed to create API key: {response.text}")
            return
        
        api_key = response.json()["key"]

        # Set the X-API-Key header for all future requests from this user
        # self.client.headers persists across all requests
        self.client.headers["X-API-Key"] = api_key

        # store taskIDs so we can reference them in get_task
        self.task_ids = []


    @task(5)
    def submit_task(self):
        """Submit a task - the most common operations.
        @task(5) means this runs 5x more often than @task(1).
        Out of every 9 actions: 5 are submits, 3 are list, 1 is get.
        This simulates realistic traffic - most API calls are submissions.
        """

        # Pick a random task type

        task_types = [
            {
                "task_name": "send_email",
                "payload": {
                    "to": "loadttest@exmple.com",
                    "subject": "Load test email",
                    "body": "Testing under load",
                },
            },
            {
                "task_name": "process_image",
                "payload": {
                    "image_url": "https://picsum.photos/800/600.jpg",
                    "width": 200,
                    "height": 200,
                },
            },
            {
                "task_name": "generate_report",
                "payload": {
                    "report_type": "summary",
                },
            },
        ]

        task_data = random.choice(task_types)

        # Pick a random priority
        task_data["priority"] = random.choice([1, 5, 10, 20])

        # 20% chance of adding a delay (test scheduled tasks)
        if random.random() < 0.2:
            task_data["delay_seconds"] = random.randint(5, 15)

        response = self.client.post("/tasks/", json=task_data)

        # Store the task ID for later get_task calls
        if response.status_code == 201:
            self.task_ids.append(response.json()["id"])
            # Keep only the last 20 IDs to avoid memory growth
            if len(self.task_ids) > 20:
                self.task_ids.pop(0)

    @task(3)
    def list_task(self):
        """List task- second mot common operation.
        @task(3) meand this runs 3x more often than @task(1).
        Simulates users checking the dashboard.
        """

        # Random page and page size
        page = random.randint(1,3)
        self.client.get(f"/tasks/?page={page}&page_size=20")

    @task(1)
    def get_task(self):
        """Get a specific task - least common operation.
        
        @task(1) is the baseline frequency.
        Simulates users clicking on a specific task to see details.
        """

        if self.task_ids:
            # Pick a random task from our list
            task_id = random.choice(self.task_ids)
            self.client.get(f"/tasks/{task_id}", name="/tasks/[id]")


class QueueFlowFailureUser(HttpUser):
    """Simulates users submitting tasks that will fail.
    
    This test the retry and DLQ paths under load.
    Separate class so Locust can control the ratio -
    you can run 90% normal users and 10% failure users.
    """

    # Slower pace - we don't want to flood the DLQ
    wait_time = between(5, 15)

    # wieght = 1 means for every 10 QueueFlowUser instances,
    # Locust created 1 QueueFlowFailureUser instance.
    # QueueFlowUser has default wiehgt of 10.
    weight = 1

    def on_start(self):
        """Same setup as QueueFlowUser - create tenant and key."""
        suffix = ''.join(random.choices(string.ascii_lowercase, k=8))
        response = self.client.post("/tenants/", json={
            "name": f"loadtest-fail-{suffix}"
        })
        if response.status_code != 201:
            return
        
        tenant_id = response.json()["id"]
        response = self.client.post(
            f"/tenants/{tenant_id}/api-keys",
            json={"label": "loadtest-fail"}
        )
        if response.status_code != 201:
            return
    
        self.client.headers["X-API-Key"] = response.json()["key"]

    @task
    def submit_failing_task(self):
        """Submit a task with a bad URL - it will fail and retry.
        
        After max_retries(2), it lands in the DLQ.
        This exercises: retry logic, exponential backoff, DLQ push.
        """

        self.client.post("/tasks/", json={
            "task_name": "process_image",
            "payload":
            {
                "image_url": "https://this-url-does-not-exist.invalid/image.jpg",
                "width": 100,
                "height": 100,
            },
            "max_retries": 2,
        })


