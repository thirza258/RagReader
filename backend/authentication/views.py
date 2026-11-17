"""Accounts: sign-up (create, or claim a legacy account), sign-in and sign-out.

A GuestUser is a username, an email and, since passwords were added, a
password hash. Tokens are only ever issued against a password:

* sign-up with PASSWORD creates an account (201 + token), or sets the
  password of an account created before passwords existed when the username
  *and* email match it exactly (one-time claim, 200 + token);
* sign-in checks the password (200 + token). The identifier is looked up as
  an email when it contains "@" and as a username otherwise, and new
  usernames may not contain "@", so one value can never match two accounts.

Every new account has a password: sign-up without PASSWORD is a 400, so no
claimable passwordless account can be created any more. Sign-in answers an
account that has no password yet exactly like a wrong password, so it does
not reveal which accounts can still be claimed.

Sign-up keeps the legacy `status/message/data` envelope and only adds fields
(`token`, and `error` on failures); sign-in and sign-out are new endpoints and
use the workspace API's error envelope. Both sign-up and sign-in are throttled
per client (scope "auth", settings.RAG_AUTH_THROTTLE_RATE) and per submitted
account identifier (settings.RAG_AUTH_IDENTIFIER_THROTTLE_RATE), so rotating
client addresses does not buy more guesses against one account.
"""
import logging
import secrets
import time

from django.contrib.auth.hashers import check_password, get_hasher, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import exceptions
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from common.schema import get_responses
from router.models import GuestUser
from router.serializers import SignInSerializer, SignUpSerializer
from workspace.auth import AuthIdentifierThrottle, AuthRateThrottle, hash_token, issue_token
from workspace.errors import ApiError, api_exception_handler, describe_exception, error_object
from workspace.models import ApiToken
from workspace.views.base import OwnedAPIView

logger = logging.getLogger(__name__)

INVALID_REQUEST_MESSAGE = "The request contains invalid or missing fields."
ACCOUNT_EXISTS_MESSAGE = (
    "That username or email is already registered. Sign in instead. An account created "
    "before passwords existed can be given one here, using its exact username and email."
)
WEAK_PASSWORD_MESSAGE = "Choose a different password."
INVALID_CREDENTIALS_MESSAGE = (
    "The username, email or password is incorrect. An account created before passwords "
    "existed needs one first: use Create account with its exact username and email."
)
USERNAME_AT_MESSAGE = "Usernames cannot contain \"@\"."


# ── Sign-up (legacy envelope) ────────────────────────────────────────────────

def legacy_error(http_status, code, message, *, retryable=False, details=None, headers=None):
    """The sign-up envelope (`status`, `message`, `data`) plus the `error` object."""
    return Response({
        "status": http_status,
        "message": message,
        "timestamp": time.time(),
        "data": None,
        "error": error_object(code, message, retryable=retryable, details=details),
    }, status=http_status, headers=headers)


def sign_up_exception_handler(exc, context):
    http_status, error = describe_exception(exc)
    headers = None
    if isinstance(exc, exceptions.Throttled) and exc.wait:
        headers = {"Retry-After": str(int(exc.wait))}
    return legacy_error(http_status, error["code"], error["message"], retryable=error["retryable"],
                        details=error["details"], headers=headers)


def password_errors(password, user):
    """Messages from AUTH_PASSWORD_VALIDATORS; `user` feeds the similarity check."""
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        return list(exc.messages)
    return []


def account_exists():
    return legacy_error(409, "account_exists", ACCOUNT_EXISTS_MESSAGE)


def weak_password(errors):
    return legacy_error(400, "invalid_request", WEAK_PASSWORD_MESSAGE, details={"PASSWORD": errors})


