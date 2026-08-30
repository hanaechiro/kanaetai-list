from django.db.models import F
from django.utils import timezone

from .models import UserActivity


class UserActivityMiddleware:
    """Record one lightweight daily activity row for authenticated Wishly users."""

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
            now = timezone.now()
            activity, _ = UserActivity.objects.get_or_create(
                user=user,
                date=timezone.localdate(),
                defaults={
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "request_count": 0,
                },
            )
            UserActivity.objects.filter(pk=activity.pk).update(
                last_seen_at=now,
                request_count=F("request_count") + 1,
            )
        return response
