import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginFailureBucket

MAX_FAILURES = 5
WINDOW = timedelta(minutes=15)
LOCKOUT = timedelta(minutes=15)


def _fingerprint(request, login_key):
    remote = request.META.get("REMOTE_ADDR", "")
    raw = f"{remote.lower()}:{login_key.lower()}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).hexdigest()


def is_login_locked(request, login_key):
    bucket = LoginFailureBucket.objects.filter(fingerprint=_fingerprint(request, login_key)).first()
    return bool(bucket and bucket.locked_until and bucket.locked_until > timezone.now())


def record_login_failure(request, login_key):
    fingerprint = _fingerprint(request, login_key)
    now = timezone.now()
    with transaction.atomic():
        bucket, _ = LoginFailureBucket.objects.select_for_update().get_or_create(fingerprint=fingerprint)
        if bucket.window_started_at < now - WINDOW:
            bucket.window_started_at = now
            bucket.failures = 0
            bucket.locked_until = None
        bucket.failures += 1
        if bucket.failures >= MAX_FAILURES:
            bucket.locked_until = now + LOCKOUT
        bucket.save(update_fields=("window_started_at", "failures", "locked_until"))


def clear_login_failures(request, login_key):
    LoginFailureBucket.objects.filter(fingerprint=_fingerprint(request, login_key)).delete()
