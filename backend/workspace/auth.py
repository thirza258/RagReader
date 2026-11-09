"""Bearer tokens for the workspace API.

Sign-up/sign-in issues a token (`rr_` + 43 url-safe characters, 256 bits of
randomness). Only its SHA-256 is stored, so a leaked database does not leak
usable credentials; a fast hash is enough because the input is random, not a
password.
"""
import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from workspace.models import ApiToken

TOKEN_PREFIX = "rr_"
# Signing in again from another browser must not log the first one out, but
# tokens are issued on every sign-in, so the oldest beyond this are pruned.
MAX_TOKENS_PER_USER = 20
# last_used_at is informational; writing it on every request would turn every
# read into a write.
LAST_USED_RESOLUTION = timedelta(minutes=5)
INVALID_TOKEN_MESSAGE = "Your session has expired or the token is invalid. Sign in again."


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(user) -> str:
    """Create a token for `user` and return its plaintext (shown only once)."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    ApiToken.objects.create(user=user, key_hash=hash_token(token))
    stale = list(
        ApiToken.objects.filter(user=user)
        .order_by("-created_at", "-id")
        .values_list("pk", flat=True)[MAX_TOKENS_PER_USER:]
    )
    if stale:
        ApiToken.objects.filter(pk__in=stale).delete()
    return token


class GuestTokenAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword.lower().encode():
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Invalid Authorization header. Send 'Bearer <token>'.")
        try:
            token = parts[1].decode("ascii")
        except UnicodeDecodeError:
            raise AuthenticationFailed(INVALID_TOKEN_MESSAGE)
        if not token.startswith(TOKEN_PREFIX):
            raise AuthenticationFailed(INVALID_TOKEN_MESSAGE)
        record = ApiToken.objects.select_related("user").filter(key_hash=hash_token(token)).first()
        if record is None:
            raise AuthenticationFailed(INVALID_TOKEN_MESSAGE)
        now = timezone.now()
        if record.last_used_at is None or now - record.last_used_at > LAST_USED_RESOLUTION:
            ApiToken.objects.filter(pk=record.pk).update(last_used_at=now)
        return record.user, record

    def authenticate_header(self, request):
        # A value here makes DRF answer missing/invalid credentials with 401
        # (and WWW-Authenticate) instead of 403.
        return self.keyword