class SignUpView(GenericAPIView):
    serializer_class = SignUpSerializer
    # A stale token from an earlier session must not turn sign-up into a 401.
    authentication_classes = []
    permission_classes = []
    throttle_classes = [AuthRateThrottle, AuthIdentifierThrottle]
    throttle_scope = "auth"

    def get_exception_handler(self):
        return sign_up_exception_handler

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return legacy_error(400, "invalid_request", INVALID_REQUEST_MESSAGE, details=serializer.errors)
        email = serializer.validated_data["EMAIL"]
        username = serializer.validated_data["USERNAME"]
        password = serializer.validated_data["PASSWORD"]
        try:
            return self.sign_up_with_password(username, email, password)
        except Exception:
            logger.exception("Sign-up failed")
            return legacy_error(500, "internal_error", "Sign-up could not be completed. Try again.", retryable=True)

    def sign_up_with_password(self, username, email, password):
        by_username = GuestUser.objects.filter(username=username).first()
        by_email = GuestUser.objects.filter(email=email).first()

        if by_username is None and by_email is None:
            if "@" in username:
                return legacy_error(400, "invalid_request", INVALID_REQUEST_MESSAGE,
                                    details={"USERNAME": [USERNAME_AT_MESSAGE]})
            user = GuestUser(username=username, email=email)
            errors = password_errors(password, user)
            if errors:
                return weak_password(errors)
            user.set_password(password)
            try:
                with transaction.atomic():
                    user.save()
            except IntegrityError:
                return account_exists()  # Someone else took the name a moment ago.
            return get_responses().response_201({
                "response": "User created successfully!", "username": username, "email": email,
                "token": issue_token(user),
            })

        # One-time claim: an account from before passwords, matched on both
        # its exact username and its exact email.
        user = by_username
        if user is None or by_email is None or user.pk != by_email.pk or user.has_password:
            return account_exists()
        errors = password_errors(password, user)
        if errors:
            return weak_password(errors)
        claimed = GuestUser.objects.filter(pk=user.pk, password="").update(
            password=make_password(password), updated_at=timezone.now(),
        )
        if not claimed:
            return account_exists()  # A concurrent claim won.
        # Whatever tokens the account collected before it had a password were
        # issued to anyone who knew its username and email.
        ApiToken.objects.filter(user=user).delete()
        logger.info("Password set for legacy account %s", user.pk)
        return get_responses().response_200({
            "response": "Password set for your existing account.", "username": username, "email": email,
            "token": issue_token(user), "claimed": True,
        })


# ── Sign-in and sign-out (workspace API envelope) ───────────────────────────

_dummy_hashes = {}


def dummy_password_hash():
    """A real hash under the current default hasher, for unknown accounts.

    Checking a password against it costs what checking a real account costs,
    so response time does not reveal whether the account exists.
    """
    algorithm = get_hasher("default").algorithm
    if algorithm not in _dummy_hashes:
        _dummy_hashes[algorithm] = make_password(secrets.token_urlsafe(16))
    return _dummy_hashes[algorithm]


def find_account(identifier):
    """The account an identifier names: by email if it contains "@", else by username.

    Never both. A legacy username that equals another account's email would
    otherwise let one identifier resolve to either account.
    """
    field = "email" if "@" in identifier else "username"
    return GuestUser.objects.filter(**{field: identifier}).first()


def invalid_credentials():
    return ApiError("invalid_credentials", INVALID_CREDENTIALS_MESSAGE, status=401)


class SignInView(GenericAPIView):
    serializer_class = SignInSerializer
    authentication_classes = []
    permission_classes = []
    throttle_classes = [AuthRateThrottle, AuthIdentifierThrottle]
    throttle_scope = "auth"

    def get_exception_handler(self):
        return api_exception_handler

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data.get("USERNAME") or serializer.validated_data.get("EMAIL")
        password = serializer.validated_data["PASSWORD"]

        user = find_account(identifier)
        if user is None or not user.has_password:
            # Same work and same answer as a wrong password: neither a missing
            # account nor a still-claimable one is revealed.
            check_password(password, dummy_password_hash())
            raise invalid_credentials()
        if not user.check_password(password):
            raise invalid_credentials()

        token = issue_token(user)
        expires_at = ApiToken.objects.filter(key_hash=hash_token(token)).values_list("expires_at", flat=True).first()
        return Response({"token": token, "username": user.username, "email": user.email, "expires_at": expires_at})


class SignOutView(OwnedAPIView):
    """Revokes the token the request was made with; other sessions stay signed in."""

    @extend_schema(tags=["Accounts"], operation_id="sign_out", summary="Revoke the presenting token",
                   request=None, responses={204: None})
    def post(self, request):
        ApiToken.objects.filter(pk=request.auth.pk).delete()
        return Response(status=204)
