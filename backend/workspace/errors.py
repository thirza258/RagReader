"""One error envelope for every non-2xx response of the workspace API.

    {"error": {"code", "message", "retryable", "stage", "details"}}

Scoped to the new views (OwnedAPIView.get_exception_handler) so the legacy
endpoints keep their own response shapes.
"""
import logging

from django.core.exceptions import ObjectDoesNotExist, RequestDataTooBig
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response

from common.errors import PipelineError

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """A deliberate, user-facing failure with a stable machine-readable code."""

    def __init__(self, code, message, *, status=400, retryable=False, stage=None, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        self.stage = stage
        self.details = details


def error_object(code, message, *, retryable=False, stage=None, details=None):
    return {"code": code, "message": message, "retryable": retryable, "stage": stage, "details": details}


def error_response(code, message, *, status, retryable=False, stage=None, details=None, extra=None, headers=None):
    body = {"error": error_object(code, message, retryable=retryable, stage=stage, details=details)}
    if extra:
        body.update(extra)
    return Response(body, status=status, headers=headers)


def describe_exception(exc):
    """(status, error object) for any exception, without leaking internals."""
    if isinstance(exc, ApiError):
        return exc.status, error_object(exc.code, exc.message, retryable=exc.retryable, stage=exc.stage, details=exc.details)
    if isinstance(exc, PipelineError):
        return exc.http_status, error_object(exc.code, str(exc), retryable=exc.retryable)
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        message = str(exc.detail) if isinstance(exc, exceptions.AuthenticationFailed) else "Sign in to continue."
        return status.HTTP_401_UNAUTHORIZED, error_object("authentication_required", message)
    if isinstance(exc, (Http404, exceptions.NotFound, ObjectDoesNotExist)):
        return status.HTTP_404_NOT_FOUND, error_object("not_found", "Not found.")
    if isinstance(exc, exceptions.ValidationError):
        return status.HTTP_400_BAD_REQUEST, error_object(
            "invalid_request", "The request contains invalid or missing fields.", details=exc.detail,
        )
    if isinstance(exc, exceptions.ParseError):
        return status.HTTP_400_BAD_REQUEST, error_object("invalid_request", str(exc.detail))
    if isinstance(exc, RequestDataTooBig):
        return status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, error_object("file_too_large", "The request body is too large.")
    if isinstance(exc, exceptions.APIException):
        return exc.status_code, error_object(exc.default_code, str(exc.detail))
    logger.error("Workspace API request failed", exc_info=exc)
    return status.HTTP_500_INTERNAL_SERVER_ERROR, error_object(
        "internal_error", "The request could not be completed. Try again.", retryable=True,
    )


def api_exception_handler(exc, context):
    http_status, error = describe_exception(exc)
    headers = None
    auth_header = getattr(exc, "auth_header", None)
    if http_status == status.HTTP_401_UNAUTHORIZED and auth_header:
        headers = {"WWW-Authenticate": auth_header}
    wait = getattr(exc, "wait", None)
    if isinstance(exc, exceptions.Throttled) and wait:
        headers = {**(headers or {}), "Retry-After": str(int(wait))}
    return Response({"error": error}, status=http_status, headers=headers)
