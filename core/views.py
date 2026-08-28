from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse


def health_check(request):
    """Report application health, including critical infrastructure.

    Milestone 1 (04_MVP_IMPLEMENTATION_PLAN.md) requires a basic health
    endpoint confirming the app can reach PostgreSQL. Redis and other
    dependencies can be added here as they become part of the request path.
    """
    database_ok = _database_is_reachable()
    status = "ok" if database_ok else "degraded"
    payload = {
        "status": status,
        "database": "ok" if database_ok else "unavailable",
    }
    return JsonResponse(payload, status=200 if database_ok else 503)


def _database_is_reachable():
    try:
        connections["default"].cursor()
        return True
    except OperationalError:
        return False
