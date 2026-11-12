"""Bearer tokens for the workspace API and every legacy endpoint.

Sign-up/sign-in issues a token (`rr_` + 43 url-safe characters, 256 bits of
randomness). Only its SHA-256 is stored, so a leaked database does not leak
usable credentials; a fast hash is enough because the input is random, not a
password. Tokens expire after RAG_TOKEN_TTL_DAYS and are revoked by sign-out.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import exception_handler as drf_exception_handler

from workspace.errors import api_exception_handler
from workspace.models import ApiToken

TOKEN_PREFIX = "rr_"
# Longer than any token this module issues; anything longer is not looked up.
MAX_TOKEN_LENGTH = 128
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
    ApiToken.objects.filter(user=user, expires_at__lte=timezone.now()).delete()
    stale = list(
        ApiToken.objects.filter(user=user)
        .order_by("-created_at", "-id")
        .values_list("pk", flat=True)[MAX_TOKENS_PER_USER:]
    )
    if stale:
        ApiToken.objects.filter(pk__in=stale).delete()
    return token


def resolve_token(token):
    """The live ApiToken (with its user) for a plaintext token, else None.

    None covers a malformed, unknown, revoked or expired token alike; an
    expired one is deleted on sight. Shared by the HTTP authentication class
    and the analysis WebSocket, which authenticates with its first frame.
    """
    if not isinstance(token, str) or not token.startswith(TOKEN_PREFIX) or len(token) > MAX_TOKEN_LENGTH:
        return None
    record = ApiToken.objects.select_related("user").filter(key_hash=hash_token(token)).first()
    if record is None:
        return None
    now = timezone.now()
    if record.expires_at <= now:
        ApiToken.objects.filter(pk=record.pk).delete()
        return None
    if record.last_used_at is None or now - record.last_used_at > LAST_USED_RESOLUTION:
        ApiToken.objects.filter(pk=record.pk).update(last_used_at=now)
    return record


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
        record = resolve_token(token)
        if record is None:
            raise AuthenticationFailed(INVALID_TOKEN_MESSAGE)
        return record.user, record

    def authenticate_header(self, request):
        # A value here makes DRF answer missing/invalid credentials with 401
        # (and WWW-Authenticate) instead of 403.
        return self.keyword


def legacy_exception_handler(exc, context):
    """Auth and throttling failures get the error envelope; the rest is unchanged.

    The legacy views build their own error bodies inside `post`/`get`, so only
    what DRF raises before the handler runs (no or bad token) reaches here.
    """
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed, exceptions.Throttled)):
        return api_exception_handler(exc, context)
    return drf_exception_handler(exc, context)


class TokenRequiredMixin:
    """For the legacy and deep-analysis views: the workspace API's bearer token.

    Without a valid token the view answers 401 with `WWW-Authenticate: Bearer`
    and the error envelope. Views must still check that every username and id
    they are given belongs to `request.user`.
    """

    authentication_classes = [GuestTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_exception_handler(self):
        return legacy_exception_handler


class AuthRateThrottle(ScopedRateThrottle):
    """Per-client limit for the views whose `throttle_scope` is "auth".

    The rate is read from settings.RAG_AUTH_THROTTLE_RATE on every request
    (DRF's own throttles capture their rates at import), so deployments and
    tests can change it. An empty rate disables the throttle.
    """

    def get_rate(self):
        return getattr(settings, "RAG_AUTH_THROTTLE_RATE", None) or None
