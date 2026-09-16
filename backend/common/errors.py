"""Stable, public error messages without provider response bodies or secrets."""
from openai import APIConnectionError, APIStatusError, APITimeoutError


class PipelineError(RuntimeError):
    def __init__(self, code, message, *, retryable=False, http_status=500):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.http_status = http_status


def error_payload(exc, *, code="analysis_failed", message="Analysis failed. Retry the run; if it continues to fail, check the server logs."):
    if isinstance(exc, PipelineError):
        return {"error": str(exc), "error_code": exc.code, "retryable": exc.retryable}
    return {"error": message, "error_code": code, "retryable": True}


def provider_error(exc, operation, model):
    label = f"{operation} ({model})"
    if isinstance(exc, PipelineError):
        return exc
    if isinstance(exc, APITimeoutError):
        return PipelineError("provider_timeout", f"{label} timed out. Try again.", retryable=True, http_status=504)
    if isinstance(exc, APIConnectionError):
        return PipelineError("provider_unreachable", f"Could not connect to OpenRouter for {label.lower()}. Try again.", retryable=True, http_status=502)
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        if status in (401, 403):
            return PipelineError("provider_authentication", "OpenRouter rejected the API credentials. Check the configured API key and model permissions.", http_status=502)
        if status == 402:
            return PipelineError("provider_credits", "OpenRouter has insufficient credits for this request. Check the account balance.", http_status=502)
        if status == 429:
            return PipelineError("provider_rate_limit", f"OpenRouter rate-limited {label.lower()}. Try again shortly.", retryable=True, http_status=429)
        if status in (400, 404, 422):
            return PipelineError("provider_request_rejected", f"OpenRouter rejected {label.lower()}. Check model availability, supported inputs, and document size.", http_status=502)
        return PipelineError("provider_unavailable", f"OpenRouter could not complete {label.lower()}. Try again.", retryable=True, http_status=502)
    return PipelineError("provider_error", f"{label} failed. Check the provider configuration and try again.", retryable=True, http_status=502)
