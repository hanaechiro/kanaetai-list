from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from .models import UserActivity


class UserActivityMiddleware:
    """Record one lightweight daily activity row for authenticated Wishly users."""

    UPDATE_INTERVAL = timedelta(minutes=1)

    EXCLUDED_PREFIXES = (
        "/admin/",
        "/management/",
        "/static/",
        "/media/",
        "/service-worker.js",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and request.method in {"GET", "POST"}
            and response.status_code < 500
            and not request.path.startswith(self.EXCLUDED_PREFIXES)
        ):
            today = timezone.localdate()
            now = timezone.now()
            activity = UserActivity.objects.filter(user=user, date=today).values("pk", "last_seen_at").first()

            if activity is None:
                UserActivity.objects.create(
                    user=user,
                    date=today,
                    first_seen_at=now,
                    last_seen_at=now,
                    request_count=1,
                )
            elif activity["last_seen_at"] is None or now - activity["last_seen_at"] >= self.UPDATE_INTERVAL:
                UserActivity.objects.filter(pk=activity["pk"]).update(
                    last_seen_at=now,
                    request_count=F("request_count") + 1,
                )
        return response
