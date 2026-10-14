from django.db import connection
from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answer /healthz before ALLOWED_HOSTS and login checks.

    kamal-proxy probes the container directly with a Host header Django doesn't know.
    Returns 200 when the database answers, 503 otherwise.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            except Exception:
                return HttpResponse("database unavailable", status=503, content_type="text/plain")
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
